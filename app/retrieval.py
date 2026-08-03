from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Protocol

import numpy as np
from qdrant_client import models

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:/-]*", re.IGNORECASE)
SPARSE_BUCKETS = 1_048_576
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "may",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "who",
    "with",
}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def content_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOPWORDS]


class SparseEmbedder:
    """Deterministic lexical vectors; Qdrant applies collection-level IDF."""

    name = "hashed-bm25"

    @staticmethod
    def embed(text: str) -> models.SparseVector:
        counts = Counter(content_tokens(text))
        weighted: dict[int, float] = {}
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "little") % SPARSE_BUCKETS
            weighted[index] = weighted.get(index, 0.0) + 1.0 + math.log(count)
        ordered = sorted(weighted.items())
        return models.SparseVector(
            indices=[index for index, _ in ordered],
            values=[value for _, value in ordered],
        )


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class LexicalReranker:
    """Fast deterministic fallback for tests and resource-constrained deployments."""

    name = "lexical-overlap-v1"

    def score(self, query: str, passages: list[str]) -> list[float]:
        query_tokens = tokenize(query)
        query_set = set(query_tokens)
        scores: list[float] = []
        for passage in passages:
            passage_tokens = tokenize(passage)
            passage_set = set(passage_tokens)
            coverage = len(query_set & passage_set) / max(len(query_set), 1)
            exact_sequence = " ".join(query_tokens) in " ".join(passage_tokens)
            scores.append(coverage + (0.15 if exact_sequence else 0.0))
        return scores


class ColbertReranker:
    """Late-interaction MaxSim reranking without a hosted model dependency."""

    name = "colbert-late-interaction"

    def __init__(self, model_name: str) -> None:
        from fastembed import LateInteractionTextEmbedding

        self._model = LateInteractionTextEmbedding(model_name=model_name)

    def score(self, query: str, passages: list[str]) -> list[float]:
        query_matrix = next(iter(self._model.query_embed([query])))
        passage_matrices = list(self._model.passage_embed(passages))
        scores: list[float] = []
        for passage_matrix in passage_matrices:
            token_similarity = np.asarray(query_matrix) @ np.asarray(passage_matrix).T
            scores.append(float(token_similarity.max(axis=1).sum()))
        return scores


class CrossEncoderReranker:
    """Pairwise query/passage scoring through FastEmbed's ONNX runtime."""

    name = "cross-encoder"

    def __init__(self, model_name: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name=model_name)

    def score(self, query: str, passages: list[str]) -> list[float]:
        return [float(score) for score in self._model.rerank(query, passages)]


def create_reranker(provider: str, model_name: str) -> Reranker:
    if provider == "colbert":
        return ColbertReranker(model_name)
    if provider == "cross-encoder":
        return CrossEncoderReranker(model_name)
    if provider == "lexical":
        return LexicalReranker()
    raise ValueError(f"Unsupported reranker provider: {provider}")
