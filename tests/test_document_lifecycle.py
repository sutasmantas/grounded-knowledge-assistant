from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.embeddings import HashEmbedder
from app.ingestion import Chunk
from app.service import KnowledgeService
from app.storage import KnowledgeStore


def test_existing_metadata_database_receives_lifecycle_columns(
    tmp_path: Path,
) -> None:
    sqlite_path = tmp_path / "metadata.db"
    connection = sqlite3.connect(sqlite_path)
    connection.execute(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            title TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            chunk_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO documents VALUES (
            'legacy-id', 'legacy.md', 'Legacy', 'General', 'text/markdown',
            42, 'legacy-checksum', 1, 'indexed', '2026-07-30T10:00:00+00:00'
        )
        """
    )
    connection.commit()
    connection.close()

    store = KnowledgeStore(sqlite_path, tmp_path / "qdrant", HashEmbedder())
    try:
        migrated = store.get_document("legacy-id")
        assert migrated is not None
        assert migrated.source_id == "legacy-id"
        assert migrated.source_uri == "legacy-upload://legacy.md"
        assert migrated.version == 1
        assert migrated.supersedes_document_id is None
        assert migrated.tenant_id == "demo"
        assert migrated.owner_principal_id == "demo-user"
        indexes = store._connection.execute(
            "PRAGMA index_list(documents)"
        ).fetchall()
        unique_columns = {
            tuple(
                row["name"]
                for row in store._connection.execute(
                    f"PRAGMA index_info('{index['name']}')"
                ).fetchall()
            )
            for index in indexes
            if index["unique"]
        }
        assert ("sha256",) not in unique_columns
        assert ("tenant_id", "sha256") in unique_columns
    finally:
        store.close()


def test_failed_reindex_restores_current_version_and_removes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "policy.md"
    source_path.write_text(
        "# Routing Policy\nThe current routing desk is Mercury.",
        encoding="utf-8",
    )
    service = KnowledgeService(
        Settings(
            data_dir=tmp_path / "runtime",
            sample_documents_dir=tmp_path / "no-samples",
            embedding_provider="hash",
            generation_provider="extractive",
        )
    )
    try:
        current = service.ingest_path(
            source_path,
            filename="policy.md",
            title="Routing Policy",
            collection="Operations",
            mime_type="text/markdown",
            source_uri="handbook://routing-policy",
        )

        def fail_insert(_document: object) -> None:
            raise RuntimeError("simulated metadata failure")

        monkeypatch.setattr(service.store, "_insert_document", fail_insert)
        with pytest.raises(RuntimeError, match="simulated metadata failure"):
            service.store.replace_document(
                current=current,
                filename="policy.md",
                title="Routing Policy",
                collection="Operations",
                mime_type="text/markdown",
                size_bytes=52,
                sha256="replacement-checksum",
                chunks=[
                    Chunk(
                        page=1,
                        text="The proposed routing desk is Atlas.",
                    )
                ],
                source_uri=current.source_uri,
            )

        documents = service.list_documents()
        assert [(document.id, document.status) for document in documents] == [
            (current.id, "indexed")
        ]
        response = service.query(
            "Which routing desk is named Mercury?",
            [],
            top_k=5,
        )
        assert {source.document_id for source in response.sources} == {current.id}
        assert all("Atlas" not in source.passage for source in response.sources)
    finally:
        service.close()


def test_startup_repairs_a_stale_latest_marker(tmp_path: Path) -> None:
    """An indexed document must never stay invisible to retrieval.

    Re-indexing flips the outgoing version's payload before the metadata commit.
    Qdrant payloads are not part of that transaction, so a crash in that window
    can leave a document `indexed` in SQLite with vectors filtered out of every
    search. Startup reconciliation must repair it.
    """
    source_path = tmp_path / "routing.md"
    source_path.write_text(
        "# Routing Policy\nThe incident routing desk is Mercury.",
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )
    service = KnowledgeService(settings)
    try:
        document = service.ingest_path(
            source_path,
            filename="routing.md",
            title="Routing Policy",
            collection="Operations",
            mime_type="text/markdown",
        )
        assert service.query("Which desk owns incident routing?", [], 5).sources

        # Reproduce the crash window.
        service.store._set_latest(document.id, False)
        assert service.query("Which desk owns incident routing?", [], 5).sources == []
        assert [record.status for record in service.list_documents()] == ["indexed"]
    finally:
        service.close()

    restarted = KnowledgeService(settings)
    try:
        # The store repairs the marker while opening, so retrieval works again.
        response = restarted.query("Which desk owns incident routing?", [], 5)
        assert {source.document_id for source in response.sources} == {document.id}
        assert restarted.store.reconcile_latest_flags() == 0
    finally:
        restarted.close()


def test_reconciliation_leaves_retired_versions_hidden(tmp_path: Path) -> None:
    source_path = tmp_path / "routing.md"
    source_path.write_text(
        "# Routing Policy\nThe incident routing desk is Mercury.",
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )
    service = KnowledgeService(settings)
    try:
        current = service.ingest_path(
            source_path,
            filename="routing.md",
            title="Routing Policy",
            collection="Operations",
            mime_type="text/markdown",
        )
        replacement = service.store.replace_document(
            current=current,
            filename="routing.md",
            title="Routing Policy",
            collection="Operations",
            mime_type="text/markdown",
            size_bytes=52,
            sha256="replacement-checksum",
            chunks=[Chunk(page=1, text="The incident routing desk is Atlas.")],
            source_uri=current.source_uri,
        )
    finally:
        service.close()

    restarted = KnowledgeService(settings)
    try:
        assert restarted.store.reconcile_latest_flags() == 0
        assert restarted.store.count_vectors_for_document(current.id) == 0
        response = restarted.query("Which desk owns incident routing?", [], 5)
        assert {source.document_id for source in response.sources} == {replacement.id}
    finally:
        restarted.close()


def test_failed_vector_delete_restores_document_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "retention.md"
    source_path.write_text(
        "# Retention Policy\nThe retention owner is the Records desk.",
        encoding="utf-8",
    )
    service = KnowledgeService(
        Settings(
            data_dir=tmp_path / "runtime",
            sample_documents_dir=tmp_path / "no-samples",
            embedding_provider="hash",
            generation_provider="extractive",
        )
    )
    try:
        current = service.ingest_path(
            source_path,
            filename="retention.md",
            title="Retention Policy",
            collection="Operations",
            mime_type="text/markdown",
        )

        def fail_delete(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated vector-store failure")

        monkeypatch.setattr(service.store._qdrant, "delete", fail_delete)
        with pytest.raises(RuntimeError, match="simulated vector-store failure"):
            service.delete_document(current.id)

        documents = service.list_documents()
        assert [(document.id, document.status) for document in documents] == [
            (current.id, "indexed")
        ]
        response = service.query(
            "Who is the retention owner?",
            [],
            top_k=5,
        )
        assert {source.document_id for source in response.sources} == {current.id}
    finally:
        service.close()
