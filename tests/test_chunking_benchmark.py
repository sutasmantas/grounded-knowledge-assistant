from __future__ import annotations

from app.chunking_benchmark import DEFAULT_MANIFEST, run_benchmark
from app.evaluation import DEFAULT_CASES


def test_chunking_benchmark_exports_quality_and_operational_metrics() -> None:
    report, rows = run_benchmark(
        cases_path=DEFAULT_CASES,
        manifest_path=DEFAULT_MANIFEST,
        chunking_profiles=["fixed"],
        embedding_provider="hash",
        retrieval_profile="hybrid",
    )

    fixed = report["results"]["fixed"]
    assert report["embedding_provider"] == "hash"
    assert fixed["documents"] == 6
    assert fixed["indexed_chunks"] > fixed["documents"]
    assert fixed["index_build_ms"] >= 0
    assert fixed["index_disk_bytes"] > 0
    assert fixed["overall"]["recall_at_5"] > 0
    assert rows
    assert {row["chunking_profile"] for row in rows} == {"fixed"}
