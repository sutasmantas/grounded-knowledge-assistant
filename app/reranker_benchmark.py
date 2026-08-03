from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, Settings
from app.evaluation import DEFAULT_CASES, evaluate, load_cases
from app.service import KnowledgeService

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "reranker-manifest.json"
RERANKER_CANDIDATES = [
    "none",
    "minilm-cross-encoder",
    "bge-cross-encoder",
    "colbert",
]
WARMUP_QUESTION = "Who approves a commercial exception below 50,000 USD?"
WARMUP_COLLECTIONS = ["Customer contracts"]


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def run_benchmark(
    *,
    cases_path: Path,
    manifest_path: Path,
    candidates: list[str],
    embedding_provider: str,
    embedding_model: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = load_cases(cases_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate_specs = manifest["candidates"]
    results: dict[str, Any] = {}
    raw_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        specification = candidate_specs[candidate]
        retrieval_profile = str(specification["retrieval_profile"])
        reranker_provider = str(specification["provider"] or "lexical")
        reranker_model = str(specification["model"] or "")
        with tempfile.TemporaryDirectory(
            prefix=f"atlas-reranker-{candidate}-"
        ) as temp_dir:
            data_dir = Path(temp_dir)
            service = KnowledgeService(
                Settings(
                    data_dir=data_dir,
                    chunking_profile="fixed",
                    embedding_provider=embedding_provider,  # type: ignore[arg-type]
                    embedding_model=embedding_model,
                    reranker_provider=reranker_provider,  # type: ignore[arg-type]
                    reranker_model=reranker_model,
                    generation_provider="extractive",
                )
            )
            tracemalloc.start()
            try:
                index_started = time.perf_counter()
                service.seed_sample_documents()
                index_build_ms = round((time.perf_counter() - index_started) * 1000)
                documents = service.list_documents()

                warmup_ms = 0
                if candidate != "none":
                    warmup_started = time.perf_counter()
                    service.query(
                        WARMUP_QUESTION,
                        WARMUP_COLLECTIONS,
                        top_k=5,
                        retrieval_profile="hybrid-reranked",
                    )
                    warmup_ms = round((time.perf_counter() - warmup_started) * 1000)

                report, rows = evaluate(service, cases, [retrieval_profile])
                _, peak_memory = tracemalloc.get_traced_memory()
                index_disk_bytes = _directory_size(data_dir)
            finally:
                tracemalloc.stop()
                service.close()

        metrics = report["profiles"][retrieval_profile]
        results[candidate] = {
            "provider": specification["provider"],
            "model": specification["model"],
            "model_artifact_gb": specification["model_artifact_gb"],
            "documents": len(documents),
            "indexed_chunks": sum(document.chunk_count for document in documents),
            "index_build_ms": index_build_ms,
            "index_disk_bytes": index_disk_bytes,
            "warmup_ms": warmup_ms,
            "traced_python_peak_memory_mb": round(
                peak_memory / (1024 * 1024), 2
            ),
            "memory_note": (
                "Python allocator peak; ONNX Runtime native memory is excluded."
            ),
            **metrics,
        }
        raw_rows.extend(
            {"reranker_candidate": candidate, **row} for row in rows
        )

    return (
        {
            "schema_version": "1.0",
            "manifest": manifest,
            "dataset": _display_path(cases_path),
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
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
        description="Compare Atlas rerankers on frozen retrieval cases."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--candidates",
        nargs="+",
        choices=RERANKER_CANDIDATES,
        default=RERANKER_CANDIDATES,
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["hash", "fastembed"],
        default="fastembed",
    )
    parser.add_argument(
        "--embedding-model",
        default="BAAI/bge-small-en-v1.5",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, rows = run_benchmark(
        cases_path=args.cases,
        manifest_path=args.manifest,
        candidates=args.candidates,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
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
