from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import UploadFile
from opentelemetry import trace

from app.access import (
    DEFAULT_ACCESS_CONTEXT,
    AccessContext,
    DocumentVisibility,
)
from app.config import Settings
from app.connectors.base import Connector, ConnectorSecurityError
from app.connectors.local_folder import LocalFolderConnector
from app.connectors.web import UrlConnector
from app.embeddings import create_embedder
from app.generation import GenerationResult, create_generator
from app.ingestion import chunk_pages
from app.jobs import (
    IngestionJobRunner,
    IngestionJobStore,
    PermanentJobError,
)
from app.observability import TRACER, tenant_hash
from app.parsers import ParseRequest, ParserRegistry
from app.retrieval import Reranker, create_reranker
from app.schemas import (
    ConnectorDescriptor,
    DocumentRecord,
    GenerationTrace,
    IngestionJobRecord,
    LocalFolderSyncRequest,
    QueryResponse,
    RetrievalProfile,
    SyncReport,
    UrlSyncRequest,
)
from app.security import reject_direct_prompt_injection
from app.storage import KnowledgeStore
from app.sync import ConnectorSynchronizer

SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")
QUERY_LOGGER = logging.getLogger("atlas.rag")


class DuplicateDocumentError(ValueError):
    pass


class UnknownConnectorRootError(ValueError):
    pass


class KnowledgeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder = create_embedder(
            settings.embedding_provider,
            settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            dimensions=settings.embedding_dimensions,
        )
        self.generator = create_generator(
            settings.generation_provider,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            require_citations=settings.llm_require_citations,
        )
        self.store = KnowledgeStore(
            settings.sqlite_path,
            settings.qdrant_path,
            self.embedder,
            qdrant_mode=settings.qdrant_mode,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            qdrant_timeout_seconds=settings.qdrant_timeout_seconds,
        )
        self._reranker: Reranker | None = None
        self._document_lock = threading.RLock()
        self.parsers = ParserRegistry(
            pdf_min_characters_per_page=settings.pdf_min_characters_per_page,
        )
        self.synchronizer = ConnectorSynchronizer(
            store=self.store,
            registry=self.parsers,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            chunking_profile=settings.chunking_profile,
            deletion_policy=settings.connector_deletion_policy,
            max_items=settings.connector_max_items,
            lock=self._document_lock,
        )
        self.job_store = IngestionJobStore(
            settings.ingestion_jobs_path,
            settings.ingestion_job_inputs_dir,
        )
        self.job_runner = IngestionJobRunner(
            self.job_store,
            self._process_ingestion_job,
            settings.ingestion_worker_poll_seconds,
        )

    def close(self) -> None:
        if self.job_runner.stop():
            self.store.close()
            close_embedder = getattr(self.embedder, "close", None)
            if close_embedder is not None:
                close_embedder()

    def start_background_workers(self) -> None:
        if self.settings.ingestion_worker_enabled:
            self.job_runner.start()

    def seed_sample_documents(self) -> None:
        manifest_path = self.settings.sample_documents_dir / "manifest.json"
        if not manifest_path.exists() or self.store.count_documents():
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest:
            path = self.settings.sample_documents_dir / entry["file"]
            self.ingest_path(
                path,
                filename=entry["file"],
                title=entry["title"],
                collection=entry["collection"],
                mime_type=mimetypes.guess_type(path.name)[0] or "text/plain",
                source_uri=f"sample://{entry['file']}",
            )

    def list_documents(
        self,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[DocumentRecord]:
        with self._document_lock:
            return self.store.list_documents(access)

    def count_documents(
        self,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> int:
        with self._document_lock:
            return self.store.count_documents(access)

    def readiness_checks(self) -> dict[str, str]:
        checks: dict[str, str] = {}
        for name, check in {
            "metadata": self.store.healthcheck,
            "ingestion_jobs": self.job_store.healthcheck,
        }.items():
            try:
                checks[name] = "ok" if check() else "unavailable"
            except Exception:
                checks[name] = "unavailable"
        return checks

    def list_document_versions(
        self,
        document_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[DocumentRecord]:
        with self._document_lock:
            document = self.store.get_document(document_id, access)
            if document is None:
                raise KeyError(document_id)
            return self.store.list_document_versions(document.source_id, access)

    def ingest_path(
        self,
        path: Path,
        *,
        filename: str,
        title: str,
        collection: str,
        mime_type: str,
        source_uri: str | None = None,
        progress: Callable[[int, str], None] | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
    ) -> DocumentRecord:
        if progress:
            progress(10, "reading")
        content = path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        if progress:
            progress(25, "checking_duplicate")
        with self._document_lock:
            duplicate = self.store.find_by_hash(sha256, access)
        if duplicate:
            raise DuplicateDocumentError(f"{duplicate.filename} is already indexed.")
        if progress:
            progress(40, "extracting")
        with TRACER.start_as_current_span("atlas.ingestion.extract") as span:
            span.set_attribute("atlas.document.mime_type", mime_type)
            span.set_attribute("atlas.document.size_bytes", len(content))
            parsed = self.parsers.parse(
                ParseRequest(
                    content=content,
                    filename=filename,
                    media_type=mime_type,
                    source_uri=source_uri or "",
                )
            )
            pages = parsed.pages
            span.set_attribute("atlas.parser.name", parsed.parser)
            span.set_attribute("atlas.parser.format", parsed.document_format)
            span.set_attribute("atlas.parser.degraded", parsed.degraded)
            span.set_attribute("atlas.document.page_count", len(pages))
        if progress:
            progress(60, "chunking")
        with TRACER.start_as_current_span("atlas.ingestion.chunk") as span:
            span.set_attribute(
                "atlas.chunking.profile",
                self.settings.chunking_profile,
            )
            chunks = chunk_pages(
                pages,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
                profile=self.settings.chunking_profile,
            )
            span.set_attribute("atlas.chunk.count", len(chunks))
        if progress:
            progress(80, "indexing")
        with TRACER.start_as_current_span("atlas.ingestion.index") as span:
            span.set_attribute("atlas.tenant_hash", tenant_hash(access.tenant_id))
            span.set_attribute("atlas.chunk.count", len(chunks))
            with self._document_lock:
                duplicate = self.store.find_by_hash(sha256, access)
                if duplicate:
                    raise DuplicateDocumentError(
                        f"{duplicate.filename} is already indexed."
                    )
                document = self.store.add_document(
                    filename=filename,
                    title=title,
                    collection=collection,
                    mime_type=mime_type,
                    size_bytes=len(content),
                    sha256=sha256,
                    chunks=chunks,
                    source_uri=source_uri or f"upload://{filename}",
                    access=access,
                    visibility=visibility,
                    allowed_principals=allowed_principals,
                    allowed_groups=allowed_groups,
                )
            span.set_attribute("atlas.document.id", document.id)
        return document

    async def ingest_upload(
        self,
        upload: UploadFile,
        collection: str,
        source_uri: str | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
    ) -> DocumentRecord:
        raw_name = Path(upload.filename or "document").name
        safe_name = SAFE_FILENAME.sub("_", raw_name)
        maximum = self.settings.max_upload_mb * 1024 * 1024
        with tempfile.TemporaryDirectory(prefix="atlas-upload-") as temp_dir:
            temp_path = Path(temp_dir) / safe_name
            size = 0
            with temp_path.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError(
                            f"Document exceeds the {self.settings.max_upload_mb} MB limit."
                        )
                    destination.write(chunk)
            title = Path(safe_name).stem.replace("_", " ").strip().title()
            mime_type = upload.content_type or mimetypes.guess_type(safe_name)[0] or "text/plain"
            return self.ingest_path(
                temp_path,
                filename=safe_name,
                title=title,
                collection=collection.strip() or "General",
                mime_type=mime_type,
                source_uri=source_uri.strip() if source_uri else None,
                access=access,
                visibility=visibility,
                allowed_principals=allowed_principals,
                allowed_groups=allowed_groups,
            )

    async def enqueue_ingestion_upload(
        self,
        upload: UploadFile,
        collection: str,
        source_uri: str | None = None,
        idempotency_key: str | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
    ) -> IngestionJobRecord:
        normalized_key = idempotency_key.strip() if idempotency_key else None
        if normalized_key and len(normalized_key) > 200:
            raise ValueError("Idempotency-Key must be 200 characters or fewer.")
        if normalized_key:
            existing = self.job_store.get_by_idempotency_key(normalized_key, access)
            if existing:
                return existing

        raw_name = Path(upload.filename or "document").name
        safe_name = SAFE_FILENAME.sub("_", raw_name)
        job_id = self.job_store.new_id()
        job_directory = self.settings.ingestion_job_inputs_dir / job_id
        job_directory.mkdir(parents=True, exist_ok=False)
        input_path = job_directory / safe_name
        maximum = self.settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with input_path.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError(
                            f"Document exceeds the {self.settings.max_upload_mb} MB limit."
                        )
                    destination.write(chunk)
            if size == 0:
                raise ValueError("The uploaded document is empty.")
            job, created = self.job_store.create(
                job_id=job_id,
                idempotency_key=normalized_key,
                filename=safe_name,
                collection=collection.strip() or "General",
                source_uri=(
                    source_uri.strip()
                    if source_uri and source_uri.strip()
                    else f"upload://{safe_name}"
                ),
                mime_type=(
                    upload.content_type
                    or mimetypes.guess_type(safe_name)[0]
                    or "text/plain"
                ),
                input_path=input_path,
                max_attempts=self.settings.ingestion_job_max_attempts,
                access=access,
                visibility=visibility,
                allowed_principals=allowed_principals,
                allowed_groups=allowed_groups,
            )
            if not created:
                shutil.rmtree(job_directory)
            else:
                self.job_runner.notify()
            return job
        except Exception:
            if job_directory.exists():
                shutil.rmtree(job_directory)
            raise

    def available_connectors(self) -> list[ConnectorDescriptor]:
        """Connector catalogue. Root names are exposed; absolute paths are not."""
        formats = list(self.parsers.supported_formats)
        return [
            ConnectorDescriptor(
                name="local-folder",
                description=(
                    "Synchronize documents from an operator-configured local root."
                ),
                configured_roots=sorted(self.settings.connector_local_roots),
                supported_formats=formats,
            ),
            ConnectorDescriptor(
                name="url",
                description=(
                    "Synchronize documents from validated http/https URLs."
                ),
                configured_roots=[],
                supported_formats=formats,
            ),
        ]

    def build_local_folder_connector(
        self,
        request: LocalFolderSyncRequest,
    ) -> LocalFolderConnector:
        root = self.settings.connector_local_roots.get(request.root)
        if root is None:
            raise UnknownConnectorRootError(
                f"'{request.root}' is not a configured connector root."
            )
        return LocalFolderConnector(
            root_name=request.root,
            root=root,
            subpath=request.subpath,
            recursive=request.recursive,
            registry=self.parsers,
            max_bytes=self.settings.connector_max_bytes,
            max_items=self.settings.connector_max_items,
            instance_id=request.instance_id,
        )

    def build_url_connector(self, request: UrlSyncRequest) -> UrlConnector:
        return UrlConnector(
            urls=request.urls,
            registry=self.parsers,
            max_bytes=self.settings.connector_max_bytes,
            max_items=self.settings.connector_max_items,
            timeout_seconds=self.settings.connector_url_timeout_seconds,
            max_redirects=self.settings.connector_url_max_redirects,
            allow_private_networks=(
                self.settings.connector_url_allow_private_networks
            ),
            instance_id=request.instance_id,
        )

    def run_connector_sync(
        self,
        connector: Connector,
        *,
        collection: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
        progress: Callable[[int, str], None] | None = None,
    ) -> SyncReport:
        try:
            return self.synchronizer.run(
                connector,
                collection=collection,
                access=access,
                visibility=visibility,
                allowed_principals=allowed_principals,
                allowed_groups=allowed_groups,
                progress=progress,
            )
        finally:
            connector.close()

    def enqueue_connector_sync(
        self,
        *,
        connector_name: str,
        request: LocalFolderSyncRequest | UrlSyncRequest,
        idempotency_key: str | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord:
        normalized_key = idempotency_key.strip() if idempotency_key else None
        if normalized_key and len(normalized_key) > 200:
            raise ValueError("Idempotency-Key must be 200 characters or fewer.")
        if normalized_key:
            existing = self.job_store.get_by_idempotency_key(normalized_key, access)
            if existing:
                return existing
        # Building the connector validates roots, paths and URLs before a job
        # is persisted, so an unsafe request never reaches the worker.
        connector = self._build_connector(connector_name, request)
        try:
            description = connector.describe()
            instance_id = connector.instance_id
        finally:
            connector.close()
        job, created = self.job_store.create(
            job_id=self.job_store.new_id(),
            idempotency_key=normalized_key,
            filename=f"{connector_name}-sync",
            collection=request.collection.strip() or "General",
            source_uri=f"connector://{instance_id}",
            mime_type="application/x-atlas-connector-sync",
            input_path=None,
            max_attempts=self.settings.ingestion_job_max_attempts,
            kind="connector-sync",
            connector_name=connector_name,
            connector_instance=instance_id,
            config={
                "connector": connector_name,
                "request": request.model_dump(),
                "describe": description,
            },
            access=access,
            visibility=request.visibility,
            allowed_principals=tuple(request.allowed_principals),
            allowed_groups=tuple(request.allowed_groups),
        )
        if created:
            self.job_runner.notify()
        return job

    def _build_connector(
        self,
        connector_name: str,
        request: LocalFolderSyncRequest | UrlSyncRequest,
    ) -> Connector:
        if connector_name == "local-folder" and isinstance(
            request, LocalFolderSyncRequest
        ):
            return self.build_local_folder_connector(request)
        if connector_name == "url" and isinstance(request, UrlSyncRequest):
            return self.build_url_connector(request)
        raise ValueError(f"Unknown connector '{connector_name}'.")

    def _process_connector_sync_job(
        self,
        job: IngestionJobRecord,
        progress: Callable[[int, str], None],
    ) -> None:
        config = self.job_store.config(job.id)
        connector_name = str(config.get("connector", job.connector_name))
        raw_request = config.get("request") or {}
        request: LocalFolderSyncRequest | UrlSyncRequest = (
            LocalFolderSyncRequest.model_validate(raw_request)
            if connector_name == "local-folder"
            else UrlSyncRequest.model_validate(raw_request)
        )
        access = AccessContext(
            tenant_id=job.tenant_id,
            principal_id=job.owner_principal_id,
        )
        try:
            connector = self._build_connector(connector_name, request)
        except (ConnectorSecurityError, ValueError, UnknownConnectorRootError) as exc:
            raise PermanentJobError(str(exc)) from exc
        report = self.run_connector_sync(
            connector,
            collection=job.collection,
            access=access,
            visibility=job.visibility,
            allowed_principals=job.allowed_principals,
            allowed_groups=job.allowed_groups,
            progress=progress,
        )
        self.job_store.set_result(job.id, report)

    def _process_ingestion_job(
        self,
        job: IngestionJobRecord,
        progress: Callable[[int, str], None],
    ) -> str | None:
        if job.kind == "connector-sync":
            try:
                self._process_connector_sync_job(job, progress)
            except ConnectorSecurityError as exc:
                raise PermanentJobError(str(exc)) from exc
            return None
        try:
            document = self.ingest_path(
                self.job_store.input_path(job.id),
                filename=job.filename,
                title=Path(job.filename).stem.replace("_", " ").strip().title(),
                collection=job.collection,
                mime_type=job.mime_type,
                source_uri=job.source_uri,
                progress=progress,
                access=AccessContext(
                    tenant_id=job.tenant_id,
                    principal_id=job.owner_principal_id,
                ),
                visibility=job.visibility,
                allowed_principals=job.allowed_principals,
                allowed_groups=job.allowed_groups,
            )
        except (DuplicateDocumentError, ValueError) as exc:
            raise PermanentJobError(str(exc)) from exc
        return document.id

    def list_ingestion_jobs(
        self,
        limit: int = 50,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[IngestionJobRecord]:
        return self.job_store.list(limit, access)

    def get_ingestion_job(
        self,
        job_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord:
        job = self.job_store.get_for_access(job_id, access)
        if job is None:
            raise KeyError(job_id)
        return job

    def retry_ingestion_job(
        self,
        job_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord:
        self.get_ingestion_job(job_id, access)
        job = self.job_store.retry(job_id)
        self.job_runner.notify()
        return job

    def replay_ingestion_job(
        self,
        job_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord:
        self.get_ingestion_job(job_id, access)
        job = self.job_store.replay(job_id)
        self.job_runner.notify()
        return job

    def cancel_ingestion_job(
        self,
        job_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord:
        self.get_ingestion_job(job_id, access)
        job = self.job_store.request_cancel(job_id)
        if job.status == "cancelled":
            self.job_store.remove_input(job_id)
        return job

    def process_next_ingestion_job(self) -> IngestionJobRecord | None:
        return self.job_runner.run_once()

    async def reindex_upload(
        self,
        document_id: str,
        upload: UploadFile,
        collection: str | None = None,
        source_uri: str | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> DocumentRecord:
        with self._document_lock:
            current = self.store.get_document(document_id, access, manage=True)
        if current is None:
            raise KeyError(document_id)
        if current.status != "indexed":
            raise ValueError("Only the current indexed version can be replaced.")

        raw_name = Path(upload.filename or current.filename).name
        safe_name = SAFE_FILENAME.sub("_", raw_name)
        maximum = self.settings.max_upload_mb * 1024 * 1024
        with tempfile.TemporaryDirectory(prefix="atlas-reindex-") as temp_dir:
            temp_path = Path(temp_dir) / safe_name
            size = 0
            with temp_path.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError(
                            f"Document exceeds the {self.settings.max_upload_mb} MB limit."
                        )
                    destination.write(chunk)

            content = temp_path.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            parsed = self.parsers.parse(
                ParseRequest(
                    content=content,
                    filename=safe_name,
                    media_type=(
                        upload.content_type
                        or mimetypes.guess_type(safe_name)[0]
                        or "text/plain"
                    ),
                    source_uri=current.source_uri,
                )
            )
            chunks = chunk_pages(
                parsed.pages,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
                profile=self.settings.chunking_profile,
            )
            with self._document_lock:
                current = self.store.get_document(document_id, access, manage=True)
                if current is None:
                    raise KeyError(document_id)
                duplicate = self.store.find_by_hash(sha256, access)
                if duplicate:
                    raise DuplicateDocumentError(
                        f"{duplicate.filename} is already indexed as version "
                        f"{duplicate.version}."
                    )
                return self.store.replace_document(
                    current=current,
                    filename=safe_name,
                    title=Path(safe_name).stem.replace("_", " ").strip().title(),
                    collection=(
                        collection.strip()
                        if collection and collection.strip()
                        else current.collection
                    ),
                    mime_type=(
                        upload.content_type
                        or mimetypes.guess_type(safe_name)[0]
                        or "text/plain"
                    ),
                    size_bytes=len(content),
                    sha256=sha256,
                    chunks=chunks,
                    source_uri=(
                        source_uri.strip()
                        if source_uri and source_uri.strip()
                        else current.source_uri
                    ),
                )

    def query(
        self,
        question: str,
        collections: list[str],
        top_k: int | None,
        retrieval_profile: RetrievalProfile | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> QueryResponse:
        reject_direct_prompt_injection(question)
        with TRACER.start_as_current_span("atlas.rag.query") as query_span:
            started = time.perf_counter()
            profile = retrieval_profile or self.settings.retrieval_profile
            query_span.set_attribute("atlas.tenant_hash", tenant_hash(access.tenant_id))
            query_span.set_attribute("atlas.query.length", len(question))
            query_span.set_attribute("atlas.retrieval.profile", profile)
            query_span.set_attribute("atlas.collection_filter.count", len(collections))
            reranker = (
                self._get_reranker() if profile == "hybrid-reranked" else None
            )
            with TRACER.start_as_current_span("atlas.rag.retrieve") as span:
                outcome = self.store.search(
                    question,
                    collections,
                    limit=top_k or self.settings.top_k,
                    min_score=self.settings.min_score,
                    semantic_evidence_floor=self.settings.semantic_evidence_floor,
                    score_ratio=self.settings.score_ratio,
                    profile=profile,
                    candidate_limit=max(
                        self.settings.retrieval_candidate_k,
                        top_k or self.settings.top_k,
                    ),
                    deduplicate_contexts=(
                        self.settings.chunking_profile == "parent-child"
                    ),
                    reranker=reranker,
                    access=access,
                )
                span.set_attribute(
                    "atlas.retrieval.candidates",
                    outcome.trace.candidates_considered,
                )
                span.set_attribute(
                    "atlas.retrieval.source_count",
                    len(outcome.sources),
                )
                span.set_attribute(
                    "atlas.retrieval.duration_ms",
                    outcome.trace.retrieval_ms + outcome.trace.rerank_ms,
                )
            with TRACER.start_as_current_span("atlas.rag.generate") as span:
                generation_started = time.perf_counter()
                span.set_attribute("gen_ai.operation.name", "chat")
                span.set_attribute("gen_ai.provider.name", self.generator.name)
                span.set_attribute("atlas.context.source_count", len(outcome.sources))
                generated = self.generator.generate(question, outcome.sources)
                generation_ms = round((time.perf_counter() - generation_started) * 1000)
                generation = GenerationTrace(
                    provider=self.generator.name,
                    context_sources=generated.context_sources,
                    context_characters=generated.context_characters,
                    prompt_tokens=generated.prompt_tokens,
                    completion_tokens=generated.completion_tokens,
                    total_tokens=generated.total_tokens,
                    generation_ms=generation_ms,
                )
                span.set_attribute(
                    "atlas.context.characters",
                    generation.context_characters,
                )
                span.set_attribute("atlas.generation.duration_ms", generation_ms)
                # Only report usage the provider actually sent. A missing
                # attribute is honest; a zero would corrupt a cost budget.
                for attribute, value in (
                    ("gen_ai.usage.input_tokens", generation.prompt_tokens),
                    ("gen_ai.usage.output_tokens", generation.completion_tokens),
                    ("gen_ai.usage.total_tokens", generation.total_tokens),
                ):
                    if value is not None:
                        span.set_attribute(attribute, value)
            latency_ms = round((time.perf_counter() - started) * 1000)
            query_span.set_attribute("atlas.query.duration_ms", latency_ms)
            query_span.set_attribute("atlas.query.source_count", len(outcome.sources))
            if generation.total_tokens is not None:
                query_span.set_attribute(
                    "gen_ai.usage.total_tokens",
                    generation.total_tokens,
                )
            QUERY_LOGGER.info(
                "Query completed",
                extra={
                    "event": "rag.query.completed",
                    "retrieval_profile": profile,
                    "source_count": len(outcome.sources),
                    "duration_ms": latency_ms,
                    "generation_provider": self.generator.name,
                    "total_tokens": generation.total_tokens,
                },
            )
            return QueryResponse(
                answer=generated.text,
                sources=outcome.sources,
                retrieval=outcome.trace,
                generation=generation,
                generation_mode=self.generator.name,
                latency_ms=latency_ms,
            )

    def stream_query(
        self,
        question: str,
        collections: list[str],
        top_k: int | None,
        retrieval_profile: RetrievalProfile | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> Iterator[tuple[str, dict[str, object]]]:
        """Yield `(event, payload)` pairs for a server-sent-events response.

        Retrieval completes before any answer text is emitted, so the evidence
        is on screen while generation is still running. That is the part of the
        latency a RAG interface can genuinely hide.

        The trade-off is explicit: `generate` refuses an uncited answer before
        the caller ever sees it, whereas here the text is already on screen when
        the citation contract is checked. A failure therefore arrives as a
        `retracted` event, and a client that ignores it will display an answer
        Atlas has judged ungrounded.
        """
        reject_direct_prompt_injection(question)
        started = time.perf_counter()
        profile = retrieval_profile or self.settings.retrieval_profile
        # Spans are started and ended explicitly rather than with
        # `start_as_current_span`. A generator's `with` block spans its yields,
        # and the ASGI server resumes the iterator in a different context, so
        # the context token cannot be detached where it was attached. Parenting
        # is passed explicitly instead of relying on the current context.
        query_span = TRACER.start_span("atlas.rag.query.stream")
        query_context = trace.set_span_in_context(query_span)
        try:
            query_span.set_attribute("atlas.tenant_hash", tenant_hash(access.tenant_id))
            query_span.set_attribute("atlas.retrieval.profile", profile)
            reranker = self._get_reranker() if profile == "hybrid-reranked" else None
            retrieve_span = TRACER.start_span(
                "atlas.rag.retrieve", context=query_context
            )
            try:
                outcome = self.store.search(
                    question,
                    collections,
                    limit=top_k or self.settings.top_k,
                    min_score=self.settings.min_score,
                    semantic_evidence_floor=self.settings.semantic_evidence_floor,
                    score_ratio=self.settings.score_ratio,
                    profile=profile,
                    candidate_limit=max(
                        self.settings.retrieval_candidate_k,
                        top_k or self.settings.top_k,
                    ),
                    deduplicate_contexts=(
                        self.settings.chunking_profile == "parent-child"
                    ),
                    reranker=reranker,
                    access=access,
                )
                retrieve_span.set_attribute(
                    "atlas.retrieval.source_count", len(outcome.sources)
                )
            finally:
                retrieve_span.end()

            yield (
                "sources",
                {
                    "sources": [source.model_dump() for source in outcome.sources],
                    "retrieval": outcome.trace.model_dump(),
                    "streamed": self.generator.streams,
                },
            )

            generation_started = time.perf_counter()
            retracted: str | None = None
            final: GenerationResult | None = None
            generate_span = TRACER.start_span(
                "atlas.rag.generate", context=query_context
            )
            try:
                generate_span.set_attribute("gen_ai.operation.name", "chat")
                generate_span.set_attribute(
                    "gen_ai.provider.name", self.generator.name
                )
                for chunk in self.generator.stream(question, outcome.sources):
                    if chunk.text:
                        yield ("delta", {"text": chunk.text})
                    if chunk.result is not None:
                        final = chunk.result
                        retracted = chunk.retracted_reason
                if final is None:
                    raise RuntimeError("The generator produced no final result.")
                generation_ms = round((time.perf_counter() - generation_started) * 1000)
                for attribute, value in (
                    ("gen_ai.usage.input_tokens", final.prompt_tokens),
                    ("gen_ai.usage.output_tokens", final.completion_tokens),
                    ("gen_ai.usage.total_tokens", final.total_tokens),
                ):
                    if value is not None:
                        generate_span.set_attribute(attribute, value)
                if retracted:
                    generate_span.set_attribute("atlas.generation.retracted", True)
            finally:
                generate_span.end()

            latency_ms = round((time.perf_counter() - started) * 1000)
            if retracted:
                yield ("retracted", {"detail": retracted})
            yield (
                "trace",
                {
                    "generation": GenerationTrace(
                        provider=self.generator.name,
                        context_sources=final.context_sources,
                        context_characters=final.context_characters,
                        prompt_tokens=final.prompt_tokens,
                        completion_tokens=final.completion_tokens,
                        total_tokens=final.total_tokens,
                        generation_ms=generation_ms,
                    ).model_dump(),
                    "generation_mode": self.generator.name,
                    "latency_ms": latency_ms,
                    "retracted": retracted is not None,
                },
            )
            QUERY_LOGGER.info(
                "Streamed query completed",
                extra={
                    "event": "rag.query.stream.completed",
                    "retrieval_profile": profile,
                    "source_count": len(outcome.sources),
                    "duration_ms": latency_ms,
                    "generation_provider": self.generator.name,
                    "total_tokens": final.total_tokens,
                },
            )
            query_span.set_attribute("atlas.query.duration_ms", latency_ms)
            query_span.set_attribute("atlas.query.source_count", len(outcome.sources))
            if final.total_tokens is not None:
                query_span.set_attribute(
                    "gen_ai.usage.total_tokens", final.total_tokens
                )
        finally:
            query_span.end()

    def _get_reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = create_reranker(
                self.settings.reranker_provider,
                self.settings.reranker_model,
            )
        return self._reranker

    def delete_document(
        self,
        document_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> bool:
        with self._document_lock:
            return self.store.delete_document(document_id, access)
