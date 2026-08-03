from __future__ import annotations

import json
from pathlib import Path

from app.embedding_benchmark import run_benchmark


def test_embedding_benchmark_runs_local_candidate(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "candidates": {
                    "local": {
                        "provider": "hash",
                        "model": "unused",
                        "dimensions": 384,
                        "execution": "local",
                        "input_price_usd_per_million": 0.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report, rows = run_benchmark(
        cases_path=Path("evals/golden.jsonl").resolve(),
        manifest_path=manifest_path,
    )

    result = report["results"]["local"]
    assert result["status"] == "completed"
    assert result["quality_metrics"]["dense"]["overall"]["cases"] == 50
    assert result["indexed_chunks"] > 0
    assert {row["embedding_candidate"] for row in rows} == {"local"}


def test_embedding_benchmark_records_missing_hosted_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "candidates": {
                    "hosted": {
                        "provider": "openai-compatible",
                        "model": "test-model",
                        "dimensions": 4,
                        "execution": "credentialed",
                        "credential_env": "TEST_EMBEDDING_KEY",
                        "base_url": "https://example.test/v1",
                        "input_price_usd_per_million": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TEST_EMBEDDING_KEY", raising=False)

    report, rows = run_benchmark(
        cases_path=Path("evals/golden.jsonl").resolve(),
        manifest_path=manifest_path,
    )

    assert report["results"]["hosted"]["status"] == "credential_required"
    assert report["results"]["hosted"]["quality_metrics"] is None
    assert rows == []
