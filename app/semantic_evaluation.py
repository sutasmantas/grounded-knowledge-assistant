from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.config import PROJECT_ROOT, Settings
from app.evaluation import DEFAULT_CASES, EvaluationCase, load_cases
from app.generation import NO_ANSWER_TEXT
from app.schemas import QueryResponse, SourceResult
from app.service import KnowledgeService

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "semantic-evaluation-manifest.json"
CITATION_PATTERN = re.compile(r"\[(\d+)]")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+")


class SemanticJudge(Protocol):
    name: str

    def score(self, pairs: list[tuple[str, str]]) -> list[float]: ...


class HHEMJudge:
    name = "local-hhem"

    def __init__(self, model_name: str, revision: str) -> None:
        try:
            from transformers import AutoModelForSequenceClassification
        except ImportError as exc:
            raise RuntimeError(
                'HHEM evaluation requires `pip install -e ".[semantic-eval]"`.'
            ) from exc
        self._model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            revision=revision,
            trust_remote_code=True,
            dtype="auto",
        )

    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        scores = self._model.predict(pairs).detach().cpu().tolist()
        return [round(float(score), 6) for score in scores]


@dataclass(frozen=True)
class CitedStatement:
    text: str
    citations: tuple[int, ...]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _statements(answer: str) -> list[CitedStatement]:
    body = answer.removeprefix("Based on the indexed policies:").strip()
    statements: list[CitedStatement] = []
    for paragraph in (part.strip() for part in body.split("\n\n")):
        claim_lines = [
            line
            for line in paragraph.splitlines()
            if not MARKDOWN_HEADING_PATTERN.match(line)
        ]
        paragraph = "\n".join(claim_lines).strip()
        if not paragraph:
            continue
        citations = tuple(int(rank) for rank in CITATION_PATTERN.findall(paragraph))
        claim = CITATION_PATTERN.sub("", paragraph).strip()
        if claim:
            statements.append(CitedStatement(text=claim, citations=citations))
    return statements


def _source_map(sources: list[SourceResult]) -> dict[int, SourceResult]:
    return {source.rank: source for source in sources}


def _is_no_answer(response: QueryResponse) -> bool:
    return _normalize(response.answer) == _normalize(NO_ANSWER_TEXT)


def _case_record(case: EvaluationCase, response: QueryResponse) -> dict[str, Any]:
    source_by_rank = _source_map(response.sources)
    statements = _statements(response.answer)
    emitted_ranks = [
        rank for statement in statements for rank in statement.citations
    ]
    valid_links = [
        (statement, rank)
        for statement in statements
        for rank in statement.citations
        if rank in source_by_rank
    ]
    exact_links = [
        _normalize(statement.text) in _normalize(source_by_rank[rank].passage)
        for statement, rank in valid_links
    ]

    return {
        "case_id": case.id,
        "split": case.split,
        "category": case.category,
        "should_answer": case.should_answer,
        "answer": response.answer,
        "retrieved_titles": [source.title for source in response.sources],
        "statements": [
            {"text": statement.text, "citations": list(statement.citations)}
            for statement in statements
        ],
        "citation_validity": (
            float(all(rank in source_by_rank for rank in emitted_ranks))
            if emitted_ranks
            else float(not case.should_answer)
        ),
        "citation_completeness": (
            sum(bool(statement.citations) for statement in statements) / len(statements)
            if statements
            else float(not case.should_answer)
        ),
        "exact_citation_support": (
            sum(exact_links) / len(exact_links)
            if exact_links
            else float(not case.should_answer)
        ),
        "no_answer_correct": float(_is_no_answer(response))
        if not case.should_answer
        else None,
        "abstained": _is_no_answer(response),
        "abstention_correct": float(_is_no_answer(response) != case.should_answer),
        "provider": response.generation.provider,
        "latency_ms": response.latency_ms,
        "generation_ms": response.generation.generation_ms,
        "prompt_tokens": response.generation.prompt_tokens,
        "completion_tokens": response.generation.completion_tokens,
        "total_tokens": response.generation.total_tokens,
        "error": None,
        "_valid_links": valid_links,
        "_statements": statements,
        "_source_by_rank": source_by_rank,
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _failed_case_record(case: EvaluationCase, exc: Exception) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "split": case.split,
        "category": case.category,
        "should_answer": case.should_answer,
        "answer": "",
        "retrieved_titles": [],
        "statements": [],
        "citation_validity": 0.0 if case.should_answer else 1.0,
        "citation_completeness": 0.0 if case.should_answer else 1.0,
        "exact_citation_support": 0.0 if case.should_answer else 1.0,
        "no_answer_correct": 0.0 if not case.should_answer else None,
        "abstained": False,
        "abstention_correct": 0.0,
        "provider": "unknown",
        "latency_ms": None,
        "generation_ms": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "error": f"{type(exc).__name__}: {exc}",
        "semantic_citation_support": [],
        "semantic_answer_faithfulness": [],
    }


def aggregate_semantic_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [record for record in records if record["should_answer"]]
    unanswerable = [record for record in records if not record["should_answer"]]
    citation_scores = [
        score
        for record in answerable
        for score in record["semantic_citation_support"]
    ]
    faithfulness_scores = [
        score
        for record in answerable
        for score in record["semantic_answer_faithfulness"]
    ]
    return {
        "cases": len(records),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "failed_cases": sum(bool(record["error"]) for record in records),
        "citation_validity": _mean(
            [record["citation_validity"] for record in answerable]
        ),
        "citation_completeness": _mean(
            [record["citation_completeness"] for record in answerable]
        ),
        "exact_citation_support": _mean(
            [record["exact_citation_support"] for record in answerable]
        ),
        "mean_semantic_citation_support": _mean(citation_scores),
        "mean_semantic_answer_faithfulness": _mean(faithfulness_scores),
        "no_answer_accuracy": _mean(
            [record["no_answer_correct"] for record in unanswerable]
        ),
        "abstention_accuracy": _mean(
            [record["abstention_correct"] for record in records]
        ),
    }


def select_cases(
    cases: list[EvaluationCase],
    *,
    split: str,
    expected_count: int | None,
) -> list[EvaluationCase]:
    selected = [case for case in cases if case.split == split and case.enabled]
    if expected_count is not None and len(selected) != expected_count:
        raise ValueError(
            f"Semantic selection expected {expected_count} cases, found {len(selected)}"
        )
    return selected


def evaluate_semantics(
    *,
    service: KnowledgeService,
    cases: list[EvaluationCase],
    judge: SemanticJudge,
    retrieval_profile: str,
    continue_on_error: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    citation_pairs: list[tuple[str, str]] = []
    citation_targets: list[tuple[int, int]] = []
    faithfulness_pairs: list[tuple[str, str]] = []
    faithfulness_targets: list[tuple[int, int]] = []

    for case in cases:
        try:
            response = service.query(
                case.question,
                case.collections,
                top_k=5,
                retrieval_profile=retrieval_profile,  # type: ignore[arg-type]
            )
        except Exception as exc:
            if not continue_on_error:
                raise
            records.append(_failed_case_record(case, exc))
            continue
        record = _case_record(case, response)
        record_index = len(records)
        record["semantic_citation_support"] = []
        record["semantic_answer_faithfulness"] = []

        for statement, rank in record.pop("_valid_links"):
            citation_targets.append(
                (record_index, len(record["semantic_citation_support"]))
            )
            record["semantic_citation_support"].append(None)
            citation_pairs.append(
                (record["_source_by_rank"][rank].passage, statement.text)
            )

        for statement in record.pop("_statements"):
            cited_passages = [
                record["_source_by_rank"][rank].passage
                for rank in statement.citations
                if rank in record["_source_by_rank"]
            ]
            if cited_passages:
                faithfulness_targets.append(
                    (record_index, len(record["semantic_answer_faithfulness"]))
                )
                record["semantic_answer_faithfulness"].append(None)
                faithfulness_pairs.append(("\n\n".join(cited_passages), statement.text))

        record.pop("_source_by_rank")
        records.append(record)

    for (record_index, score_index), score in zip(
        citation_targets,
        judge.score(citation_pairs),
        strict=True,
    ):
        records[record_index]["semantic_citation_support"][score_index] = score
    for (record_index, score_index), score in zip(
        faithfulness_targets,
        judge.score(faithfulness_pairs),
        strict=True,
    ):
        records[record_index]["semantic_answer_faithfulness"][score_index] = score

    return aggregate_semantic_records(records), records


def run_evaluation(
    *,
    cases_path: Path,
    manifest_path: Path,
    judge: SemanticJudge | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    split = manifest["selection"]["split"]
    cases = select_cases(
        load_cases(cases_path),
        split=split,
        expected_count=manifest["selection"].get("cases"),
    )
    judge = judge or HHEMJudge(
        manifest["semantic_judge"]["model"],
        manifest["semantic_judge"]["model_revision"],
    )

    with tempfile.TemporaryDirectory(prefix="atlas-semantic-eval-") as temp_dir:
        service = KnowledgeService(
            Settings(
                data_dir=Path(temp_dir),
                embedding_provider=manifest["controlled_variables"][
                    "embedding_provider"
                ],
                generation_provider=manifest["controlled_variables"][
                    "generation_provider"
                ],
                chunking_profile=manifest["controlled_variables"]["chunking_profile"],
                reranker_provider="lexical",
            )
        )
        try:
            service.seed_sample_documents()
            started = time.perf_counter()
            aggregate, records = evaluate_semantics(
                service=service,
                cases=cases,
                judge=judge,
                retrieval_profile=manifest["controlled_variables"][
                    "retrieval_profile"
                ],
            )
            evaluation_ms = round((time.perf_counter() - started) * 1000)
        finally:
            service.close()

    controls = manifest["controls"]
    control_scores = judge.score(
        [
            (
                controls["supported"]["premise"],
                controls["supported"]["hypothesis"],
            ),
            (
                controls["unsupported"]["premise"],
                controls["unsupported"]["hypothesis"],
            ),
        ]
    )
    gates = manifest["gate"]
    gate_checks = {
        name: aggregate[name] >= threshold
        for name, threshold in gates.items()
        if name in aggregate
    }
    gate_checks["control_supported_min"] = (
        control_scores[0] >= gates["control_supported_min"]
    )
    gate_checks["control_unsupported_max"] = (
        control_scores[1] <= gates["control_unsupported_max"]
    )
    return (
        {
            "schema_version": "1.0",
            "manifest": manifest,
            "judge": judge.name,
            "evaluation_ms": evaluation_ms,
            "aggregate": aggregate,
            "controls": {
                "supported_score": control_scores[0],
                "unsupported_score": control_scores[1],
            },
            "gate_checks": gate_checks,
            "gate_passed": all(gate_checks.values()),
        },
        records,
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Atlas answer faithfulness and citation correctness."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--raw-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, rows = run_evaluation(
        cases_path=args.cases,
        manifest_path=args.manifest,
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
