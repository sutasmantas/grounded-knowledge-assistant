from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.evaluation import EvaluationCase
from app.semantic_evaluation import evaluate_semantics, select_cases
from app.service import KnowledgeService


class ExactJudge:
    name = "exact-test-judge"

    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [
            float(" ".join(hypothesis.lower().split()) in " ".join(premise.lower().split()))
            for premise, hypothesis in pairs
        ]


@pytest.fixture
def service(tmp_path: Path):
    instance = KnowledgeService(
        Settings(
            data_dir=tmp_path,
            embedding_provider="hash",
            generation_provider="extractive",
            reranker_provider="lexical",
        )
    )
    try:
        yield instance
    finally:
        instance.close()


def test_semantic_evaluation_checks_claims_against_cited_passages(
    service: KnowledgeService,
) -> None:
    service.seed_sample_documents()
    cases = [
        EvaluationCase(
            id="refund",
            split="held_out",
            category="exact",
            question="Where do approved refunds return?",
            expected_titles=["Billing Close Procedure"],
            collections=[],
            should_answer=True,
        )
    ]

    aggregate, rows = evaluate_semantics(
        service=service,
        cases=cases,
        judge=ExactJudge(),
        retrieval_profile="sparse",
    )

    assert aggregate["citation_validity"] == 1.0
    assert aggregate["citation_completeness"] == 1.0
    assert aggregate["exact_citation_support"] == 1.0
    assert aggregate["mean_semantic_citation_support"] == 1.0
    assert rows[0]["statements"]
    assert all(
        not statement["text"].lstrip().startswith("#")
        for statement in rows[0]["statements"]
    )


def test_semantic_evaluation_counts_selected_cases(
    service: KnowledgeService,
) -> None:
    service.seed_sample_documents()
    cases = [
        EvaluationCase(
            id="refund",
            split="held_out",
            category="exact",
            question="Where do approved refunds return?",
            expected_titles=["Billing Close Procedure"],
            collections=[],
            should_answer=True,
        )
    ]
    aggregate, _ = evaluate_semantics(
        service=service,
        cases=cases,
        judge=ExactJudge(),
        retrieval_profile="sparse",
    )

    assert aggregate["cases"] == 1


def test_semantic_selection_excludes_capability_gated_cases() -> None:
    enabled = EvaluationCase(
        id="enabled",
        split="held_out",
        category="exact",
        question="What is the policy?",
        expected_titles=["Policy"],
        collections=[],
        should_answer=True,
    )
    gated = EvaluationCase(
        id="gated",
        split="held_out",
        category="prompt_injection",
        question="What is the future test?",
        expected_titles=[],
        collections=[],
        should_answer=False,
        enabled=False,
        skip_reason="Requires a future capability.",
    )

    assert select_cases(
        [enabled, gated],
        split="held_out",
        expected_count=1,
    ) == [enabled]


def test_provider_failure_is_recorded_when_comparison_continues() -> None:
    case = EvaluationCase(
        id="provider-failure",
        split="held_out",
        category="exact",
        question="What is the policy?",
        expected_titles=["Policy"],
        collections=[],
        should_answer=True,
    )

    class FailingService:
        def query(self, *_args, **_kwargs):
            raise TimeoutError("model endpoint timed out")

    aggregate, rows = evaluate_semantics(
        service=FailingService(),  # type: ignore[arg-type]
        cases=[case],
        judge=ExactJudge(),
        retrieval_profile="sparse",
        continue_on_error=True,
    )

    assert aggregate["failed_cases"] == 1
    assert aggregate["abstention_accuracy"] == 0.0
    assert rows[0]["error"] == "TimeoutError: model endpoint timed out"
