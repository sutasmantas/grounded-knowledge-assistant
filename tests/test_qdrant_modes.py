from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from qdrant_client.http.exceptions import ResponseHandlingException

from app.config import Settings
from app.main import create_app
from app.storage import create_qdrant_client


def test_server_mode_requires_an_explicit_url(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ATLAS_QDRANT_URL is required"):
        Settings(data_dir=tmp_path, qdrant_mode="server")


def test_embedded_mode_rejects_an_ignored_server_url(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ATLAS_QDRANT_MODE=server"):
        Settings(
            data_dir=tmp_path,
            qdrant_mode="embedded",
            qdrant_url="http://qdrant:6333",
        )


def test_official_client_receives_server_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("app.storage.QdrantClient", FakeClient)

    create_qdrant_client(
        mode="server",
        path=tmp_path / "must-not-be-created" / "qdrant",
        url="https://qdrant.example",
        api_key="secret",
        timeout_seconds=17,
    )

    assert captured == {
        "url": "https://qdrant.example",
        "api_key": "secret",
        "timeout": 17,
    }
    assert not (tmp_path / "must-not-be-created").exists()


def test_official_client_keeps_embedded_path_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("app.storage.QdrantClient", FakeClient)
    path = tmp_path / "embedded" / "qdrant"

    create_qdrant_client(
        mode="embedded",
        path=path,
        url="",
        api_key="",
        timeout_seconds=5,
    )

    assert captured == {"path": str(path)}
    assert path.parent.is_dir()


def test_vector_connection_failure_returns_service_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        service = client.app.state.knowledge

        def unavailable(*_args: object, **_kwargs: object) -> None:
            raise ResponseHandlingException(ConnectionError("connection refused"))

        monkeypatch.setattr(service.store, "search", unavailable)
        response = client.post(
            "/api/query",
            json={"question": "What is the refund window?"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Vector storage is temporarily unavailable."
    }
