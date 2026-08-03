from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from qdrant_client.http.exceptions import ResponseHandlingException
from starlette.concurrency import run_in_threadpool

from app.access import (
    AccessContext,
    normalize_visibility,
    parse_acl_values,
)
from app.auth import AuthenticationError, create_authenticator
from app.config import PROJECT_ROOT, Settings
from app.connectors.base import ConnectorError, ConnectorSecurityError
from app.jobs import JobStateError
from app.observability import (
    bind_request_context,
    configure_logging,
    configure_tracing,
    normalize_request_id,
    reset_request_context,
    tenant_hash,
)
from app.parsers import ParserUnavailableError
from app.schemas import (
    ConnectorDescriptor,
    DocumentRecord,
    HealthResponse,
    IngestionJobRecord,
    LocalFolderSyncRequest,
    QueryComparisonRequest,
    QueryComparisonResponse,
    QueryRequest,
    QueryResponse,
    ReadinessResponse,
    UrlSyncRequest,
)
from app.security import UnsafePromptError
from app.service import (
    DuplicateDocumentError,
    KnowledgeService,
    UnknownConnectorRootError,
)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.structured_logs)
    request_logger = logging.getLogger("atlas.http")
    authenticator = create_authenticator(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        service = KnowledgeService(resolved_settings)
        service.seed_sample_documents()
        service.start_background_workers()
        application.state.knowledge = service
        yield
        service.close()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="2.0.0",
        lifespan=lifespan,
    )

    @application.exception_handler(ResponseHandlingException)
    async def qdrant_unavailable(
        _request: Request,
        exc: ResponseHandlingException,
    ) -> JSONResponse:
        request_logger.error(
            "Vector storage unavailable",
            extra={"event": "qdrant.unavailable", "error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Vector storage is temporarily unavailable."},
        )

    def apply_response_headers(
        request: Request,
        response: Response,
        request_id: str,
    ) -> None:
        headers = response.headers
        headers["X-Request-ID"] = request_id
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            headers["Cache-Control"] = "no-store"
        if request.url.path in {
            "/",
            "/legacy-ui2-comparison",
            "/app.js",
            "/styles.css",
        } or (
            request.url.path.startswith("/assets/")
        ):
            headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                "form-action 'self'; img-src 'self' data:; "
                "script-src 'self'; style-src 'self'; connect-src 'self'"
            )

    @application.middleware("http")
    async def request_boundary(request: Request, call_next):
        started = time.perf_counter()
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        public_without_identity = (
            not request.url.path.startswith("/api/")
            or request.url.path in {"/api/health/live", "/api/health/ready"}
        )
        try:
            access = (
                AccessContext()
                if resolved_settings.auth_mode == "oidc" and public_without_identity
                else await run_in_threadpool(authenticator.authenticate, request.headers)
            )
        except AuthenticationError as exc:
            request_logger.warning(
                "Authentication failed",
                extra={"event": "auth.failed", "error_type": type(exc).__name__},
            )
            response = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid bearer token."},
                headers={"WWW-Authenticate": "Bearer"},
            )
            apply_response_headers(request, response, request_id)
            return response
        except ValueError as exc:
            response = JSONResponse(status_code=422, content={"detail": str(exc)})
            apply_response_headers(request, response, request_id)
            return response

        request.state.access_context = access
        tokens = bind_request_context(request_id, access)
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
                if declared_length < 0:
                    raise ValueError
                too_large = declared_length > (
                    resolved_settings.request_body_limit_mb * 1024 * 1024
                )
            except ValueError:
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Content-Length must be a non-negative integer."},
                )
                apply_response_headers(request, response, request_id)
                reset_request_context(tokens)
                return response
            if too_large:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            "Request body exceeds the "
                            f"{resolved_settings.request_body_limit_mb} MB limit."
                        )
                    },
                )
                apply_response_headers(request, response, request_id)
                reset_request_context(tokens)
                return response

        span = trace.get_current_span()
        span.set_attribute("atlas.request_id", request_id)
        span.set_attribute("atlas.tenant_hash", tenant_hash(access.tenant_id))
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            apply_response_headers(request, response, request_id)
            return response
        except Exception as exc:
            request_logger.exception(
                "Request failed",
                extra={
                    "event": "http.request.failed",
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": 500,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000
                    ),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000)
            if status_code != 500:
                request_logger.info(
                    "Request completed",
                    extra={
                        "event": "http.request.completed",
                        "http_method": request.method,
                        "http_path": request.url.path,
                        "http_status": status_code,
                        "duration_ms": duration_ms,
                    },
                )
            reset_request_context(tokens)

    def service(request: Request) -> KnowledgeService:
        return request.app.state.knowledge

    def request_access(request: Request) -> AccessContext:
        return request.state.access_context

    @application.get("/api/health", response_model=HealthResponse)
    def health(
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> HealthResponse:
        knowledge = service(request)
        return HealthResponse(
            status="ok",
            documents=knowledge.count_documents(access),
            embedding_provider=knowledge.embedder.name,
            generation_provider=knowledge.generator.name,
            chunking_profile=knowledge.settings.chunking_profile,
        )

    @application.get("/api/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/api/health/ready", response_model=ReadinessResponse)
    def readiness(request: Request, response: Response) -> ReadinessResponse:
        checks = service(request).readiness_checks()
        ready = all(value == "ok" for value in checks.values())
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="ready" if ready else "not_ready",
            checks=checks,
        )

    @application.get("/api/documents", response_model=list[DocumentRecord])
    def documents(
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> list[DocumentRecord]:
        return service(request).list_documents(access)

    @application.get(
        "/api/documents/{document_id}/versions",
        response_model=list[DocumentRecord],
    )
    def document_versions(
        document_id: str,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> list[DocumentRecord]:
        try:
            return service(request).list_document_versions(document_id, access)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Document not found.") from exc

    @application.post(
        "/api/documents",
        response_model=DocumentRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        collection: str = Form(default="General"),
        source_uri: str | None = Form(default=None),
        visibility: str = Form(default="tenant"),
        allowed_principals: str | None = Form(default=None),
        allowed_groups: str | None = Form(default=None),
        access: AccessContext = Depends(request_access),
    ) -> DocumentRecord:
        try:
            return await service(request).ingest_upload(
                file,
                collection,
                source_uri,
                access=access,
                visibility=normalize_visibility(visibility),
                allowed_principals=parse_acl_values(
                    allowed_principals,
                    "allowed_principals",
                ),
                allowed_groups=parse_acl_values(allowed_groups, "allowed_groups"),
            )
        except DuplicateDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ParserUnavailableError as exc:
            # An installation fault, not a bad request: say so instead of
            # telling the caller their document is unsupported.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post(
        "/api/ingestion-jobs",
        response_model=IngestionJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_ingestion_job(
        request: Request,
        file: UploadFile = File(...),
        collection: str = Form(default="General"),
        source_uri: str | None = Form(default=None),
        visibility: str = Form(default="tenant"),
        allowed_principals: str | None = Form(default=None),
        allowed_groups: str | None = Form(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        try:
            return await service(request).enqueue_ingestion_upload(
                file,
                collection,
                source_uri,
                idempotency_key,
                access=access,
                visibility=normalize_visibility(visibility),
                allowed_principals=parse_acl_values(
                    allowed_principals,
                    "allowed_principals",
                ),
                allowed_groups=parse_acl_values(allowed_groups, "allowed_groups"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get(
        "/api/ingestion-jobs",
        response_model=list[IngestionJobRecord],
    )
    def ingestion_jobs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        access: AccessContext = Depends(request_access),
    ) -> list[IngestionJobRecord]:
        return service(request).list_ingestion_jobs(limit, access)

    @application.get(
        "/api/ingestion-jobs/{job_id}",
        response_model=IngestionJobRecord,
    )
    def ingestion_job(
        job_id: str,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        try:
            return service(request).get_ingestion_job(job_id, access)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Ingestion job not found.") from exc

    @application.post(
        "/api/ingestion-jobs/{job_id}/retry",
        response_model=IngestionJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_ingestion_job(
        job_id: str,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        try:
            return service(request).retry_ingestion_job(job_id, access)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Ingestion job not found.") from exc
        except JobStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post(
        "/api/ingestion-jobs/{job_id}/replay",
        response_model=IngestionJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def replay_ingestion_job(
        job_id: str,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        try:
            return service(request).replay_ingestion_job(job_id, access)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Ingestion job not found.") from exc
        except JobStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post(
        "/api/ingestion-jobs/{job_id}/cancel",
        response_model=IngestionJobRecord,
    )
    def cancel_ingestion_job(
        job_id: str,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        try:
            return service(request).cancel_ingestion_job(job_id, access)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Ingestion job not found.") from exc
        except JobStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get("/api/connectors", response_model=list[ConnectorDescriptor])
    def connectors(request: Request) -> list[ConnectorDescriptor]:
        return service(request).available_connectors()

    @application.post(
        "/api/connectors/local-folder/sync",
        response_model=IngestionJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def sync_local_folder(
        payload: LocalFolderSyncRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        return _enqueue_sync(request, "local-folder", payload, idempotency_key, access)

    @application.post(
        "/api/connectors/url/sync",
        response_model=IngestionJobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def sync_urls(
        payload: UrlSyncRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        access: AccessContext = Depends(request_access),
    ) -> IngestionJobRecord:
        return _enqueue_sync(request, "url", payload, idempotency_key, access)

    def _enqueue_sync(
        request: Request,
        connector_name: str,
        payload: LocalFolderSyncRequest | UrlSyncRequest,
        idempotency_key: str | None,
        access: AccessContext,
    ) -> IngestionJobRecord:
        try:
            return service(request).enqueue_connector_sync(
                connector_name=connector_name,
                request=payload,
                idempotency_key=idempotency_key,
                access=access,
            )
        except UnknownConnectorRootError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConnectorSecurityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.put(
        "/api/documents/{document_id}",
        response_model=DocumentRecord,
    )
    async def reindex_document(
        document_id: str,
        request: Request,
        file: UploadFile = File(...),
        collection: str | None = Form(default=None),
        source_uri: str | None = Form(default=None),
        access: AccessContext = Depends(request_access),
    ) -> DocumentRecord:
        try:
            return await service(request).reindex_upload(
                document_id,
                file,
                collection,
                source_uri,
                access=access,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Document not found.") from exc
        except DuplicateDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ParserUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_document(
        document_id: str,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> None:
        if not service(request).delete_document(document_id, access):
            raise HTTPException(status_code=404, detail="Document not found.")

    @application.post("/api/query", response_model=QueryResponse)
    def query(
        payload: QueryRequest,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> QueryResponse:
        try:
            return service(request).query(
                payload.question.strip(),
                payload.collections,
                payload.top_k,
                payload.retrieval_profile,
                access=access,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Model provider failed: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except UnsafePromptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post("/api/query/stream")
    def query_stream(
        payload: QueryRequest,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> StreamingResponse:
        """Server-sent events: `sources`, then `delta`, then `trace`.

        Opt-in. `POST /api/query` remains the default because it refuses an
        uncited answer before the caller sees anything, while this route can
        only retract one after the fact — a `retracted` event that a client is
        obliged to honour.
        """
        knowledge = service(request)

        def events() -> Iterator[str]:
            try:
                for name, data in knowledge.stream_query(
                    payload.question.strip(),
                    payload.collections,
                    payload.top_k,
                    payload.retrieval_profile,
                    access=access,
                ):
                    yield f"event: {name}\ndata: {json.dumps(data)}\n\n"
            except UnsafePromptError as exc:
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            except (httpx.HTTPError, RuntimeError) as exc:
                yield (
                    "event: error\ndata: "
                    f"{json.dumps({'detail': f'Model provider failed: {exc}'})}\n\n"
                )
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                # Proxies that buffer defeat the point of streaming.
                "X-Accel-Buffering": "no",
            },
        )

    @application.post(
        "/api/evaluations/compare",
        response_model=QueryComparisonResponse,
    )
    def compare_query_profiles(
        payload: QueryComparisonRequest,
        request: Request,
        access: AccessContext = Depends(request_access),
    ) -> QueryComparisonResponse:
        question = payload.question.strip()
        try:
            results = [
                service(request).query(
                    question,
                    payload.collections,
                    payload.top_k,
                    profile,
                    access=access,
                )
                for profile in payload.profiles
            ]
            return QueryComparisonResponse(
                question=question,
                collections=payload.collections,
                results=results,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Model provider failed: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except UnsafePromptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        candidate = FRONTEND_DIST / "index.html"
        if candidate.is_file():
            return FileResponse(candidate)
        # Backend-only test and editable installs do not build Node assets. Keep
        # the previous shell as a deliberate development fallback; production
        # images always build and copy the UI2 distribution.
        return FileResponse(PROJECT_ROOT / "index.html")

    @application.get("/legacy-ui2-comparison", include_in_schema=False)
    def legacy_frontend_comparison() -> FileResponse:
        """Keep the released shell measurable after UI2 becomes the root UI."""
        return FileResponse(PROJECT_ROOT / "index.html")

    application.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
        name="frontend-assets",
    )

    @application.get("/app.js", include_in_schema=False)
    def frontend_script() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "app.js", media_type="text/javascript")

    @application.get("/styles.css", include_in_schema=False)
    def frontend_styles() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "styles.css", media_type="text/css")

    configure_tracing(application, resolved_settings)
    return application


app = create_app()
