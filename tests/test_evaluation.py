from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, Settings
from app.evaluation import EvaluationCase, _ndcg_at_5, evaluate, load_cases
from app.service import KnowledgeService


def test_frozen_corpus_has_required_coverage() -> None:
    cases = load_cases(PROJECT_ROOT / "evals" / "golden.jsonl")
    manifest = json.loads(
        (PROJECT_ROOT / "evals" / "experiment-manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert 40 <= len(cases) <= 60
    assert sum(case.split == "held_out" for case in cases) >= 12
    assert sum(case.enabled for case in cases) >= 40
    assert {
        "exact",
        "paraphrase",
        "multi_document",
        "boundary",
        "unanswerable",
        "collection_filter",
        "table",
        "stale_version",
        "prompt_injection",
        "tenant_isolation",
    } <= {case.category for case in cases}
    assert all(case.skip_reason for case in cases if not case.enabled)
    inventory = manifest["dataset"]["inventory"]
    assert inventory == {
        "total_cases": len(cases),
        "runnable_cases": sum(case.enabled for case in cases),
        "capability_gated_cases": sum(not case.enabled for case in cases),
        "development_cases": sum(case.split == "development" for case in cases),
        "held_out_cases": sum(case.split == "held_out" for case in cases),
    }


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    row = {
        "id": "duplicate",
        "split": "development",
        "category": "exact",
        "question": "What is the policy?",
        "expected_titles": ["Policy"],
        "collections": [],
        "should_answer": True,
    }
    path = tmp_path / "cases.jsonl"
    path.write_text(
        f"{json.dumps(row)}\n{json.dumps(row)}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate evaluation case id"):
        load_cases(path)


def test_ndcg_credits_each_relevant_document_once() -> None:
    score = _ndcg_at_5(
        ["Policy A", "Policy A", "Policy A", "Policy B"],
        ["Policy A", "Policy B"],
    )

    assert 0 < score <= 1


def test_evaluation_exports_case_and_group_metrics(tmp_path: Path) -> None:
    service = KnowledgeService(
        Settings(
            data_dir=tmp_path / "runtime",
            embedding_provider="hash",
            reranker_provider="lexical",
            generation_provider="extractive",
        )
    )
    cases = [
        EvaluationCase(
            id="answerable",
            split="development",
            category="exact",
            question="How many days of notice are required for termination?",
            expected_titles=["Enterprise Contract Policy"],
            collections=["Customer contracts"],
            should_answer=True,
        ),
        EvaluationCase(
            id="gated",
            split="held_out",
            category="tenant_isolation",
            question="Can tenant A retrieve tenant B documents?",
            expected_titles=[],
            collections=[],
            should_answer=False,
            enabled=False,
            skip_reason="Tenant ACLs are not implemented yet.",
        ),
    ]
    try:
        service.seed_sample_documents()
        report, rows = evaluate(service, cases, ["hybrid"])
    finally:
        service.close()

    assert len(rows) == 1
    assert rows[0]["case_id"] == "answerable"
    assert rows[0]["ndcg_at_5"] > 0
    assert report["case_inventory"]["capability_gated"] == 1
    metrics = report["profiles"]["hybrid"]
    assert metrics["overall"]["cases"] == 1
    assert metrics["by_split"]["development"]["mrr_at_5"] > 0
    assert metrics["by_category"]["exact"]["p95_total_ms"] >= 0
