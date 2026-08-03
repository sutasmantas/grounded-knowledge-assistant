from __future__ import annotations

import pytest

from app.retrieval import CrossEncoderReranker, create_reranker


def test_cross_encoder_preserves_model_score_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastembed.rerank import cross_encoder

    class FakeCrossEncoder:
        def __init__(self, model_name: str) -> None:
            assert model_name == "fake-model"

        def rerank(self, query: str, passages: list[str]) -> list[float]:
            assert query == "policy question"
            assert passages == ["first", "second"]
            return [0.2, 0.9]

    monkeypatch.setattr(cross_encoder, "TextCrossEncoder", FakeCrossEncoder)

    reranker = CrossEncoderReranker("fake-model")

    assert reranker.score("policy question", ["first", "second"]) == [0.2, 0.9]


def test_unknown_reranker_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported reranker provider"):
        create_reranker("unknown", "unused")
