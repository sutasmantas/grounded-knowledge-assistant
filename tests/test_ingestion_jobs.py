from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import IngestionJobRunner, IngestionJobStore
from app.main import create_app


def job_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
        ingestion_job_max_attempts=3,
    )


def test_async_ingestion_is_idempotent_and_exposes_result(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(job_settings(tmp_path))) as client:
        response = client.post(
            "/api/ingestion-jobs",
            headers={"Idempotency-Key": "handbook-import-2026-07-30"},
            data={
                "collection": "Operations",
                "source_uri": "handbook://routing",
            },
            files={
                "file": (
                    "routing.md",
                    b"# Routing\nThe incident routing owner is Atlas.",
                    "text/markdown",
                )
            },
        )
        assert response.status_code == 202
        queued = response.json()
        assert queued["status"] == "queued"
        assert queued["attempts"] == 0

        duplicate_request = client.post(
            "/api/ingestion-jobs",
            headers={"Idempotency-Key": "handbook-import-2026-07-30"},
            files={
                "file": (
                    "other.md",
                    b"# Different\nThis body must not create another job.",
                    "text/markdown",
                )
            },
        )
        assert duplicate_request.status_code == 202
        assert duplicate_request.json()["id"] == queued["id"]
        assert len(client.get("/api/ingestion-jobs").json()) == 1

        completed = client.app.state.knowledge.process_next_ingestion_job()
        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.progress == 100
        assert completed.attempts == 1
        assert completed.document_id

        persisted = client.get(f"/api/ingestion-jobs/{queued['id']}")
        assert persisted.status_code == 200
        assert persisted.json()["document_id"] == completed.document_id
        assert persisted.json()["finished_at"]

        answer = client.post(
            "/api/query",
            json={"question": "Who is the incident routing owner?"},
        )
        assert answer.status_code == 200
        assert {
            source["document_id"] for source in answer.json()["sources"]
        } == {completed.document_id}
        assert not (
            client.app.state.knowledge.settings.ingestion_job_inputs_dir
            / queued["id"]
        ).exists()


def test_queued_ingestion_job_can_be_cancelled(tmp_path: Path) -> None:
    with TestClient(create_app(job_settings(tmp_path))) as client:
        created = client.post(
            "/api/ingestion-jobs",
            files={
                "file": (
                    "cancel.md",
                    b"# Cancel\nThis document should never be indexed.",
                    "text/markdown",
                )
            },
        ).json()

        cancelled = client.post(
            f"/api/ingestion-jobs/{created['id']}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert client.app.state.knowledge.process_next_ingestion_job() is None
        assert client.get("/api/documents").json() == []
        assert not (
            client.app.state.knowledge.settings.ingestion_job_inputs_dir
            / created["id"]
        ).exists()


def test_transient_ingestion_failure_can_be_retried(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with TestClient(create_app(job_settings(tmp_path))) as client:
        service = client.app.state.knowledge
        created = client.post(
            "/api/ingestion-jobs",
            files={
                "file": (
                    "retry.md",
                    b"# Retry\nThe retry owner is Atlas.",
                    "text/markdown",
                )
            },
        ).json()
        original_ingest = service.ingest_path

        def fail_once(*args, **kwargs):
            raise RuntimeError("simulated provider timeout")

        monkeypatch.setattr(service, "ingest_path", fail_once)
        failed = service.process_next_ingestion_job()
        assert failed is not None
        assert failed.status == "failed"
        assert failed.attempts == 1
        assert failed.error_type == "RuntimeError"

        monkeypatch.setattr(service, "ingest_path", original_ingest)
        retried = client.post(
            f"/api/ingestion-jobs/{created['id']}/retry"
        )
        assert retried.status_code == 202
        assert retried.json()["status"] == "queued"

        succeeded = service.process_next_ingestion_job()
        assert succeeded is not None
        assert succeeded.status == "succeeded"
        assert succeeded.attempts == 2


def test_permanent_failure_moves_to_dead_letter_and_can_be_replayed(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(job_settings(tmp_path))) as client:
        created = client.post(
            "/api/ingestion-jobs",
            files={
                "file": (
                    "unsupported.zip",
                    b"PK\x03\x04binary",
                    "application/zip",
                )
            },
        ).json()

        dead_letter = client.app.state.knowledge.process_next_ingestion_job()
        assert dead_letter is not None
        assert dead_letter.status == "dead_letter"
        assert dead_letter.error_type == "UnsupportedDocumentError"
        assert "Supported document types" in (dead_letter.error_message or "")

        retry = client.post(f"/api/ingestion-jobs/{created['id']}/retry")
        assert retry.status_code == 409

        replay = client.post(f"/api/ingestion-jobs/{created['id']}/replay")
        assert replay.status_code == 202
        assert replay.json()["attempts"] == 0
        replayed = client.app.state.knowledge.process_next_ingestion_job()
        assert replayed is not None
        assert replayed.status == "dead_letter"
        assert replayed.attempts == 1


def test_running_job_is_recovered_after_worker_restart(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    job_directory = input_root / "job-1"
    job_directory.mkdir(parents=True)
    input_path = job_directory / "policy.md"
    input_path.write_text("# Policy\nThe owner is Atlas.", encoding="utf-8")
    database_path = tmp_path / "jobs.sqlite3"
    store = IngestionJobStore(database_path, input_root)
    created, was_created = store.create(
        job_id="job-1",
        idempotency_key=None,
        filename="policy.md",
        collection="General",
        source_uri="upload://policy.md",
        mime_type="text/markdown",
        input_path=input_path,
        max_attempts=3,
    )
    assert was_created
    assert created.status == "queued"
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.attempts == 1

    restarted_store = IngestionJobStore(database_path, input_root)
    assert restarted_store.recover_interrupted() == 1
    recovered = restarted_store.get("job-1")
    assert recovered is not None
    assert recovered.status == "queued"
    assert recovered.stage == "recovered"
    assert recovered.error_type == "WorkerInterrupted"


def test_cancel_requested_job_finishes_cancellation_during_recovery(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    job_directory = input_root / "job-1"
    job_directory.mkdir(parents=True)
    input_path = job_directory / "policy.md"
    input_path.write_text("# Policy\nThe owner is Atlas.", encoding="utf-8")
    store = IngestionJobStore(tmp_path / "jobs.sqlite3", input_root)
    store.create(
        job_id="job-1",
        idempotency_key=None,
        filename="policy.md",
        collection="General",
        source_uri="upload://policy.md",
        mime_type="text/markdown",
        input_path=input_path,
        max_attempts=3,
    )
    assert store.claim_next() is not None
    requested = store.request_cancel("job-1")
    assert requested.status == "running"
    assert requested.cancel_requested

    assert store.recover_interrupted() == 1
    recovered = store.get("job-1")
    assert recovered is not None
    assert recovered.status == "cancelled"
    assert not job_directory.exists()


def test_running_job_honors_cooperative_cancellation(tmp_path: Path) -> None:
    input_root = tmp_path / "inputs"
    job_directory = input_root / "job-1"
    job_directory.mkdir(parents=True)
    input_path = job_directory / "policy.md"
    input_path.write_text("# Policy\nThe owner is Atlas.", encoding="utf-8")
    store = IngestionJobStore(tmp_path / "jobs.sqlite3", input_root)
    store.create(
        job_id="job-1",
        idempotency_key=None,
        filename="policy.md",
        collection="General",
        source_uri="upload://policy.md",
        mime_type="text/markdown",
        input_path=input_path,
        max_attempts=3,
    )

    def cancel_during_work(job, progress):
        store.request_cancel(job.id)
        progress(40, "extracting")
        return "unreachable"

    runner = IngestionJobRunner(store, cancel_during_work, poll_seconds=0.1)
    cancelled = runner.run_once()

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_requested
    assert not job_directory.exists()


def test_terminal_job_exposes_input_cleanup_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_root = tmp_path / "inputs"
    job_directory = input_root / "job-1"
    job_directory.mkdir(parents=True)
    input_path = job_directory / "policy.md"
    input_path.write_text("# Policy\nThe owner is Atlas.", encoding="utf-8")
    store = IngestionJobStore(tmp_path / "jobs.sqlite3", input_root)
    store.create(
        job_id="job-1",
        idempotency_key=None,
        filename="policy.md",
        collection="General",
        source_uri="upload://policy.md",
        mime_type="text/markdown",
        input_path=input_path,
        max_attempts=3,
    )

    def fail_cleanup(_job_id: str) -> None:
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(store, "remove_input", fail_cleanup)
    runner = IngestionJobRunner(
        store,
        lambda _job, _progress: "document-1",
        poll_seconds=0.1,
    )
    result = runner.run_once()

    assert result is not None
    assert result.status == "succeeded"
    assert result.stage == "succeeded_cleanup_failed"
    assert result.error_type == "InputCleanupError"
    assert "simulated cleanup failure" in (result.error_message or "")
