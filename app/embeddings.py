from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from typing import Any, Protocol

import httpx

VECTOR_SIZE = 384
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9']{1,}", re.IGNORECASE)


class Embedder(Protocol):
    name: str
    vector_size: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Dependency-light deterministic vectorizer used for local runs and tests."""

    name = "hash"
    vector_size = VECTOR_SIZE

    @staticmethod
    def _features(text: str) -> Iterable[str]:
        tokens = [token.lower() for token in TOKEN_PATTERN.findall(text)]
        yield from tokens
        yield from (f"{left}_{right}" for left, right in zip(tokens, tokens[1:], strict=False))

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * VECTOR_SIZE
            for feature in self._features(text):
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "little") % VECTOR_SIZE
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[bucket] += sign
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class FastEmbedder:
    name = "fastembed"

    def __init__(self, model_name: str) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "FastEmbed is not installed. Run `pip install -e .` or set "
                "ATLAS_EMBEDDING_PROVIDER=hash."
            ) from exc
        self._model = TextEmbedding(model_name=model_name)
        self.vector_size = TextEmbedding.get_embedding_size(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Sentence Transformers is not installed. Run "
                '`pip install -e ".[embedding-benchmark]"`.'
            ) from exc
        self._model = SentenceTransformer(model_name)
        dimensions = self._model.get_embedding_dimension()
        if dimensions is None:
            raise RuntimeError(f"Could not determine embedding size for {model_name}")
        self.vector_size = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]


class OpenAICompatibleEmbedder:
    name = "openai-compatible"

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str,
        api_key: str,
        dimensions: int,
    ) -> None:
        self.model_name = model_name
        self.vector_size = dimensions
        self.input_tokens = 0
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            "embeddings",
            json={
                "model": self.model_name,
                "input": texts,
                "dimensions": self.vector_size,
                "encoding_format": "float",
            },
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        data = sorted(body["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding provider returned an unexpected vector count")
        if any(len(vector) != self.vector_size for vector in vectors):
            raise RuntimeError("Embedding provider returned an unexpected vector size")
        self.input_tokens += int(body.get("usage", {}).get("prompt_tokens", 0))
        return vectors

    def close(self) -> None:
        self._client.close()


def create_embedder(
    provider: str,
    model_name: str,
    *,
    base_url: str = "",
    api_key: str = "",
    dimensions: int | None = None,
) -> Embedder:
    if provider == "fastembed":
        return FastEmbedder(model_name)
    if provider == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name)
    if provider == "openai-compatible":
        if not dimensions:
            raise ValueError("OpenAI-compatible embeddings require dimensions")
        return OpenAICompatibleEmbedder(
            model_name,
            base_url=base_url,
            api_key=api_key,
            dimensions=dimensions,
        )
    if provider == "hash":
        return HashEmbedder()
    raise ValueError(f"Unsupported embedding provider: {provider}")
