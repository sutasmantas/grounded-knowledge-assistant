from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.generation import ExtractiveGenerator, OpenAICompatibleGenerator
from app.main import create_app
from app.schemas import SourceResult


def source(rank: int = 1) -> SourceResult:
    return SourceResult(
        rank=rank,
        document_id="document-1",
        source_id="source-1",
        source_uri="handbook://refunds",
        document_version=1,
        document_sha256="checksum",
        chunk_id="chunk-1",
        title="Refund Policy",
        filename="refunds.md",
        collection="Policies",
        page=1,
        passage="The approved refund window is 30 days.",
        score=0.9,
    )


def fake_client(body: dict) -> type:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return body

    class FakeClient:
        def __init__(self, timeout: int) -> None:
            del timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, _url: str, **_kwargs):
            return FakeResponse()

    return FakeClient


def test_extractive_generation_reports_context_size_and_no_token_counts() -> None:
    result = ExtractiveGenerator().generate("What is the refund window?", [source()])

    assert "30 days" in result.text
    assert result.context_sources == 1
    assert result.context_characters == len(source().passage)
    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.total_tokens is None


def test_empty_retrieval_reports_no_generation_cost() -> None:
    result = ExtractiveGenerator().generate("What is the refund window?", [])

    assert result.context_sources == 0
    assert result.context_characters == 0
    assert result.total_tokens is None


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"prompt_tokens": None},
        {"prompt_tokens": "412"},
        {"prompt_tokens": True},
        {"prompt_tokens": -3},
    ],
)
def test_missing_or_invalid_provider_usage_is_never_estimated(
    monkeypatch: pytest.MonkeyPatch,
    usage: dict,
) -> None:
    body = {
        "choices": [{"message": {"content": "The window is 30 days [1]."}}],
        "usage": usage,
    }
    monkeypatch.setattr("app.generation.httpx.Client", fake_client(body))
    result = OpenAICompatibleGenerator("https://model.example/v1", "", "m").generate(
        "What is the refund window?",
        [source()],
    )

    assert result.text == "The window is 30 days [1]."
    assert result.prompt_tokens is None


def test_evaluation_can_capture_uncited_output_without_weakening_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "choices": [{"message": {"content": "The window is 30 days."}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26},
    }
    monkeypatch.setattr("app.generation.httpx.Client", fake_client(body))

    with pytest.raises(RuntimeError, match="without source citations"):
        OpenAICompatibleGenerator(
            "https://model.example/v1", "", "m"
        ).generate("What is the refund window?", [source()])

    captured = OpenAICompatibleGenerator(
        "https://model.example/v1",
        "",
        "m",
        require_citations=False,
    ).generate("What is the refund window?", [source()])

    assert captured.text == "The window is 30 days."
    assert captured.total_tokens == 26


def test_query_response_exposes_the_generation_trace(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/documents",
            data={"collection": "Policies"},
            files={
                "file": (
                    "refunds.md",
                    b"# Refund Policy\n\nThe approved refund window is 30 days.",
                    "text/markdown",
                )
            },
        )
        payload = client.post(
            "/api/query",
            json={"question": "What is the approved refund window?"},
        ).json()

    generation = payload["generation"]
    assert generation["provider"] == "extractive"
    assert generation["context_sources"] >= 1
    assert generation["context_characters"] > 0
    assert generation["generation_ms"] >= 0
    assert generation["prompt_tokens"] is None
    assert generation["total_tokens"] is None


def test_query_trace_carries_provider_token_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="openai-compatible",
        llm_base_url="https://model.example/v1",
        llm_model="test-model",
        ingestion_worker_enabled=False,
    )
    body = {
        "choices": [{"message": {"content": "The refund window is 30 days [1]."}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 20, "total_tokens": 320},
    }
    monkeypatch.setattr("app.generation.httpx.Client", fake_client(body))
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/documents",
            data={"collection": "Policies"},
            files={
                "file": (
                    "refunds.md",
                    b"# Refund Policy\n\nThe approved refund window is 30 days.",
                    "text/markdown",
                )
            },
        )
        payload = client.post(
            "/api/query",
            json={"question": "What is the approved refund window?"},
        ).json()

    generation = payload["generation"]
    assert generation["provider"] == "openai-compatible"
    assert generation["prompt_tokens"] == 300
    assert generation["completion_tokens"] == 20
    assert generation["total_tokens"] == 320
    assert payload["generation_mode"] == "openai-compatible"


def collect_spans(monkeypatch: pytest.MonkeyPatch):
    """Attach an in-memory exporter so span attributes can be asserted."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("atlas-test")
    for module in ("app.service", "app.sync", "app.jobs"):
        monkeypatch.setattr(f"{module}.TRACER", tracer)
    return exporter


def test_generation_span_carries_provider_token_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = collect_spans(monkeypatch)
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="openai-compatible",
        llm_base_url="https://model.example/v1",
        llm_model="test-model",
        ingestion_worker_enabled=False,
    )
    body = {
        "choices": [{"message": {"content": "The refund window is 30 days [1]."}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 20, "total_tokens": 320},
    }
    monkeypatch.setattr("app.generation.httpx.Client", fake_client(body))
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/documents",
            data={"collection": "Policies"},
            files={
                "file": (
                    "refunds.md",
                    b"# Refund Policy\n\nThe approved refund window is 30 days.",
                    "text/markdown",
                )
            },
        )
        client.post(
            "/api/query",
            json={"question": "What is the approved refund window?"},
        )

    spans = {span.name: dict(span.attributes) for span in exporter.get_finished_spans()}
    generate = spans["atlas.rag.generate"]
    assert generate["gen_ai.provider.name"] == "openai-compatible"
    assert generate["gen_ai.usage.input_tokens"] == 300
    assert generate["gen_ai.usage.output_tokens"] == 20
    assert generate["gen_ai.usage.total_tokens"] == 320
    assert generate["atlas.context.characters"] > 0
    assert "atlas.generation.duration_ms" in generate
    assert spans["atlas.rag.query"]["gen_ai.usage.total_tokens"] == 320
    # No question, answer or passage text may reach a span.
    assert not any(
        "refund window is 30 days" in str(value)
        for attributes in spans.values()
        for value in attributes.values()
    )


def test_no_key_generation_span_omits_token_attributes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = collect_spans(monkeypatch)
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/documents",
            data={"collection": "Policies"},
            files={
                "file": (
                    "refunds.md",
                    b"# Refund Policy\n\nThe approved refund window is 30 days.",
                    "text/markdown",
                )
            },
        )
        client.post(
            "/api/query",
            json={"question": "What is the approved refund window?"},
        )

    spans = {span.name: dict(span.attributes) for span in exporter.get_finished_spans()}
    generate = spans["atlas.rag.generate"]
    assert generate["gen_ai.provider.name"] == "extractive"
    # Absent, not zero: a fabricated zero would corrupt a cost budget.
    assert "gen_ai.usage.input_tokens" not in generate
    assert "gen_ai.usage.output_tokens" not in generate
    assert "gen_ai.usage.total_tokens" not in generate
    assert "gen_ai.usage.total_tokens" not in spans["atlas.rag.query"]
    assert generate["atlas.context.characters"] > 0


def test_ingestion_and_connector_spans_are_emitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = collect_spans(monkeypatch)
    root = tmp_path / "handbook"
    root.mkdir()
    (root / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Mercury.",
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
        connector_local_roots={"handbook": root},
    )
    from app.schemas import LocalFolderSyncRequest
    from app.service import KnowledgeService

    service = KnowledgeService(settings)
    try:
        service.run_connector_sync(
            service.build_local_folder_connector(
                LocalFolderSyncRequest(root="handbook", collection="Operations")
            ),
            collection="Operations",
        )
    finally:
        service.close()

    spans = {span.name: dict(span.attributes) for span in exporter.get_finished_spans()}
    assert spans["atlas.connector.sync"]["atlas.connector.name"] == "local-folder"
    assert spans["atlas.connector.sync"]["atlas.connector.created"] == 1
    assert spans["atlas.ingestion.extract"]["atlas.parser.name"] == "text"
    assert spans["atlas.ingestion.chunk"]["atlas.chunk.count"] >= 1
    assert "atlas.document.id" in spans["atlas.ingestion.index"]


def test_query_completion_log_records_provider_and_token_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="openai-compatible",
        llm_base_url="https://model.example/v1",
        llm_model="test-model",
        ingestion_worker_enabled=False,
    )
    body = {
        "choices": [{"message": {"content": "The refund window is 30 days [1]."}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 20, "total_tokens": 320},
    }
    monkeypatch.setattr("app.generation.httpx.Client", fake_client(body))
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/documents",
            data={"collection": "Policies"},
            files={
                "file": (
                    "refunds.md",
                    b"# Refund Policy\n\nThe approved refund window is 30 days.",
                    "text/markdown",
                )
            },
        )
        # The `atlas` logger does not propagate, so attach the capture handler
        # to it directly instead of relying on the root logger.
        atlas_logger = logging.getLogger("atlas")
        atlas_logger.addHandler(caplog.handler)
        try:
            client.post(
                "/api/query",
                json={"question": "What is the approved refund window?"},
            )
        finally:
            atlas_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "rag.query.completed"
    ]
    assert records
    assert records[0].generation_provider == "openai-compatible"
    assert records[0].total_tokens == 320
    assert not hasattr(records[0], "question")
