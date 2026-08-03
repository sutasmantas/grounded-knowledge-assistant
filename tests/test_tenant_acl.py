from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import IngestionJobStore
from app.main import create_app


def access_headers(
    tenant: str,
    principal: str,
    groups: str | None = None,
) -> dict[str, str]:
    headers = {
        "X-Atlas-Tenant": tenant,
        "X-Atlas-Principal": principal,
    }
    if groups:
        headers["X-Atlas-Groups"] = groups
    return headers


def isolated_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )


def test_restricted_document_is_filtered_before_retrieval_and_direct_access(
    tmp_path: Path,
) -> None:
    owner = access_headers("acme", "owner")
    other_user = access_headers("acme", "other")
    named_reader = access_headers("acme", "analyst")
    group_reader = access_headers("acme", "counsel", "legal")
    other_tenant = access_headers("globex", "owner")
    canary = "TENANT_CANARY_ORCHID_9417"

    with TestClient(create_app(isolated_settings(tmp_path))) as client:
        created_response = client.post(
            "/api/documents",
            headers=owner,
            data={
                "collection": "Mergers",
                "visibility": "restricted",
                "allowed_principals": "analyst",
                "allowed_groups": "legal",
            },
            files={
                "file": (
                    "acquisition.md",
                    f"# Acquisition\nThe confidential code is {canary}.".encode(),
                    "text/markdown",
                )
            },
        )
        assert created_response.status_code == 201
        created = created_response.json()
        document_id = created["id"]

        for denied in (other_user, other_tenant):
            assert client.get("/api/documents", headers=denied).json() == []
            assert (
                client.get(
                    f"/api/documents/{document_id}/versions",
                    headers=denied,
                ).status_code
                == 404
            )
            denied_query = client.post(
                "/api/query",
                headers=denied,
                json={"question": f"What is the code {canary}?"},
            )
            assert denied_query.status_code == 200
            assert denied_query.json()["sources"] == []
            assert canary not in denied_query.json()["answer"]

        for reader in (named_reader, group_reader):
            listed = client.get("/api/documents", headers=reader).json()
            assert [item["id"] for item in listed] == [document_id]
            allowed_query = client.post(
                "/api/query",
                headers=reader,
                json={"question": f"What is the code {canary}?"},
            )
            assert allowed_query.status_code == 200
            assert {
                source["document_id"]
                for source in allowed_query.json()["sources"]
            } == {document_id}
            assert (
                client.delete(
                    f"/api/documents/{document_id}",
                    headers=reader,
                ).status_code
                == 404
            )

        assert (
            client.delete(
                f"/api/documents/{document_id}",
                headers=owner,
            ).status_code
            == 204
        )


def test_tenant_document_hashes_are_scoped_without_cross_tenant_disclosure(
    tmp_path: Path,
) -> None:
    content = b"# Shared Template\nThe routing owner is Atlas."
    with TestClient(create_app(isolated_settings(tmp_path))) as client:
        first = client.post(
            "/api/documents",
            headers=access_headers("acme", "owner"),
            files={"file": ("routing.md", content, "text/markdown")},
        )
        second = client.post(
            "/api/documents",
            headers=access_headers("globex", "owner"),
            files={"file": ("routing.md", content, "text/markdown")},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
        assert {
            item["id"]
            for item in client.get(
                "/api/documents",
                headers=access_headers("acme", "reader"),
            ).json()
        } == {first.json()["id"]}


def test_tenant_visible_documents_are_readable_but_only_owner_can_manage(
    tmp_path: Path,
) -> None:
    owner = access_headers("acme", "owner")
    colleague = access_headers("acme", "colleague")
    with TestClient(create_app(isolated_settings(tmp_path))) as client:
        created = client.post(
            "/api/documents",
            headers=owner,
            files={
                "file": (
                    "handbook.md",
                    b"# Handbook\nThe support owner is Atlas.",
                    "text/markdown",
                )
            },
        ).json()

        assert [item["id"] for item in client.get(
            "/api/documents",
            headers=colleague,
        ).json()] == [created["id"]]
        denied_reindex = client.put(
            f"/api/documents/{created['id']}",
            headers=colleague,
            files={
                "file": (
                    "handbook.md",
                    b"# Handbook\nThe support owner is Nova.",
                    "text/markdown",
                )
            },
        )
        assert denied_reindex.status_code == 404
        assert (
            client.delete(
                f"/api/documents/{created['id']}",
                headers=colleague,
            ).status_code
            == 404
        )


def test_ingestion_jobs_and_idempotency_keys_are_tenant_and_owner_scoped(
    tmp_path: Path,
) -> None:
    acme_owner = access_headers("acme", "owner")
    acme_other = access_headers("acme", "other")
    globex_owner = access_headers("globex", "owner")
    idempotency = {"Idempotency-Key": "daily-import"}

    with TestClient(create_app(isolated_settings(tmp_path))) as client:
        acme_job = client.post(
            "/api/ingestion-jobs",
            headers=acme_owner | idempotency,
            files={
                "file": (
                    "acme.md",
                    b"# Acme\nThe owner is Atlas.",
                    "text/markdown",
                )
            },
        )
        globex_job = client.post(
            "/api/ingestion-jobs",
            headers=globex_owner | idempotency,
            files={
                "file": (
                    "globex.md",
                    b"# Globex\nThe owner is Nova.",
                    "text/markdown",
                )
            },
        )
        assert acme_job.status_code == 202
        assert globex_job.status_code == 202
        assert acme_job.json()["id"] != globex_job.json()["id"]

        acme_job_id = acme_job.json()["id"]
        acme_other_job = client.post(
            "/api/ingestion-jobs",
            headers=acme_other | idempotency,
            files={
                "file": (
                    "other.md",
                    b"# Other\nThe owner is Orion.",
                    "text/markdown",
                )
            },
        )
        assert acme_other_job.status_code == 202
        assert acme_other_job.json()["id"] != acme_job_id
        assert client.get(
            f"/api/ingestion-jobs/{acme_job_id}",
            headers=acme_other,
        ).status_code == 404
        assert client.get(
            f"/api/ingestion-jobs/{acme_job_id}",
            headers=globex_owner,
        ).status_code == 404
        assert client.post(
            f"/api/ingestion-jobs/{acme_job_id}/cancel",
            headers=acme_other,
        ).status_code == 404
        assert client.get(
            "/api/ingestion-jobs",
            headers=acme_other,
        ).json() == [acme_other_job.json()]
        assert {
            job["id"]
            for job in client.get(
                "/api/ingestion-jobs",
                headers=acme_owner,
            ).json()
        } == {acme_job_id}


def test_untrusted_identity_header_shape_is_rejected(tmp_path: Path) -> None:
    with TestClient(create_app(isolated_settings(tmp_path))) as client:
        response = client.get(
            "/api/documents",
            headers={
                "X-Atlas-Tenant": "../invalid tenant",
                "X-Atlas-Principal": "owner",
            },
        )

    assert response.status_code == 422


def test_existing_ingestion_jobs_receive_demo_identity_and_scoped_key(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE ingestion_jobs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL,
                stage TEXT NOT NULL,
                filename TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                input_path TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                cancel_requested INTEGER NOT NULL,
                error_type TEXT,
                error_message TEXT,
                document_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO ingestion_jobs VALUES (
                'legacy-job', 'legacy-import', 'queued', 0, 'queued',
                'legacy.md', 'General', 'upload://legacy.md', 'text/markdown',
                'legacy.md', 0, 3, 0, NULL, NULL, NULL,
                '2026-07-30T10:00:00+00:00', '2026-07-30T10:00:00+00:00',
                NULL, NULL
            )
            """
        )

    store = IngestionJobStore(database, tmp_path / "inputs")
    migrated = store.get_by_idempotency_key("legacy-import")

    assert migrated is not None
    assert migrated.id == "legacy-job"
    assert migrated.tenant_id == "demo"
    assert migrated.owner_principal_id == "demo-user"
