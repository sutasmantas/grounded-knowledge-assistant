from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, Settings
from app.evaluation import load_cases
from app.semantic_evaluation import (
    HHEMJudge,
    SemanticJudge,
    aggregate_semantic_records,
    evaluate_semantics,
    select_cases,
)
from app.service import KnowledgeService

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "generation-comparison-manifest.json"
DEFAULT_CASES = PROJECT_ROOT / "evals" / "golden.jsonl"


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def _provider_metrics(
    records: list[dict[str, Any]],
    pricing: dict[str, float],
) -> dict[str, Any]:
    metrics = aggregate_semantic_records(records)
    successful = [record for record in records if not record["error"]]
    generation_ms = [
        int(record["generation_ms"])
        for record in successful
        if record["generation_ms"] is not None
    ]
    total_ms = [
        int(record["latency_ms"])
        for record in successful
        if record["latency_ms"] is not None
    ]
    prompt_tokens = sum(
        int(record["prompt_tokens"] or 0) for record in successful
    )
    completion_tokens = sum(
        int(record["completion_tokens"] or 0) for record in successful
    )
    total_tokens = sum(int(record["total_tokens"] or 0) for record in successful)
    accounted = sum(record["total_tokens"] is not None for record in successful)
    provider_cost_usd = (
        prompt_tokens * float(pricing.get("input_per_million_usd", 0.0))
        + completion_tokens * float(pricing.get("output_per_million_usd", 0.0))
    ) / 1_000_000
    metrics.update(
        {
            "successful_cases": len(successful),
            "production_rejection_cases": sum(
                bool(record["error"])
                or (
                    record["should_answer"]
                    and (
                        record["citation_validity"] < 1.0
                        or record["citation_completeness"] < 1.0
                    )
                )
                or (not record["should_answer"] and not record["abstained"])
                for record in records
            ),
            "token_accounting_coverage": (
                round(accounted / len(successful), 4) if successful else 0.0
            ),
            "prompt_tokens": prompt_tokens if accounted else None,
            "completion_tokens": completion_tokens if accounted else None,
            "total_tokens": total_tokens if accounted else None,
            "estimated_provider_cost_usd": round(provider_cost_usd, 8),
            "p50_generation_ms": (
                round(statistics.median(generation_ms)) if generation_ms else None
            ),
            "p95_generation_ms": _percentile(generation_ms, 0.95),
            "mean_generation_ms": _mean([float(value) for value in generation_ms]),
            "p50_total_ms": round(statistics.median(total_ms)) if total_ms else None,
            "p95_total_ms": _percentile(total_ms, 0.95),
        }
    )
    return metrics


def _by_category(
    records: list[dict[str, Any]],
    pricing: dict[str, float],
) -> dict[str, dict[str, Any]]:
    return {
        category: _provider_metrics(
            [record for record in records if record["category"] == category],
            pricing,
        )
        for category in sorted({str(record["category"]) for record in records})
    }


def _resource_record_complete(resource: dict[str, Any]) -> bool:
    return bool(
        resource.get("container_image_id")
        and float(resource.get("peak_memory_mb") or 0) > 0
        and int(resource.get("model_file_bytes") or 0) > 0
        and resource.get("measurement_command")
    )


def promotion_decision(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    gate: dict[str, Any],
    resource: dict[str, Any],
) -> dict[str, Any]:
    tolerance = float(gate["noninferiority_tolerance"])
    checks: dict[str, bool] = {
        "candidate_completed_every_case": candidate["failed_cases"] == 0,
        "candidate_tokens_measured": candidate["token_accounting_coverage"] == 1.0,
        "candidate_resource_measured": _resource_record_complete(resource),
        "candidate_p95_generation_latency": (
            candidate["p95_generation_ms"] is not None
            and candidate["p95_generation_ms"]
            <= int(gate["max_candidate_p95_generation_ms"])
        ),
    }
    for metric in gate["noninferiority_metrics"]:
        checks[f"noninferior_{metric}"] = (
            float(candidate[metric]) + tolerance >= float(baseline[metric])
        )
    minimum_gain = float(gate["minimum_quality_gain"])
    checks["measurable_quality_gain"] = any(
        float(candidate[metric]) - float(baseline[metric]) >= minimum_gain - 1e-9
        for metric in gate["quality_gain_metrics"]
    )
    promote = all(checks.values())
    return {
        "checks": checks,
        "promote_candidate": promote,
        "selected_default": "candidate" if promote else "baseline",
        "decision": (
            "candidate met every predeclared promotion check"
            if promote
            else "retain extractive default; candidate missed one or more predeclared checks"
        ),
    }


def _provider_settings(
    *,
    temp_dir: Path,
    manifest: dict[str, Any],
    provider: str,
    candidate_base_url: str,
    candidate_model: str,
    candidate_api_key: str,
) -> Settings:
    controlled = manifest["controlled_variables"]
    values: dict[str, Any] = {
        "data_dir": temp_dir,
        "embedding_provider": controlled["embedding_provider"],
        "chunking_profile": controlled["chunking_profile"],
        "reranker_provider": "lexical",
        "generation_provider": provider,
        "llm_max_tokens": int(controlled["max_generation_tokens"]),
        "ingestion_worker_enabled": False,
        # Production keeps citation rejection enabled. The benchmark captures
        # invalid output so its tokens, latency and failure shape become
        # evidence instead of disappearing behind the rejection exception.
        "llm_require_citations": provider != "openai-compatible",
    }
    if provider == "openai-compatible":
        values.update(
            {
                "llm_base_url": candidate_base_url,
                "llm_model": candidate_model,
                "llm_api_key": candidate_api_key,
            }
        )
    return Settings(**values)


def run_comparison(
    *,
    cases_path: Path,
    manifest_path: Path,
    candidate_base_url: str,
    candidate_model: str,
    candidate_api_key: str = "",
    resource_path: Path | None = None,
    judge: SemanticJudge | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = select_cases(
        load_cases(cases_path),
        split=manifest["selection"]["split"],
        expected_count=manifest["selection"]["cases"],
    )
    judge = judge or HHEMJudge(
        manifest["semantic_judge"]["model"],
        manifest["semantic_judge"]["model_revision"],
    )
    resource = (
        json.loads(resource_path.read_text(encoding="utf-8"))
        if resource_path
        else {}
    )
    all_records: list[dict[str, Any]] = []
    providers: dict[str, Any] = {}
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="atlas-generation-eval-") as root:
        for label, provider in (("baseline", "extractive"), ("candidate", "openai-compatible")):
            settings = _provider_settings(
                temp_dir=Path(root) / label,
                manifest=manifest,
                provider=provider,
                candidate_base_url=candidate_base_url,
                candidate_model=candidate_model,
                candidate_api_key=candidate_api_key,
            )
            service = KnowledgeService(settings)
            try:
                service.seed_sample_documents()
                aggregate, records = evaluate_semantics(
                    service=service,
                    cases=cases,
                    judge=judge,
                    retrieval_profile=manifest["controlled_variables"][
                        "retrieval_profile"
                    ],
                    continue_on_error=True,
                )
            finally:
                service.close()
            pricing = manifest["providers"][label]["pricing"]
            metrics = _provider_metrics(records, pricing)
            if any(metrics[key] != value for key, value in aggregate.items()):
                raise AssertionError("Provider metric aggregation drifted")
            for record in records:
                record["provider_label"] = label
            all_records.extend(records)
            providers[label] = {
                "generation_provider": provider,
                "model": "extractive" if label == "baseline" else candidate_model,
                "metrics": metrics,
                "by_category": _by_category(records, pricing),
                "resource": {} if label == "baseline" else resource,
            }

    control_scores = judge.score(
        [
            (
                manifest["controls"][name]["premise"],
                manifest["controls"][name]["hypothesis"],
            )
            for name in ("supported", "unsupported")
        ]
    )
    decision = promotion_decision(
        providers["baseline"]["metrics"],
        providers["candidate"]["metrics"],
        manifest["promotion_gate"],
        resource,
    )
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": manifest,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "evaluation_ms": round((time.perf_counter() - started) * 1000),
        },
        "judge": judge.name,
        "judge_controls": {
            "supported_score": control_scores[0],
            "unsupported_score": control_scores[1],
        },
        "providers": providers,
        "promotion": decision,
    }
    return report, all_records


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Atlas extractive and OpenAI-compatible generation."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--candidate-base-url", required=True)
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--candidate-api-key", default="")
    parser.add_argument("--resource", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, rows = run_comparison(
        cases_path=args.cases,
        manifest_path=args.manifest,
        candidate_base_url=args.candidate_base_url,
        candidate_model=args.candidate_model,
        candidate_api_key=args.candidate_api_key,
        resource_path=args.resource,
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
