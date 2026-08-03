from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.access import AccessContext
from app.config import Settings

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
request_id_context: ContextVar[str] = ContextVar("request_id", default="")
tenant_context: ContextVar[str] = ContextVar("tenant_id", default="")
principal_context: ContextVar[str] = ContextVar("principal_id", default="")
TRACER = trace.get_tracer("atlas-knowledge")


class JsonLogFormatter(logging.Formatter):
    _fields = (
        "event",
        "http_method",
        "http_path",
        "http_status",
        "duration_ms",
        "error_type",
        "resource_type",
        "resource_id",
        "retrieval_profile",
        "source_count",
        "generation_provider",
        "total_tokens",
        "connector",
        "connector_action",
        "items_discovered",
        "items_failed",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        tenant_id = tenant_context.get()
        if tenant_id:
            payload["tenant_hash"] = tenant_hash(tenant_id)
        principal_id = principal_context.get()
        if principal_id:
            payload["principal_hash"] = principal_hash(principal_id)
        for field in self._fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(structured: bool) -> logging.Logger:
    logger = logging.getLogger("atlas")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = (
        JsonLogFormatter()
        if structured
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    atlas_handlers = [
        handler
        for handler in logger.handlers
        if getattr(handler, "_atlas_handler", False)
    ]
    if not atlas_handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler._atlas_handler = True  # type: ignore[attr-defined]
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        for handler in atlas_handlers:
            handler.setFormatter(formatter)
    return logger


def configure_tracing(application: FastAPI, settings: Settings) -> bool:
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        return False
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.version": application.version,
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        application,
        tracer_provider=provider,
        excluded_urls="^/$|^/app.js$|^/styles.css$",
    )
    return True


def normalize_request_id(value: str | None) -> str:
    if value and REQUEST_ID_PATTERN.fullmatch(value.strip()):
        return value.strip()
    return str(uuid.uuid4())


def bind_request_context(
    request_id: str,
    access: AccessContext,
) -> tuple[Token[str], Token[str], Token[str]]:
    return (
        request_id_context.set(request_id),
        tenant_context.set(access.tenant_id),
        principal_context.set(access.principal_id),
    )


def reset_request_context(tokens: tuple[Token[str], Token[str], Token[str]]) -> None:
    request_id_context.reset(tokens[0])
    tenant_context.reset(tokens[1])
    principal_context.reset(tokens[2])


def tenant_hash(tenant_id: str) -> str:
    return hashlib.sha256(tenant_id.encode()).hexdigest()[:12]


def principal_hash(principal_id: str) -> str:
    return hashlib.sha256(principal_id.encode()).hexdigest()[:12]
