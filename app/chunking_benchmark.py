from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, Settings
from app.evaluation import DEFAULT_CASES, evaluate, load_cases
from app.service import KnowledgeService

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "chunking-manifest.json"
CHUNKING_PROFILES = ["fixed", "heading-aware", "parent-child", "docling-hybrid"]


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def run_benchmark(
    *,
    cases_path: Path,
    manifest_path: Path,
    chunking_profiles: list[str],
    embedding_provider: str,
    retrieval_profile: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = load_cases(cases_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: dict[str, Any] = {}
    raw_rows: list[dict[str, Any]] = []

    for chunking_profile in chunking_profiles:
        with tempfile.TemporaryDirectory(
            prefix=f"atlas-chunk-{chunking_profile}-"
        ) as temp_dir:
            data_dir = Path(temp_dir)
            service = KnowledgeService(
                Settings(
                    data_dir=data_dir,
                    chunking_profile=chunking_profile,  # type: ignore[arg-type]
                    embedding_provider=embedding_provider,
                    reranker_provider="lexical",
                    generation_provider="extractive",
                )
            )
            try:
                started = time.perf_counter()
                service.seed_sample_documents()
                index_build_ms = round((time.perf_counter() - started) * 1000)
                documents = service.list_documents()
                report, rows = evaluate(service, cases, [retrieval_profile])
                index_disk_bytes = _directory_size(data_dir)
            finally:
                service.close()

        metrics = report["profiles"][retrieval_profile]
        results[chunking_profile] = {
            "documents": len(documents),
            "indexed_chunks": sum(document.chunk_count for document in documents),
            "index_build_ms": index_build_ms,
            "index_disk_bytes": index_disk_bytes,
            **metrics,
        }
        raw_rows.extend(
            {"chunking_profile": chunking_profile, **row} for row in rows
        )

    return (
        {
            "schema_version": "1.0",
            "manifest": manifest,
            "dataset": cases_path.relative_to(PROJECT_ROOT).as_posix(),
            "embedding_provider": embedding_provider,
            "retrieval_profile": retrieval_profile,
            "results": results,
        },
        raw_rows,
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Atlas chunking profiles on frozen retrieval cases."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--chunking-profiles",
        nargs="+",
        choices=CHUNKING_PROFILES,
        default=CHUNKING_PROFILES,
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["hash", "fastembed"],
        default="hash",
    )
    parser.add_argument(
        "--retrieval-profile",
        choices=["dense", "sparse", "hybrid", "hybrid-reranked"],
        default="hybrid",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, rows = run_benchmark(
        cases_path=args.cases,
        manifest_path=args.manifest,
        chunking_profiles=args.chunking_profiles,
        embedding_provider=args.embedding_provider,
        retrieval_profile=args.retrieval_profile,
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
