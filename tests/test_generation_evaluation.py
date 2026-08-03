from __future__ import annotations

from app.generation_evaluation import promotion_decision


def metrics(**overrides):
    values = {
        "failed_cases": 0,
        "token_accounting_coverage": 1.0,
        "p95_generation_ms": 2000,
        "citation_validity": 1.0,
        "citation_completeness": 1.0,
        "mean_semantic_citation_support": 0.8,
        "mean_semantic_answer_faithfulness": 0.8,
        "abstention_accuracy": 1.0,
    }
    values.update(overrides)
    return values


GATE = {
    "noninferiority_tolerance": 0.0,
    "noninferiority_metrics": [
        "citation_validity",
        "citation_completeness",
        "mean_semantic_citation_support",
        "mean_semantic_answer_faithfulness",
        "abstention_accuracy",
    ],
    "quality_gain_metrics": [
        "mean_semantic_citation_support",
        "mean_semantic_answer_faithfulness",
    ],
    "minimum_quality_gain": 0.02,
    "max_candidate_p95_generation_ms": 15000,
}


RESOURCE = {
    "container_image_id": "sha256:runner",
    "peak_memory_mb": 900.0,
    "model_file_bytes": 500_000_000,
    "measurement_command": "docker stats --no-stream",
}


def test_candidate_promotes_only_with_noninferiority_and_quality_gain() -> None:
    decision = promotion_decision(
        metrics(),
        metrics(
            mean_semantic_citation_support=0.82,
            mean_semantic_answer_faithfulness=0.82,
        ),
        GATE,
        RESOURCE,
    )

    assert decision["promote_candidate"] is True
    assert decision["selected_default"] == "candidate"


def test_fluent_but_unmeasured_candidate_does_not_promote() -> None:
    decision = promotion_decision(
        metrics(),
        metrics(
            token_accounting_coverage=0.0,
            mean_semantic_answer_faithfulness=0.9,
        ),
        GATE,
        {},
    )

    assert decision["promote_candidate"] is False
    assert decision["checks"]["candidate_tokens_measured"] is False
    assert decision["checks"]["candidate_resource_measured"] is False


def test_quality_gain_cannot_hide_abstention_regression() -> None:
    decision = promotion_decision(
        metrics(),
        metrics(
            mean_semantic_answer_faithfulness=0.9,
            abstention_accuracy=0.5,
        ),
        GATE,
        RESOURCE,
    )

    assert decision["promote_candidate"] is False
    assert decision["checks"]["noninferior_abstention_accuracy"] is False
