from __future__ import annotations

import argparse
import json
import os
import platform
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from app.config import PROJECT_ROOT, Settings
from app.evaluation import DEFAULT_CASES, evaluate, load_cases
from app.service import KnowledgeService

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "embedding-manifest.json"


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")


def run_benchmark(
    *,
    cases_path: Path,
    manifest_path: Path,
    candidate_names: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = manifest["candidates"]
    selected = candidate_names or list(candidates)
    unknown = sorted(set(selected) - set(candidates))
    if unknown:
        raise ValueError(f"Unknown embedding candidates: {unknown}")

    cases = load_cases(cases_path)
    results: dict[str, Any] = {}
    raw_rows: list[dict[str, Any]] = []

    for name in selected:
        candidate = candidates[name]
        credential_env = candidate.get("credential_env")
        api_key = os.getenv(credential_env, "") if credential_env else ""
        if candidate["execution"] == "credentialed" and not api_key:
            results[name] = {
                "status": "credential_required",
                "provider": candidate["provider"],
                "model": candidate["model"],
                "dimensions": candidate["dimensions"],
                "credential_env": credential_env,
                "credential_setup": (
                    f"Set {credential_env} in the process environment; do not commit it."
                ),
                "command": (
                    f"python -m app.embedding_benchmark --candidates {name}"
                ),
                "quality_metrics": None,
                "estimated_provider_cost_usd": None,
            }
            continue

        with tempfile.TemporaryDirectory(prefix=f"atlas-embed-{name}-") as temp_dir:
            data_dir = Path(temp_dir)
            process = psutil.Process()
            rss_before_mb = round(process.memory_info().rss / (1024 * 1024), 2)
            tracemalloc.start()
            service: KnowledgeService | None = None
            try:
                started = time.perf_counter()
                service = KnowledgeService(
                    Settings(
                        data_dir=data_dir,
                        embedding_provider=candidate["provider"],
                        embedding_model=candidate["model"],
                        embedding_dimensions=candidate["dimensions"],
                        embedding_base_url=candidate.get("base_url", ""),
                        embedding_api_key=api_key,
                        reranker_provider="lexical",
                        generation_provider="extractive",
                        chunking_profile="fixed",
                    )
                )
                model_load_ms = round((time.perf_counter() - started) * 1000)
                rss_after_model_load_mb = round(
                    process.memory_info().rss / (1024 * 1024),
                    2,
                )
                started = time.perf_counter()
                service.seed_sample_documents()
                index_build_ms = round((time.perf_counter() - started) * 1000)
                report, rows = evaluate(service, cases, ["dense", "hybrid"])
                _, peak_memory = tracemalloc.get_traced_memory()
                input_tokens = int(getattr(service.embedder, "input_tokens", 0))
                indexed_chunks = sum(
                    document.chunk_count for document in service.list_documents()
                )
                index_disk_bytes = _directory_size(data_dir)
                rss_after_evaluation_mb = round(
                    process.memory_info().rss / (1024 * 1024),
                    2,
                )
            finally:
                tracemalloc.stop()
                if service is not None:
                    service.close()

        price = float(candidate["input_price_usd_per_million"])
        results[name] = {
            "status": "completed",
            "provider": candidate["provider"],
            "model": candidate["model"],
            "dimensions": candidate["dimensions"],
            "model_load_ms": model_load_ms,
            "index_build_ms": index_build_ms,
            "indexed_chunks": indexed_chunks,
            "index_disk_bytes": index_disk_bytes,
            "traced_python_peak_memory_mb": round(peak_memory / (1024 * 1024), 2),
            "memory_note": "Python allocator peak; native model/runtime memory is excluded.",
            "rss_before_mb": rss_before_mb,
            "rss_after_model_load_mb": rss_after_model_load_mb,
            "rss_after_evaluation_mb": rss_after_evaluation_mb,
            "rss_note": (
                "Resident-set snapshots include the Python runtime and shared native "
                "allocations; compare directionally on the recorded machine."
            ),
            "input_tokens": input_tokens,
            "estimated_provider_cost_usd": round(
                input_tokens * price / 1_000_000,
                8,
            ),
            "quality_metrics": report["profiles"],
        }
        raw_rows.extend({"embedding_candidate": name, **row} for row in rows)

    return (
        {
            "schema_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "manifest": manifest,
            "dataset": cases_path.relative_to(PROJECT_ROOT).as_posix(),
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "results": results,
        },
        raw_rows,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Atlas embedding models.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--candidates", nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, rows = run_benchmark(
        cases_path=args.cases,
        manifest_path=args.manifest,
        candidate_names=args.candidates,
    )
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.raw_output:
        _write_jsonl(args.raw_output, rows)
    print(rendered)


if __name__ == "__main__":
    main()
