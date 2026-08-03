from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_seeded_documents_and_grounded_query(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        embedding_provider="hash",
        generation_provider="extractive",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["chunking_profile"] == "fixed"

        documents = client.get("/api/documents")
        assert documents.status_code == 200
        assert len(documents.json()) == 6

        response = client.post(
            "/api/query",
            json={"question": "Who approves a commercial exception below 50,000 USD?"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["sources"]
        assert "[1]" in payload["answer"]
        assert any(
            "Account Management Handbook" == source["title"] for source in payload["sources"]
        )


def test_upload_is_persisted_and_duplicate_is_rejected(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
    )
    document = b"# Security Exception\nA severity-one incident permits a request within 30 days."
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/documents",
            data={"collection": "Security & compliance"},
            files={"file": ("security_exception.md", document, "text/markdown")},
        )
        assert created.status_code == 201
        assert created.json()["chunk_count"] == 1
        assert created.json()["version"] == 1
        assert created.json()["source_uri"] == "upload://security_exception.md"
        assert len(created.json()["sha256"]) == 64

        duplicate = client.post(
            "/api/documents",
            data={"collection": "Security & compliance"},
            files={"file": ("security_exception.md", document, "text/markdown")},
        )
        assert duplicate.status_code == 409

        listed = client.get("/api/documents")
        assert len(listed.json()) == 1
        document_id = created.json()["id"]

    with TestClient(create_app(settings)) as client:
        listed = client.get("/api/documents")
        assert [item["id"] for item in listed.json()] == [document_id]

        deleted = client.delete(f"/api/documents/{document_id}")
        assert deleted.status_code == 204
        assert client.get("/api/documents").json() == []


def test_query_respects_collection_filter(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        embedding_provider="hash",
        generation_provider="extractive",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/query",
            json={
                "question": "When is an unused annual plan eligible for a refund?",
                "collections": ["Billing & renewals"],
            },
        )
        assert response.status_code == 200
        sources = response.json()["sources"]
        assert sources
        assert {source["collection"] for source in sources} == {"Billing & renewals"}
        trace = response.json()["retrieval"]
        assert trace["profile"] == "sparse"
        assert trace["fusion"] is None
        assert trace["candidates_considered"] >= len(sources)


def test_retrieval_profiles_are_selectable(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        embedding_provider="hash",
        reranker_provider="lexical",
        generation_provider="extractive",
    )
    with TestClient(create_app(settings)) as client:
        for profile in ("dense", "sparse", "hybrid", "hybrid-reranked"):
            response = client.post(
                "/api/query",
                json={
                    "question": "Who approves a commercial exception below 50,000 USD?",
                    "retrieval_profile": profile,
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["retrieval"]["profile"] == profile
            if profile == "hybrid-reranked":
                assert payload["retrieval"]["reranker"] == "lexical-overlap-v1"
                assert all(source["rerank_score"] is not None for source in payload["sources"])
            else:
                assert all(source["rerank_score"] is None for source in payload["sources"])
            if profile == "sparse":
                assert payload["retrieval"]["fusion"] is None


def test_query_profiles_can_be_compared_side_by_side(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        embedding_provider="hash",
        reranker_provider="lexical",
        generation_provider="extractive",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/evaluations/compare",
            json={
                "question": "Who approves a commercial exception below 50,000 USD?",
                "profiles": ["sparse", "hybrid"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == (
        "Who approves a commercial exception below 50,000 USD?"
    )
    assert [result["retrieval"]["profile"] for result in payload["results"]] == [
        "sparse",
        "hybrid",
    ]
    assert all(result["sources"] for result in payload["results"])
    assert all("[1]" in result["answer"] for result in payload["results"])


def test_query_comparison_rejects_duplicate_profiles(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        embedding_provider="hash",
        generation_provider="extractive",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/evaluations/compare",
            json={
                "question": "Who approves this exception?",
                "profiles": ["sparse", "sparse"],
            },
        )

    assert response.status_code == 422
    assert "Comparison profiles must be unique" in response.text


def test_parent_child_contexts_do_not_collide_across_documents(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        chunking_profile="parent-child",
        embedding_provider="hash",
        generation_provider="extractive",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/query",
            json={
                "question": (
                    "Where must an approved refund be sent, and which records "
                    "must Billing retain?"
                ),
                "collections": ["Billing & renewals"],
            },
        )

    assert response.status_code == 200
    titles = {source["title"] for source in response.json()["sources"]}
    assert {"Billing Close Procedure", "Customer Refund Policy"} <= titles


def test_irrelevant_query_can_return_no_match(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        embedding_provider="hash",
        generation_provider="extractive",
        min_score=0.95,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/query",
            json={"question": "quantum banana telescope"},
        )
        assert response.status_code == 200
        assert response.json()["sources"] == []
        assert "could not find relevant information" in response.json()["answer"]


def test_unsupported_upload_returns_validation_error(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/documents",
            data={"collection": "General"},
            files={
                "file": (
                    "archive.zip",
                    b"PK\x03\x04binary",
                    "application/zip",
                )
            },
        )
        assert response.status_code == 422
        assert "Supported document types" in response.json()["detail"]

        accepted = client.post(
            "/api/documents",
            data={"collection": "General"},
            files={"file": ("roster.csv", b"owner,team\nAtlas,Operations", "text/csv")},
        )
        assert accepted.status_code == 201
        assert accepted.json()["chunk_count"] >= 1


def test_reindex_creates_version_history_and_hides_stale_vectors(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
    )
    first_content = (
        b"# Escalation Policy\n"
        b"The legacy escalation owner is the Mercury desk."
    )
    replacement_content = (
        b"# Escalation Policy\n"
        b"The current escalation owner is the Atlas desk."
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/documents",
            data={
                "collection": "Operations",
                "source_uri": "handbook://escalation-policy",
            },
            files={"file": ("escalation_policy.md", first_content, "text/markdown")},
        )
        assert created.status_code == 201
        first = created.json()

        replaced = client.put(
            f"/api/documents/{first['id']}",
            data={"collection": "Operations"},
            files={
                "file": (
                    "escalation_policy.md",
                    replacement_content,
                    "text/markdown",
                )
            },
        )
        assert replaced.status_code == 200
        second = replaced.json()
        assert second["source_id"] == first["source_id"]
        assert second["source_uri"] == first["source_uri"]
        assert second["version"] == 2
        assert second["supersedes_document_id"] == first["id"]

        versions = client.get("/api/documents").json()
        assert [(item["version"], item["status"]) for item in versions] == [
            (2, "indexed")
        ]
        source_history = client.get(
            f"/api/documents/{second['id']}/versions"
        ).json()
        assert [item["version"] for item in source_history] == [2, 1]

        current_query = client.post(
            "/api/query",
            json={"question": "Who is the current escalation owner?"},
        )
        assert current_query.status_code == 200
        assert {
            source["document_id"] for source in current_query.json()["sources"]
        } == {second["id"]}
        assert {
            source["document_version"] for source in current_query.json()["sources"]
        } == {2}
        assert {
            source["source_uri"] for source in current_query.json()["sources"]
        } == {"handbook://escalation-policy"}
        assert {
            source["document_sha256"] for source in current_query.json()["sources"]
        } == {second["sha256"]}
        assert "Atlas desk" in current_query.json()["sources"][0]["passage"]

        stale_query = client.post(
            "/api/query",
            json={"question": "Which desk is named Mercury?"},
        )
        assert stale_query.status_code == 200
        assert stale_query.json()["sources"] == []

        deleted = client.delete(f"/api/documents/{second['id']}")
        assert deleted.status_code == 204
        assert client.get("/api/documents").json() == []
        assert (
            client.get(f"/api/documents/{second['id']}/versions").status_code
            == 404
        )
        deleted_query = client.post(
            "/api/query",
            json={"question": "Which routing desk is named Atlas?"},
        )
        assert deleted_query.status_code == 200
        assert deleted_query.json()["sources"] == []


def test_reindex_rejects_duplicate_without_superseding_current_version(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
    )
    content = b"# Policy\nThe current approval owner is Finance."
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/documents",
            files={"file": ("policy.md", content, "text/markdown")},
        )
        document_id = created.json()["id"]

        duplicate = client.put(
            f"/api/documents/{document_id}",
            files={"file": ("policy.md", content, "text/markdown")},
        )

        assert duplicate.status_code == 409
        versions = client.get("/api/documents").json()
        assert len(versions) == 1
        assert versions[0]["id"] == document_id
        assert versions[0]["status"] == "indexed"


def test_reindex_unknown_document_returns_not_found(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
    )
    with TestClient(create_app(settings)) as client:
        response = client.put(
            "/api/documents/missing",
            files={
                "file": (
                    "policy.md",
                    b"# Policy\nThe owner is Finance.",
                    "text/markdown",
                )
            },
        )

    assert response.status_code == 404
