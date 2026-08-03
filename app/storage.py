from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qdrant_client import QdrantClient, models

from app.access import (
    DEFAULT_ACCESS_CONTEXT,
    AccessContext,
    DocumentVisibility,
    can_manage,
    can_read,
)
from app.embeddings import Embedder
from app.ingestion import Chunk
from app.retrieval import Reranker, SparseEmbedder, content_tokens
from app.schemas import DocumentRecord, RetrievalProfile, RetrievalTrace, SourceResult
from app.security import security_flags

COLLECTION_NAME = "atlas_chunks_v2"
LEGACY_COLLECTION_NAME = "atlas_chunks"
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"
LOGGER = logging.getLogger("atlas.storage")
QDRANT_PAYLOAD_INDEX_FIELDS = frozenset(
    {
        "tenant_id",
        "document_id",
        "collection",
        "is_latest",
        "visibility",
        "owner_principal_id",
        "allowed_principals",
        "allowed_groups",
    }
)


def create_qdrant_client(
    *,
    mode: str,
    path: Path,
    url: str,
    api_key: str,
    timeout_seconds: int,
) -> QdrantClient:
    """Use the official client's local/server boundary without fallback.

    A configured server failure must remain a server failure. Falling back to
    an empty embedded index would make healthy-looking reads silently return no
    client documents.
    """
    if mode == "server":
        return QdrantClient(
            url=url,
            api_key=api_key or None,
            timeout=timeout_seconds,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(path))


def _batched(values: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


@dataclass(frozen=True)
class SearchOutcome:
    sources: list[SourceResult]
    trace: RetrievalTrace


class KnowledgeStore:
    def __init__(
        self,
        sqlite_path: Path,
        qdrant_path: Path,
        embedder: Embedder,
        *,
        qdrant_mode: str = "embedded",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        qdrant_timeout_seconds: int = 5,
    ) -> None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._embedder = embedder
        self._sparse_embedder = SparseEmbedder()
        self._qdrant_mode = qdrant_mode
        self._qdrant = create_qdrant_client(
            mode=qdrant_mode,
            path=qdrant_path,
            url=qdrant_url,
            api_key=qdrant_api_key,
            timeout_seconds=qdrant_timeout_seconds,
        )
        self._initialize()

    def _initialize(self) -> None:
        self._create_documents_table()
        self._ensure_document_columns()
        self._remove_global_hash_constraint()
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_version
            ON documents (tenant_id, source_id, version)
            """
        )
        # Content uniqueness applies to the live revision only. Immutable
        # version history and archived connector documents must be allowed to
        # repeat a checksum, otherwise an upstream revert can never be indexed.
        self._connection.execute("DROP INDEX IF EXISTS idx_documents_tenant_hash")
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_tenant_hash
            ON documents (tenant_id, sha256) WHERE status = 'indexed'
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_connector
            ON documents (tenant_id, connector_instance, status)
            """
        )
        self._connection.commit()
        if not self._qdrant.collection_exists(COLLECTION_NAME):
            self._qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    DENSE_VECTOR: models.VectorParams(
                        size=self._embedder.vector_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            self._migrate_legacy_collection()
        if self._qdrant_mode == "server":
            self._ensure_payload_indexes()
        self._backfill_access_payloads()
        self.reconcile_latest_flags()

    def _ensure_payload_indexes(self) -> None:
        schemas: dict[str, models.PayloadSchemaType | models.KeywordIndexParams] = {
            "tenant_id": models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=True,
            ),
            "document_id": models.PayloadSchemaType.KEYWORD,
            "collection": models.PayloadSchemaType.KEYWORD,
            "is_latest": models.PayloadSchemaType.BOOL,
            "visibility": models.PayloadSchemaType.KEYWORD,
            "owner_principal_id": models.PayloadSchemaType.KEYWORD,
            "allowed_principals": models.PayloadSchemaType.KEYWORD,
            "allowed_groups": models.PayloadSchemaType.KEYWORD,
        }
        for field_name, field_schema in schemas.items():
            self._qdrant.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )

    def payload_index_fields(self) -> set[str]:
        """Server diagnostic used by the production-adaptation gate."""
        info = self._qdrant.get_collection(COLLECTION_NAME)
        return set((info.payload_schema or {}).keys())

    def _create_documents_table(self, name: str = "documents") -> None:
        self._connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {name} (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                version INTEGER NOT NULL,
                supersedes_document_id TEXT,
                filename TEXT NOT NULL,
                title TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'demo',
                owner_principal_id TEXT NOT NULL DEFAULT 'demo-user',
                visibility TEXT NOT NULL DEFAULT 'tenant',
                allowed_principals TEXT NOT NULL DEFAULT '[]',
                allowed_groups TEXT NOT NULL DEFAULT '[]',
                connector_name TEXT NOT NULL DEFAULT '',
                connector_instance TEXT NOT NULL DEFAULT ''
            )
            """
        )

    def _ensure_document_columns(self) -> None:
        """Add lifecycle columns without invalidating an existing local index."""
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        additions = {
            "source_id": "TEXT NOT NULL DEFAULT ''",
            "source_uri": "TEXT NOT NULL DEFAULT ''",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "supersedes_document_id": "TEXT",
            "tenant_id": "TEXT NOT NULL DEFAULT 'demo'",
            "owner_principal_id": "TEXT NOT NULL DEFAULT 'demo-user'",
            "visibility": "TEXT NOT NULL DEFAULT 'tenant'",
            "allowed_principals": "TEXT NOT NULL DEFAULT '[]'",
            "allowed_groups": "TEXT NOT NULL DEFAULT '[]'",
            "connector_name": "TEXT NOT NULL DEFAULT ''",
            "connector_instance": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                self._connection.execute(
                    f"ALTER TABLE documents ADD COLUMN {name} {definition}"
                )
        self._connection.execute(
            """
            UPDATE documents
            SET source_id = id
            WHERE source_id = ''
            """
        )
        self._connection.execute(
            """
            UPDATE documents
            SET source_uri = 'legacy-upload://' || filename
            WHERE source_uri = ''
            """
        )

    def _remove_global_hash_constraint(self) -> None:
        has_global_hash_index = False
        for index in self._connection.execute(
            "PRAGMA index_list(documents)"
        ).fetchall():
            if not index["unique"]:
                continue
            columns = [
                row["name"]
                for row in self._connection.execute(
                    f"PRAGMA index_info('{index['name']}')"
                ).fetchall()
            ]
            if columns == ["sha256"]:
                has_global_hash_index = True
                break
        if not has_global_hash_index:
            return
        self._connection.execute("DROP INDEX IF EXISTS idx_documents_source_version")
        self._connection.execute("DROP INDEX IF EXISTS idx_documents_tenant_hash")
        self._connection.execute("DROP TABLE IF EXISTS documents_acl")
        self._create_documents_table("documents_acl")
        columns = (
            "id, source_id, source_uri, version, supersedes_document_id, "
            "filename, title, collection_name, mime_type, size_bytes, sha256, "
            "chunk_count, status, created_at, tenant_id, owner_principal_id, "
            "visibility, allowed_principals, allowed_groups, connector_name, "
            "connector_instance"
        )
        self._connection.execute(
            f"INSERT INTO documents_acl ({columns}) SELECT {columns} FROM documents"
        )
        self._connection.execute("DROP TABLE documents")
        self._connection.execute("ALTER TABLE documents_acl RENAME TO documents")

    def _migrate_legacy_collection(self) -> None:
        """Copy pre-v2 points so existing local users do not lose their index."""
        if not self._qdrant.collection_exists(LEGACY_COLLECTION_NAME):
            return
        offset = None
        while True:
            points, offset = self._qdrant.scroll(
                collection_name=LEGACY_COLLECTION_NAME,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            indexed_texts = [
                f"{(point.payload or {}).get('title', '')}\n"
                f"{(point.payload or {}).get('text', '')}"
                for point in points
            ]
            dense_vectors = self._embedder.embed(indexed_texts) if indexed_texts else []
            migrated = []
            for point, indexed_text, dense_vector in zip(
                points,
                indexed_texts,
                dense_vectors,
                strict=True,
            ):
                payload = point.payload or {}
                migrated.append(
                    models.PointStruct(
                        id=point.id,
                        vector={
                            DENSE_VECTOR: dense_vector,
                            SPARSE_VECTOR: self._sparse_embedder.embed(indexed_text),
                        },
                        payload=payload,
                    )
                )
            if migrated:
                self._qdrant.upsert(
                    collection_name=COLLECTION_NAME,
                    points=migrated,
                    wait=True,
                )
            if offset is None:
                break

    def _backfill_access_payloads(self) -> None:
        """Make pre-ACL vectors visible only through their migrated document ACL."""
        documents = {
            row["id"]: row
            for row in self._connection.execute(
                """
                SELECT id, tenant_id, owner_principal_id, visibility,
                       allowed_principals, allowed_groups
                FROM documents
                """
            ).fetchall()
        }
        offset = None
        while True:
            points, offset = self._qdrant.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=models.Filter(
                    must=[
                        models.IsEmptyCondition(
                            is_empty=models.PayloadField(key="tenant_id")
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for point in points:
                payload = point.payload or {}
                document = documents.get(str(payload.get("document_id", "")))
                if document is None or payload.get("tenant_id"):
                    continue
                self._qdrant.set_payload(
                    collection_name=COLLECTION_NAME,
                    points=[point.id],
                    payload={
                        "tenant_id": document["tenant_id"],
                        "owner_principal_id": document["owner_principal_id"],
                        "visibility": document["visibility"],
                        "allowed_principals": json.loads(
                            document["allowed_principals"]
                        ),
                        "allowed_groups": json.loads(document["allowed_groups"]),
                    },
                    wait=True,
                )
            if offset is None:
                break

    def reconcile_latest_flags(self) -> int:
        """Repair `is_latest` payloads that disagree with document status.

        Re-indexing flips the outgoing version's payload to `is_latest=false`
        inside the SQLite transaction, but Qdrant payloads are not part of that
        transaction. If the process dies between the payload write and the
        commit, SQLite still reports `indexed` while retrieval filters the
        vectors out, making a live document silently unsearchable. Startup
        reconciliation closes that window in the same spirit as the ingestion
        worker's interrupted-job recovery.
        """
        rows = self._connection.execute("SELECT id, status FROM documents").fetchall()
        if not rows:
            return 0
        groups = (
            ([row["id"] for row in rows if row["status"] == "indexed"], True),
            ([row["id"] for row in rows if row["status"] != "indexed"], False),
        )
        repaired = 0
        for document_ids, expected in groups:
            for batch in _batched(document_ids, 100):
                disagreeing = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchAny(any=batch),
                        ),
                        models.FieldCondition(
                            key="is_latest",
                            match=models.MatchValue(value=not expected),
                        ),
                    ]
                )
                found = self._qdrant.count(
                    collection_name=COLLECTION_NAME,
                    count_filter=disagreeing,
                    exact=True,
                ).count
                if not found:
                    continue
                self._qdrant.set_payload(
                    collection_name=COLLECTION_NAME,
                    payload={"is_latest": expected},
                    points=disagreeing,
                    wait=True,
                )
                repaired += int(found)
        if repaired:
            LOGGER.warning(
                "Repaired stale latest-version markers",
                extra={"event": "index.latest_flags.repaired", "repaired": repaired},
            )
        return repaired

    def close(self) -> None:
        self._connection.close()
        self._qdrant.close()

    def healthcheck(self) -> bool:
        self._connection.execute("SELECT 1").fetchone()
        return self._qdrant.collection_exists(COLLECTION_NAME)

    def count_documents(
        self,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> int:
        return len(self.list_documents(access))

    def find_by_hash(
        self,
        sha256: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> DocumentRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM documents
            WHERE tenant_id = ? AND sha256 = ? AND status = 'indexed'
            """,
            (access.tenant_id, sha256),
        ).fetchone()
        return self._to_document(row) if row else None

    def latest_for_source(
        self,
        source_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> DocumentRecord | None:
        """Return the newest revision of a source regardless of its status."""
        row = self._connection.execute(
            """
            SELECT * FROM documents
            WHERE tenant_id = ? AND source_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            (access.tenant_id, source_id),
        ).fetchone()
        return self._to_document(row) if row else None

    def list_connector_documents(
        self,
        connector_instance: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[DocumentRecord]:
        """Live documents currently owned by one connector instance."""
        rows = self._connection.execute(
            """
            SELECT * FROM documents
            WHERE tenant_id = ? AND connector_instance = ? AND status = 'indexed'
            ORDER BY created_at
            """,
            (access.tenant_id, connector_instance),
        ).fetchall()
        return [self._to_document(row) for row in rows]

    def get_document(
        self,
        document_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        *,
        manage: bool = False,
    ) -> DocumentRecord | None:
        row = self._connection.execute(
            "SELECT * FROM documents WHERE id = ? AND tenant_id = ?",
            (document_id, access.tenant_id),
        ).fetchone()
        if row is None:
            return None
        document = self._to_document(row)
        permitted = (
            can_manage(
                access=access,
                tenant_id=document.tenant_id,
                owner_principal_id=document.owner_principal_id,
            )
            if manage
            else self._can_read_document(document, access)
        )
        return document if permitted else None

    def list_documents(
        self,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[DocumentRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM documents
            WHERE tenant_id = ? AND status = 'indexed'
            ORDER BY created_at DESC, title
            """,
            (access.tenant_id,),
        ).fetchall()
        documents = [self._to_document(row) for row in rows]
        return [
            document
            for document in documents
            if self._can_read_document(document, access)
        ]

    def list_document_versions(
        self,
        source_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[DocumentRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM documents
            WHERE tenant_id = ? AND source_id = ?
            ORDER BY version DESC
            """,
            (access.tenant_id, source_id),
        ).fetchall()
        documents = [self._to_document(row) for row in rows]
        return [
            document
            for document in documents
            if self._can_read_document(document, access)
        ]

    def add_document(
        self,
        *,
        filename: str,
        title: str,
        collection: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        chunks: list[Chunk],
        source_uri: str,
        source_id: str | None = None,
        version: int = 1,
        supersedes_document_id: str | None = None,
        connector_name: str = "",
        connector_instance: str = "",
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
    ) -> DocumentRecord:
        document_id = str(uuid.uuid4())
        source_id = source_id or str(uuid.uuid4())
        created_at = datetime.now(UTC)
        points = self._build_points(
            document_id=document_id,
            source_id=source_id,
            source_uri=source_uri,
            version=version,
            sha256=sha256,
            filename=filename,
            title=title,
            collection=collection,
            chunks=chunks,
            is_latest=True,
            tenant_id=access.tenant_id,
            owner_principal_id=access.principal_id,
            visibility=visibility,
            allowed_principals=allowed_principals,
            allowed_groups=allowed_groups,
        )
        self._qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
        document = DocumentRecord(
            id=document_id,
            source_id=source_id,
            source_uri=source_uri,
            version=version,
            supersedes_document_id=supersedes_document_id,
            filename=filename,
            title=title,
            collection=collection,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            chunk_count=len(chunks),
            status="indexed",
            created_at=created_at,
            tenant_id=access.tenant_id,
            owner_principal_id=access.principal_id,
            visibility=visibility,
            allowed_principals=allowed_principals,
            allowed_groups=allowed_groups,
            connector_name=connector_name,
            connector_instance=connector_instance,
        )
        try:
            self._insert_document(document)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            self._delete_vectors(document_id)
            raise
        return document

    def replace_document(
        self,
        *,
        current: DocumentRecord,
        filename: str,
        title: str,
        collection: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        chunks: list[Chunk],
        source_uri: str,
    ) -> DocumentRecord:
        document_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        version = current.version + 1
        replacement = DocumentRecord(
            id=document_id,
            source_id=current.source_id,
            source_uri=source_uri,
            version=version,
            supersedes_document_id=current.id,
            filename=filename,
            title=title,
            collection=collection,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            chunk_count=len(chunks),
            status="indexed",
            created_at=created_at,
            tenant_id=current.tenant_id,
            owner_principal_id=current.owner_principal_id,
            visibility=current.visibility,
            allowed_principals=current.allowed_principals,
            allowed_groups=current.allowed_groups,
            connector_name=current.connector_name,
            connector_instance=current.connector_instance,
        )
        points = self._build_points(
            document_id=document_id,
            source_id=current.source_id,
            source_uri=source_uri,
            version=version,
            sha256=sha256,
            filename=filename,
            title=title,
            collection=collection,
            chunks=chunks,
            is_latest=False,
            tenant_id=current.tenant_id,
            owner_principal_id=current.owner_principal_id,
            visibility=current.visibility,
            allowed_principals=current.allowed_principals,
            allowed_groups=current.allowed_groups,
        )
        self._qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            claimed = self._connection.execute(
                """
                UPDATE documents
                SET status = 'reindexing'
                WHERE id = ? AND status = 'indexed'
                """,
                (current.id,),
            )
            if claimed.rowcount != 1:
                raise ValueError("The document is already being replaced.")
            self._set_latest(current.id, False)
            self._set_latest(document_id, True)
            self._insert_document(replacement)
            self._connection.execute(
                "UPDATE documents SET status = 'superseded' WHERE id = ?",
                (current.id,),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            self._set_latest(current.id, True)
            self._delete_vectors(document_id)
            raise
        self._delete_vectors(current.id)
        return replacement

    def index_source_version(
        self,
        *,
        source_id: str,
        source_uri: str,
        filename: str,
        title: str,
        collection: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        chunks: list[Chunk],
        connector_name: str,
        connector_instance: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
    ) -> tuple[DocumentRecord, str]:
        """Index a connector source, continuing its immutable version chain.

        Returns the stored revision and whether it was `created` or `updated`.
        """
        latest = self.latest_for_source(source_id, access)
        if latest is None:
            document = self.add_document(
                filename=filename,
                title=title,
                collection=collection,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=sha256,
                chunks=chunks,
                source_uri=source_uri,
                source_id=source_id,
                connector_name=connector_name,
                connector_instance=connector_instance,
                access=access,
                visibility=visibility,
                allowed_principals=allowed_principals,
                allowed_groups=allowed_groups,
            )
            return document, "created"
        if not can_manage(
            access=access,
            tenant_id=latest.tenant_id,
            owner_principal_id=latest.owner_principal_id,
        ):
            raise PermissionError(
                "The source is owned by another principal in this tenant."
            )
        if latest.status == "indexed":
            return (
                self.replace_document(
                    current=latest,
                    filename=filename,
                    title=title,
                    collection=collection,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    chunks=chunks,
                    source_uri=source_uri,
                ),
                "updated",
            )
        # The source was archived or its live revision was removed. Continue the
        # version sequence instead of restarting at version 1.
        document = self.add_document(
            filename=filename,
            title=title,
            collection=collection,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            chunks=chunks,
            source_uri=source_uri,
            source_id=source_id,
            version=latest.version + 1,
            supersedes_document_id=latest.id,
            connector_name=connector_name or latest.connector_name,
            connector_instance=connector_instance or latest.connector_instance,
            access=access,
            visibility=visibility,
            allowed_principals=allowed_principals,
            allowed_groups=allowed_groups,
        )
        return document, "created"

    def archive_document(
        self,
        document_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> bool:
        """Retire a document without discarding its version history.

        Every retrieval representation of every version is removed, so an
        archived source cannot be cited, while the metadata rows remain as an
        audit trail of what the connector once published.
        """
        document = self.get_document(document_id, access, manage=True)
        if document is None:
            return False
        versions = self.list_document_versions(document.source_id, access)
        version_ids = [version.id for version in versions] or [document.id]
        previous_statuses = {version.id: version.status for version in versions}
        self._connection.execute(
            """
            UPDATE documents SET status = 'archived'
            WHERE tenant_id = ? AND source_id = ? AND status = 'indexed'
            """,
            (access.tenant_id, document.source_id),
        )
        self._connection.commit()
        try:
            self._qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchAny(any=version_ids),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception:
            for version_id, previous_status in previous_statuses.items():
                self._connection.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (previous_status, version_id),
                )
            self._connection.commit()
            raise
        return True

    def count_vectors_for_document(self, document_id: str) -> int:
        """Diagnostic used by the orphaned-vector tests and the demo script."""
        return int(
            self._qdrant.count(
                collection_name=COLLECTION_NAME,
                count_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                ),
                exact=True,
            ).count
        )

    def all_vector_document_ids(self) -> set[str]:
        """Every document ID that still owns at least one vector."""
        identifiers: set[str] = set()
        offset = None
        while True:
            points, offset = self._qdrant.scroll(
                collection_name=COLLECTION_NAME,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                document_id = (point.payload or {}).get("document_id")
                if document_id:
                    identifiers.add(str(document_id))
            if offset is None:
                break
        return identifiers

    def _build_points(
        self,
        *,
        document_id: str,
        source_id: str,
        source_uri: str,
        version: int,
        sha256: str,
        filename: str,
        title: str,
        collection: str,
        chunks: list[Chunk],
        is_latest: bool,
        tenant_id: str,
        owner_principal_id: str,
        visibility: DocumentVisibility,
        allowed_principals: tuple[str, ...],
        allowed_groups: tuple[str, ...],
    ) -> list[models.PointStruct]:
        chunk_texts = [
            f"{title}\n{chunk.index_text or chunk.text}" for chunk in chunks
        ]
        vectors = self._embedder.embed(chunk_texts)
        points = []
        for index, (chunk, vector, chunk_text) in enumerate(
            zip(chunks, vectors, chunk_texts, strict=True)
        ):
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        DENSE_VECTOR: vector,
                        SPARSE_VECTOR: self._sparse_embedder.embed(chunk_text),
                    },
                    payload={
                        "document_id": document_id,
                        "source_id": source_id,
                        "source_uri": source_uri,
                        "document_version": version,
                        "document_sha256": sha256,
                        "is_latest": is_latest,
                        "chunk_index": index,
                        "filename": filename,
                        "title": title,
                        "collection": collection,
                        "page": chunk.page,
                        "text": chunk.text,
                        "context_id": (
                            f"{document_id}:{chunk.context_id}"
                            if chunk.context_id
                            else None
                        ),
                        "tenant_id": tenant_id,
                        "owner_principal_id": owner_principal_id,
                        "visibility": visibility,
                        "allowed_principals": list(allowed_principals),
                        "allowed_groups": list(allowed_groups),
                        "security_flags": list(security_flags(chunk.text)),
                    },
                )
            )
        return points

    def _insert_document(self, document: DocumentRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO documents (
                id, source_id, source_uri, version, supersedes_document_id,
                filename, title, collection_name, mime_type, size_bytes,
                sha256, chunk_count, status, created_at, tenant_id,
                owner_principal_id, visibility, allowed_principals, allowed_groups,
                connector_name, connector_instance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.id,
                document.source_id,
                document.source_uri,
                document.version,
                document.supersedes_document_id,
                document.filename,
                document.title,
                document.collection,
                document.mime_type,
                document.size_bytes,
                document.sha256,
                document.chunk_count,
                document.status,
                document.created_at.isoformat(),
                document.tenant_id,
                document.owner_principal_id,
                document.visibility,
                json.dumps(document.allowed_principals),
                json.dumps(document.allowed_groups),
                document.connector_name,
                document.connector_instance,
            ),
        )

    def _set_latest(self, document_id: str, is_latest: bool) -> None:
        self._qdrant.set_payload(
            collection_name=COLLECTION_NAME,
            payload={"is_latest": is_latest},
            points=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            ),
            wait=True,
        )

    def _delete_vectors(self, document_id: str) -> None:
        self._qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def delete_document(
        self,
        document_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> bool:
        document = self.get_document(document_id, access, manage=True)
        if document is None:
            return False
        versions = self.list_document_versions(document.source_id, access)
        version_ids = [version.id for version in versions]
        previous_statuses = {version.id: version.status for version in versions}
        self._connection.execute(
            """
            UPDATE documents SET status = 'deleting'
            WHERE tenant_id = ? AND source_id = ?
            """,
            (access.tenant_id, document.source_id),
        )
        self._connection.commit()
        try:
            self._qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchAny(any=version_ids),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception:
            for version_id, previous_status in previous_statuses.items():
                self._connection.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (previous_status, version_id),
                )
            self._connection.commit()
            raise
        self._connection.execute(
            "DELETE FROM documents WHERE tenant_id = ? AND source_id = ?",
            (access.tenant_id, document.source_id),
        )
        self._connection.commit()
        return True

    def search(
        self,
        question: str,
        collections: list[str],
        limit: int,
        min_score: float,
        semantic_evidence_floor: float,
        score_ratio: float,
        profile: RetrievalProfile,
        candidate_limit: int,
        deduplicate_contexts: bool = False,
        reranker: Reranker | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> SearchOutcome:
        started = time.perf_counter()
        query_vector = (
            self._embedder.embed([question])[0] if profile != "sparse" else None
        )
        must_conditions: list[models.FieldCondition | models.Filter] = [
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=access.tenant_id),
            ),
            models.Filter(
                should=[
                    models.FieldCondition(
                        key="visibility",
                        match=models.MatchValue(value="tenant"),
                    ),
                    models.FieldCondition(
                        key="owner_principal_id",
                        match=models.MatchValue(value=access.principal_id),
                    ),
                    models.FieldCondition(
                        key="allowed_principals",
                        match=models.MatchValue(value=access.principal_id),
                    ),
                    *[
                        models.FieldCondition(
                            key="allowed_groups",
                            match=models.MatchValue(value=group),
                        )
                        for group in sorted(access.groups)
                    ],
                ],
            ),
        ]
        if collections:
            must_conditions.append(
                models.FieldCondition(
                    key="collection",
                    match=models.MatchAny(any=collections),
                )
            )
        query_filter = models.Filter(
            must=must_conditions,
            must_not=[
                models.FieldCondition(
                    key="is_latest",
                    match=models.MatchValue(value=False),
                )
            ]
        )
        search_limit = (
            candidate_limit
            if profile == "hybrid-reranked" or deduplicate_contexts
            else limit
        )
        if profile == "dense":
            if query_vector is None:
                raise RuntimeError("Dense retrieval requires a query vector")
            result = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                using=DENSE_VECTOR,
                query_filter=query_filter,
                limit=search_limit,
                score_threshold=min_score,
                with_payload=True,
            )
            fusion = None
        elif profile == "sparse":
            result = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=self._sparse_embedder.embed(question),
                using=SPARSE_VECTOR,
                query_filter=query_filter,
                limit=search_limit,
                with_payload=True,
            )
            fusion = None
        else:
            if query_vector is None:
                raise RuntimeError("Hybrid retrieval requires a query vector")
            result = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    models.Prefetch(
                        query=query_vector,
                        using=DENSE_VECTOR,
                        filter=query_filter,
                        limit=candidate_limit,
                    ),
                    models.Prefetch(
                        query=self._sparse_embedder.embed(question),
                        using=SPARSE_VECTOR,
                        filter=query_filter,
                        limit=candidate_limit,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=search_limit,
                with_payload=True,
            )
            fusion = "reciprocal-rank-fusion"
        points = result.points
        retrieval_ms = round((time.perf_counter() - started) * 1000)
        rerank_ms = 0
        rerank_scores_by_id: dict[str, float] = {}
        query_tokens = set(content_tokens(question))
        if self._embedder.name == "hash":
            points = [
                point
                for point in points
                if query_tokens
                & set(content_tokens(str((point.payload or {}).get("text", ""))))
            ]
        elif points and profile != "sparse":
            has_lexical_evidence = any(
                query_tokens & set(content_tokens(str((point.payload or {}).get("text", ""))))
                for point in points
            )
            if not has_lexical_evidence:
                dense_probe = self._qdrant.query_points(
                    collection_name=COLLECTION_NAME,
                    query=query_vector,
                    using=DENSE_VECTOR,
                    query_filter=query_filter,
                    limit=1,
                    with_payload=False,
                ).points
                if not dense_probe or float(dense_probe[0].score) < semantic_evidence_floor:
                    points = []
        elif points:
            points = [
                point
                for point in points
                if query_tokens
                & set(content_tokens(str((point.payload or {}).get("text", ""))))
            ]
        if deduplicate_contexts:
            deduplicated = []
            seen_contexts: set[str] = set()
            for point in points:
                payload = point.payload or {}
                context_id = str(payload.get("context_id") or point.id)
                if context_id in seen_contexts:
                    continue
                seen_contexts.add(context_id)
                deduplicated.append(point)
            points = deduplicated
        if profile == "hybrid-reranked" and points and reranker:
            rerank_started = time.perf_counter()
            passages = [str((point.payload or {}).get("text", "")) for point in points]
            rerank_scores = reranker.score(question, passages)
            rerank_scores_by_id = {
                str(point.id): score
                for point, score in zip(points, rerank_scores, strict=True)
            }
            points = [
                point
                for _, point in sorted(
                    zip(rerank_scores, points, strict=True),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
            ][:limit]
            rerank_ms = round((time.perf_counter() - rerank_started) * 1000)
        if profile != "sparse":
            points = [point for point in points if float(point.score) >= min_score]
        if points and profile == "dense":
            relative_floor = float(points[0].score) * score_ratio
            points = [point for point in points if float(point.score) >= relative_floor]
        points = points[:limit]
        sources: list[SourceResult] = []
        for rank, point in enumerate(points, start=1):
            payload = point.payload or {}
            sources.append(
                SourceResult(
                    rank=rank,
                    document_id=str(payload["document_id"]),
                    source_id=str(payload.get("source_id") or payload["document_id"]),
                    source_uri=str(payload.get("source_uri") or ""),
                    document_version=int(payload.get("document_version") or 1),
                    document_sha256=str(payload.get("document_sha256") or ""),
                    chunk_id=str(point.id),
                    title=str(payload["title"]),
                    filename=str(payload["filename"]),
                    collection=str(payload["collection"]),
                    page=int(payload["page"]) if payload.get("page") else None,
                    passage=str(payload["text"]),
                    score=round(float(point.score), 4),
                    rerank_score=(
                        round(rerank_scores_by_id[str(point.id)], 4)
                        if str(point.id) in rerank_scores_by_id
                        else None
                    ),
                    security_flags=tuple(
                        payload.get("security_flags")
                        or security_flags(str(payload.get("text", "")))
                    ),
                )
            )
        return SearchOutcome(
            sources=sources,
            trace=RetrievalTrace(
                profile=profile,
                candidate_limit=candidate_limit,
                candidates_considered=len(result.points),
                fusion=fusion,
                reranker=reranker.name if profile == "hybrid-reranked" and reranker else None,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
            ),
        )

    @staticmethod
    def _to_document(row: sqlite3.Row) -> DocumentRecord:
        raw = dict(row)
        return DocumentRecord(
            id=raw["id"],
            source_id=raw["source_id"],
            source_uri=raw["source_uri"],
            version=raw["version"],
            supersedes_document_id=raw["supersedes_document_id"],
            filename=raw["filename"],
            title=raw["title"],
            collection=raw["collection_name"],
            mime_type=raw["mime_type"],
            size_bytes=raw["size_bytes"],
            sha256=raw["sha256"],
            chunk_count=raw["chunk_count"],
            status=raw["status"],
            created_at=datetime.fromisoformat(raw["created_at"]),
            tenant_id=raw["tenant_id"],
            owner_principal_id=raw["owner_principal_id"],
            visibility=raw["visibility"],
            allowed_principals=tuple(json.loads(raw["allowed_principals"])),
            allowed_groups=tuple(json.loads(raw["allowed_groups"])),
            connector_name=raw.get("connector_name") or "",
            connector_instance=raw.get("connector_instance") or "",
        )

    @staticmethod
    def _can_read_document(
        document: DocumentRecord,
        access: AccessContext,
    ) -> bool:
        return can_read(
            access=access,
            tenant_id=document.tenant_id,
            owner_principal_id=document.owner_principal_id,
            visibility=document.visibility,
            allowed_principals=document.allowed_principals,
            allowed_groups=document.allowed_groups,
        )

    def debug_snapshot(self) -> str:
        """Small diagnostic used by local development without exposing document text."""
        return json.dumps({"documents": self.count_documents(), "embedder": self._embedder.name})
