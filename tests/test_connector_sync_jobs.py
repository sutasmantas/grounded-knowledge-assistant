from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TENANT_A = {"X-Atlas-Tenant": "tenant-a", "X-Atlas-Principal": "alice"}
TENANT_B = {"X-Atlas-Tenant": "tenant-b", "X-Atlas-Principal": "bob"}


@pytest.fixture
def handbook(tmp_path: Path) -> Path:
    root = tmp_path / "handbook"
    root.mkdir()
    (root / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Mercury.",
        encoding="utf-8",
    )
    (root / "retention.md").write_text(
        "# Retention Policy\n\nThe retention owner is the Records desk.",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def client(tmp_path: Path, handbook: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
        connector_local_roots={"handbook": handbook},
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_connector_catalogue_lists_roots_without_absolute_paths(
    client: TestClient,
    handbook: Path,
) -> None:
    response = client.get("/api/connectors", headers=TENANT_A)

    assert response.status_code == 200
    catalogue = response.json()
    assert [entry["name"] for entry in catalogue] == ["local-folder", "url"]
    assert catalogue[0]["configured_roots"] == ["handbook"]
    assert str(handbook) not in response.text
    assert "csv" in catalogue[0]["supported_formats"]


def test_local_folder_sync_runs_as_a_durable_job(client: TestClient) -> None:
    response = client.post(
        "/api/connectors/local-folder/sync",
        headers={**TENANT_A, "Idempotency-Key": "handbook-nightly"},
        json={"root": "handbook", "collection": "Operations"},
    )

    assert response.status_code == 202
    queued = response.json()
    assert queued["kind"] == "connector-sync"
    assert queued["status"] == "queued"
    assert queued["connector_name"] == "local-folder"
    assert queued["source_uri"].startswith("connector://")
    assert queued["sync_report"] is None

    completed = client.app.state.knowledge.process_next_ingestion_job()
    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.progress == 100
    assert completed.document_id is None
    assert completed.sync_report is not None
    assert (completed.sync_report.discovered, completed.sync_report.created) == (2, 2)

    persisted = client.get(f"/api/ingestion-jobs/{queued['id']}", headers=TENANT_A)
    assert persisted.status_code == 200
    assert persisted.json()["sync_report"]["created"] == 2

    documents = client.get("/api/documents", headers=TENANT_A).json()
    assert {document["source_uri"] for document in documents} == {
        "local://handbook/routing.md",
        "local://handbook/retention.md",
    }
    answer = client.post(
        "/api/query",
        headers=TENANT_A,
        json={"question": "Which desk owns incident routing?"},
    ).json()
    assert "Mercury" in " ".join(source["passage"] for source in answer["sources"])


def test_repeated_sync_job_is_idempotent(client: TestClient) -> None:
    first = client.post(
        "/api/connectors/local-folder/sync",
        headers={**TENANT_A, "Idempotency-Key": "handbook-nightly"},
        json={"root": "handbook", "collection": "Operations"},
    ).json()
    duplicate = client.post(
        "/api/connectors/local-folder/sync",
        headers={**TENANT_A, "Idempotency-Key": "handbook-nightly"},
        json={"root": "handbook", "collection": "Different"},
    ).json()

    assert duplicate["id"] == first["id"]
    assert len(client.get("/api/ingestion-jobs", headers=TENANT_A).json()) == 1

    client.app.state.knowledge.process_next_ingestion_job()
    second = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook", "collection": "Operations"},
    ).json()
    replayed = client.app.state.knowledge.process_next_ingestion_job()

    assert replayed is not None
    assert replayed.id == second["id"]
    assert replayed.sync_report is not None
    assert (
        replayed.sync_report.created,
        replayed.sync_report.updated,
        replayed.sync_report.unchanged,
    ) == (0, 0, 2)
    assert len(client.get("/api/documents", headers=TENANT_A).json()) == 2


def test_unknown_root_is_rejected_before_a_job_is_created(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "not-configured"},
    )

    assert response.status_code == 404
    assert client.get("/api/ingestion-jobs", headers=TENANT_A).json() == []


def test_traversing_subpath_is_rejected_before_a_job_is_created(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook", "subpath": "../.."},
    )

    assert response.status_code == 422
    assert client.get("/api/ingestion-jobs", headers=TENANT_A).json() == []


def test_unsafe_url_is_rejected_before_a_job_is_created(client: TestClient) -> None:
    response = client.post(
        "/api/connectors/url/sync",
        headers=TENANT_A,
        json={"urls": ["http://169.254.169.254/latest/meta-data/"]},
    )

    assert response.status_code == 422
    assert "metadata" in response.json()["detail"]
    assert client.get("/api/ingestion-jobs", headers=TENANT_A).json() == []


def test_queued_sync_job_can_be_cancelled(client: TestClient) -> None:
    created = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook"},
    ).json()

    cancelled = client.post(
        f"/api/ingestion-jobs/{created['id']}/cancel",
        headers=TENANT_A,
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.app.state.knowledge.process_next_ingestion_job() is None
    assert client.get("/api/documents", headers=TENANT_A).json() == []


def test_cancelling_a_running_sync_keeps_already_indexed_documents(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = client.app.state.knowledge
    created = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook", "collection": "Operations"},
    ).json()

    original_parse = service.parsers.parse
    parsed_documents: list[str] = []

    def cancel_after_first(request):
        parsed_documents.append(request.filename)
        if len(parsed_documents) == 1:
            service.job_store.request_cancel(created["id"])
        return original_parse(request)

    monkeypatch.setattr(service.parsers, "parse", cancel_after_first)
    outcome = service.process_next_ingestion_job()

    assert outcome is not None
    assert outcome.status == "cancelled"
    assert len(parsed_documents) == 1
    documents = client.get("/api/documents", headers=TENANT_A).json()
    assert len(documents) == 1
    assert documents[0]["status"] == "indexed"
    assert service.store.all_vector_document_ids() == {documents[0]["id"]}

    # A later run completes the interrupted work without duplicating anything.
    client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook", "collection": "Operations"},
    )
    finished = service.process_next_ingestion_job()
    assert finished is not None
    assert finished.status == "succeeded"
    assert finished.sync_report is not None
    assert (finished.sync_report.created, finished.sync_report.unchanged) == (1, 1)
    assert len(client.get("/api/documents", headers=TENANT_A).json()) == 2


def test_transient_sync_failure_can_be_retried(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = client.app.state.knowledge
    created = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook"},
    ).json()

    original_run = service.synchronizer.run

    def fail_once(*_args: object, **_kwargs: object):
        raise RuntimeError("simulated storage outage")

    monkeypatch.setattr(service.synchronizer, "run", fail_once)
    failed = service.process_next_ingestion_job()
    assert failed is not None
    assert failed.status == "failed"
    assert failed.attempts == 1
    assert failed.error_type == "RuntimeError"
    assert client.get("/api/documents", headers=TENANT_A).json() == []

    monkeypatch.setattr(service.synchronizer, "run", original_run)
    retried = client.post(
        f"/api/ingestion-jobs/{created['id']}/retry",
        headers=TENANT_A,
    )
    assert retried.status_code == 202

    succeeded = service.process_next_ingestion_job()
    assert succeeded is not None
    assert succeeded.status == "succeeded"
    assert succeeded.attempts == 2
    assert len(client.get("/api/documents", headers=TENANT_A).json()) == 2


def test_a_removed_root_dead_letters_the_sync_job(
    client: TestClient,
    handbook: Path,
) -> None:
    created = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook"},
    ).json()
    for entry in handbook.iterdir():
        entry.unlink()
    handbook.rmdir()

    outcome = client.app.state.knowledge.process_next_ingestion_job()

    assert outcome is not None
    assert outcome.status == "dead_letter"
    assert outcome.error_type == "ConnectorSecurityError"
    assert client.post(
        f"/api/ingestion-jobs/{created['id']}/retry", headers=TENANT_A
    ).status_code == 409


def test_another_tenant_cannot_read_or_control_a_sync_job(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook"},
    ).json()
    client.app.state.knowledge.process_next_ingestion_job()

    assert client.get(f"/api/ingestion-jobs/{created['id']}", headers=TENANT_B).status_code == 404
    assert client.get("/api/ingestion-jobs", headers=TENANT_B).json() == []
    assert client.post(
        f"/api/ingestion-jobs/{created['id']}/cancel", headers=TENANT_B
    ).status_code == 404
    assert client.get("/api/documents", headers=TENANT_B).json() == []
    assert client.post(
        "/api/query",
        headers=TENANT_B,
        json={"question": "Which desk owns incident routing?"},
    ).json()["sources"] == []


def test_upstream_deletion_through_the_job_path_leaves_no_orphaned_vectors(
    client: TestClient,
    handbook: Path,
) -> None:
    service = client.app.state.knowledge
    client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook", "collection": "Operations"},
    )
    service.process_next_ingestion_job()
    (handbook / "retention.md").unlink()

    client.post(
        "/api/connectors/local-folder/sync",
        headers=TENANT_A,
        json={"root": "handbook", "collection": "Operations"},
    )
    outcome = service.process_next_ingestion_job()

    assert outcome is not None
    assert outcome.sync_report is not None
    assert outcome.sync_report.removed == 1
    documents = client.get("/api/documents", headers=TENANT_A).json()
    assert len(documents) == 1
    assert service.store.all_vector_document_ids() == {
        document["id"] for document in documents
    }
    assert client.post(
        "/api/query",
        headers=TENANT_A,
        json={"question": "Who is the retention owner?"},
    ).json()["sources"] == []
