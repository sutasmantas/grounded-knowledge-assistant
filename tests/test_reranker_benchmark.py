from __future__ import annotations

import json

from app.evaluation import DEFAULT_CASES
from app.reranker_benchmark import (
    DEFAULT_MANIFEST,
    RERANKER_CANDIDATES,
    run_benchmark,
)


def test_reranker_manifest_matches_supported_candidates() -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    assert list(manifest["candidates"]) == RERANKER_CANDIDATES


def test_reranker_benchmark_exports_baseline_metrics() -> None:
    report, rows = run_benchmark(
        cases_path=DEFAULT_CASES,
        manifest_path=DEFAULT_MANIFEST,
        candidates=["none"],
        embedding_provider="hash",
        embedding_model="unused",
    )

    baseline = report["results"]["none"]
    assert baseline["provider"] is None
    assert baseline["documents"] == 6
    assert baseline["indexed_chunks"] > baseline["documents"]
    assert baseline["warmup_ms"] == 0
    assert baseline["overall"]["recall_at_5"] > 0
    assert rows
    assert {row["reranker_candidate"] for row in rows} == {"none"}
