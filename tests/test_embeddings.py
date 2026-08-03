from __future__ import annotations

import httpx
import pytest

from app.embeddings import OpenAICompatibleEmbedder, create_embedder


def test_openai_compatible_embedder_preserves_provider_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(
        self: httpx.Client,
        url: str,
        *,
        json: dict[str, object],
    ) -> httpx.Response:
        request = httpx.Request("POST", f"https://example.test/{url}")
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 7},
            },
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    embedder = OpenAICompatibleEmbedder(
        "test-model",
        base_url="https://example.test/v1",
        api_key="secret",
        dimensions=2,
    )

    assert embedder.embed(["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert embedder.input_tokens == 7


def test_create_embedder_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        create_embedder("unknown", "unused")
