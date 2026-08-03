from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import tempfile
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, Settings
from app.service import KnowledgeService

DEFAULT_CASES = PROJECT_ROOT / "evals" / "golden.jsonl"
DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "experiment-manifest.json"
DEFAULT_RERANKER_MODELS = {
    "lexical": "",
    "cross-encoder": "BAAI/bge-reranker-base",
    "colbert": "answerdotai/answerai-colbert-small-v1",
}
VALID_SPLITS = {"development", "held_out"}
VALID_CATEGORIES = {
    "exact",
    "paraphrase",
    "multi_document",
    "boundary",
    "unanswerable",
    "collection_filter",
    "table",
    "stale_version",
    "prompt_injection",
    "tenant_isolation",
}


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    split: str
    category: str
    question: str
    expected_titles: list[str]
    collections: list[str]
    should_answer: bool
    enabled: bool = True
    skip_reason: str | None = None


def _validate_case(case: EvaluationCase, line_number: int) -> None:
    prefix = f"Case {case.id!r} on line {line_number}"
    if not case.id.strip():
        raise ValueError(f"{prefix} has an empty id")
    if case.split not in VALID_SPLITS:
        raise ValueError(f"{prefix} has invalid split {case.split!r}")
    if case.category not in VALID_CATEGORIES:
        raise ValueError(f"{prefix} has invalid category {case.category!r}")
    if len(case.question.strip()) < 3:
        raise ValueError(f"{prefix} has an invalid question")
    if case.enabled and case.should_answer and not case.expected_titles:
        raise ValueError(f"{prefix} must name at least one expected title")
    if not case.enabled and not case.skip_reason:
        raise ValueError(f"{prefix} must explain why it is capability-gated")


def load_cases(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        case = EvaluationCase(**json.loads(line))
        _validate_case(case, line_number)
        if case.id in seen:
            raise ValueError(f"Duplicate evaluation case id: {case.id}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError(f"No evaluation cases found in {path}")
    return cases


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    answerable = [row for row in rows if row["should_answer"]]
    unanswerable = [row for row in rows if not row["should_answer"]]
    retrieval_latencies = [int(row["retrieval_ms"]) for row in rows]
    total_latencies = [int(row["latency_ms"]) for row in rows]
    return {
        "cases": len(rows),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "mrr_at_5": _mean([float(row["reciprocal_rank"]) for row in answerable]),
        "recall_at_5": _mean([float(row["recall_at_5"]) for row in answerable]),
        "ndcg_at_5": _mean([float(row["ndcg_at_5"]) for row in answerable]),
        "no_answer_accuracy": _mean(
            [float(row["answer_correct"]) for row in unanswerable]
        ),
        "p50_retrieval_ms": round(statistics.median(retrieval_latencies))
        if retrieval_latencies
        else 0,
        "p95_retrieval_ms": _percentile(retrieval_latencies, 0.95),
        "p50_total_ms": round(statistics.median(total_latencies))
        if total_latencies
        else 0,
        "p95_total_ms": _percentile(total_latencies, 0.95),
    }


def _group_metrics(
    rows: list[dict[str, Any]], key: str
) -> dict[str, dict[str, float | int]]:
    values = sorted({str(row[key]) for row in rows})
    return {
        value: _aggregate([row for row in rows if row[key] == value])
        for value in values
    }


def _ndcg_at_5(titles: list[str], expected_titles: list[str]) -> float:
    expected = set(expected_titles)
    credited: set[str] = set()
    dcg = 0.0
    for rank, title in enumerate(titles[:5], start=1):
        if title in expected and title not in credited:
            dcg += 1 / math.log2(rank + 1)
            credited.add(title)
    ideal_hits = min(len(expected), 5)
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def evaluate(
    service: KnowledgeService,
    cases: list[EvaluationCase],
    profiles: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    enabled_cases = [case for case in cases if case.enabled]
    gated_cases = [case for case in cases if not case.enabled]
    rows: list[dict[str, Any]] = []
    profile_metrics: dict[str, Any] = {}

    for profile in profiles:
        profile_rows: list[dict[str, Any]] = []
        for case in enabled_cases:
            response = service.query(
                case.question,
                case.collections,
                top_k=5,
                retrieval_profile=profile,  # type: ignore[arg-type]
            )
            titles = [source.title for source in response.sources]
            expected = set(case.expected_titles)
            relevant_ranks = [
                rank
                for rank, title in enumerate(titles, start=1)
                if title in expected
            ]
            reciprocal_rank = (
                1 / min(relevant_ranks) if case.should_answer and relevant_ranks else 0.0
            )
            recall = (
                len(set(titles) & expected) / len(expected)
                if case.should_answer and expected
                else 0.0
            )
            answer_correct = (
                bool(response.sources)
                if case.should_answer
                else not bool(response.sources)
            )
            row = {
                "profile": profile,
                "case_id": case.id,
                "split": case.split,
                "category": case.category,
                "question": case.question,
                "collections": case.collections,
                "should_answer": case.should_answer,
                "expected_titles": case.expected_titles,
                "retrieved_titles": titles,
                "relevant_ranks": relevant_ranks,
                "reciprocal_rank": round(reciprocal_rank, 4),
                "recall_at_5": round(recall, 4),
                "ndcg_at_5": round(
                    _ndcg_at_5(titles, case.expected_titles)
                    if case.should_answer
                    else 0.0,
                    4,
                ),
                "answer_correct": answer_correct,
                "retrieval_ms": response.retrieval.retrieval_ms
                + response.retrieval.rerank_ms,
                "latency_ms": response.latency_ms,
                "candidates_considered": response.retrieval.candidates_considered,
                "fusion": response.retrieval.fusion,
                "reranker": response.retrieval.reranker,
            }
            profile_rows.append(row)
            rows.append(row)

        profile_metrics[profile] = {
            "overall": _aggregate(profile_rows),
            "by_split": _group_metrics(profile_rows, "split"),
            "by_category": _group_metrics(profile_rows, "category"),
        }

    gated_by_category = Counter(case.category for case in gated_cases)
    report = {
        "schema_version": "2.0",
        "case_inventory": {
            "total": len(cases),
            "runnable": len(enabled_cases),
            "capability_gated": len(gated_cases),
            "development": sum(case.split == "development" for case in cases),
            "held_out": sum(case.split == "held_out" for case in cases),
            "gated_by_category": dict(sorted(gated_by_category.items())),
            "gated_cases": [
                {
                    "id": case.id,
                    "split": case.split,
                    "category": case.category,
                    "skip_reason": case.skip_reason,
                }
                for case in gated_cases
            ],
        },
        "profiles": profile_metrics,
    }
    return report, rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _runtime_metadata(
    args: argparse.Namespace,
    *,
    index_build_ms: int,
    python_peak_memory_mb: float,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": _display_path(args.cases),
        "dataset_sha256": _sha256(args.cases),
        "manifest": _display_path(args.manifest),
        "manifest_sha256": _sha256(args.manifest),
        "profiles": args.profiles,
        "embedding_provider": args.embedding_provider,
        "reranker_provider": args.reranker_provider,
        "reranker_model": args.reranker_model,
        "generation_provider": "extractive",
        "estimated_provider_cost_usd": 0.0,
        "cost_note": "Local deterministic or local model execution; hosted API cost is zero.",
        "index_build_ms": index_build_ms,
        "traced_python_peak_memory_mb": round(python_peak_memory_mb, 2),
        "memory_note": "Python allocator peak; native model/runtime memory is excluded.",
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Atlas retrieval profiles.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=["dense", "sparse", "hybrid", "hybrid-reranked"],
        default=["dense", "hybrid"],
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["hash", "fastembed"],
        default="hash",
    )
    parser.add_argument(
        "--reranker-provider",
        choices=["lexical", "cross-encoder", "colbert"],
        default="lexical",
    )
    parser.add_argument(
        "--reranker-model",
        help="Override the provider's default reranker model.",
    )
    parser.add_argument(
        "--split",
        choices=["all", "development", "held_out"],
        default="all",
        help="Run all cases or a frozen evaluation split.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.reranker_model = (
        args.reranker_model or DEFAULT_RERANKER_MODELS[args.reranker_provider]
    )
    cases = load_cases(args.cases)
    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]

    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="atlas-eval-") as temp_dir:
        service: KnowledgeService | None = None
        try:
            service = KnowledgeService(
                Settings(
                    data_dir=Path(temp_dir),
                    embedding_provider=args.embedding_provider,
                    reranker_provider=args.reranker_provider,
                    reranker_model=args.reranker_model,
                    generation_provider="extractive",
                )
            )
            started = time.perf_counter()
            service.seed_sample_documents()
            index_build_ms = round((time.perf_counter() - started) * 1000)
            report, rows = evaluate(service, cases, args.profiles)
            _, peak_memory = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            if service is not None:
                service.close()

    report["run"] = _runtime_metadata(
        args,
        index_build_ms=index_build_ms,
        python_peak_memory_mb=peak_memory / (1024 * 1024),
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
