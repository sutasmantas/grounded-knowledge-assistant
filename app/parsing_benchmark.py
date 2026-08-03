from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.config import PROJECT_ROOT
from app.ingestion import extract_pages

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "parsing" / "manifest.json"
TOKEN_PATTERN = re.compile(r"[\w]+(?:[-'][\w]+)*", re.UNICODE)


@dataclass(frozen=True)
class ParseResult:
    markdown: str
    pages: int | None


class Parser(Protocol):
    name: str

    def parse(self, path: Path) -> ParseResult: ...

    def version(self) -> str: ...

    def supports(self, document_class: str) -> bool: ...


class PyPdfParser:
    name = "pypdf"

    @staticmethod
    def supports(document_class: str) -> bool:
        return True

    def parse(self, path: Path) -> ParseResult:
        pages = extract_pages(path)
        return ParseResult(
            markdown="\n\n".join(page.text for page in pages),
            pages=len(pages),
        )

    def version(self) -> str:
        return importlib.metadata.version("pypdf")


class DoclingParser:
    name = "docling"

    def __init__(self) -> None:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RuntimeError(
                "Docling is not installed. Run `pip install -e \".[parsing-benchmark]\"`."
            ) from exc
        self._converter = DocumentConverter()

    @staticmethod
    def supports(document_class: str) -> bool:
        return True

    def parse(self, path: Path) -> ParseResult:
        result = self._converter.convert(path)
        pages = len(result.document.pages) if result.document.pages else None
        return ParseResult(
            markdown=result.document.export_to_markdown(),
            pages=pages,
        )

    def version(self) -> str:
        return importlib.metadata.version("docling")


class DoclingOcrParser(DoclingParser):
    name = "docling-rapidocr-full-page"

    def __init__(self) -> None:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise RuntimeError(
                "Docling with RapidOCR is not installed. "
                "Run `pip install -e \".[parsing-benchmark]\"`."
            ) from exc
        pipeline_options = PdfPipelineOptions(
            do_ocr=True,
            ocr_options=RapidOcrOptions(
                lang=["english"],
                force_full_page_ocr=True,
            ),
        )
        self._converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            },
        )

    @staticmethod
    def supports(document_class: str) -> bool:
        return document_class == "scanned-pdf"


class UnstructuredFastParser:
    name = "unstructured-fast"

    def __init__(self) -> None:
        try:
            from unstructured.partition.docx import partition_docx
            from unstructured.partition.html import partition_html
            from unstructured.partition.pdf import partition_pdf
        except ImportError as exc:
            raise RuntimeError(
                "Unstructured document support could not load. "
                "Run `pip install -e \".[parsing-benchmark]\"`. "
                f"Underlying import error: {exc}"
            ) from exc
        self._partition_docx = partition_docx
        self._partition_html = partition_html
        self._partition_pdf = partition_pdf

    @staticmethod
    def supports(document_class: str) -> bool:
        return True

    def parse(self, path: Path) -> ParseResult:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            elements = self._partition_pdf(filename=str(path), strategy="fast")
        elif suffix == ".docx":
            elements = self._partition_docx(filename=str(path))
        elif suffix in {".html", ".htm"}:
            elements = self._partition_html(filename=str(path))
        else:
            raise ValueError(f"Unsupported Unstructured fixture type: {suffix}")
        rendered: list[str] = []
        page_numbers: set[int] = set()
        for element in elements:
            text = str(element).strip()
            if not text:
                continue
            category = getattr(element, "category", "")
            if category == "Title":
                rendered.append(f"## {text}")
            else:
                rendered.append(text)
            page_number = getattr(element.metadata, "page_number", None)
            if page_number is not None:
                page_numbers.add(int(page_number))
        return ParseResult(
            markdown="\n\n".join(rendered),
            pages=len(page_numbers) or None,
        )

    def version(self) -> str:
        return importlib.metadata.version("unstructured")


class UnstructuredOcrParser(UnstructuredFastParser):
    name = "unstructured-ocr-only"

    @staticmethod
    def supports(document_class: str) -> bool:
        return document_class == "scanned-pdf"

    def parse(self, path: Path) -> ParseResult:
        elements = self._partition_pdf(filename=str(path), strategy="ocr_only")
        rendered = [str(element).strip() for element in elements if str(element).strip()]
        page_numbers = {
            int(page_number)
            for element in elements
            if (page_number := getattr(element.metadata, "page_number", None)) is not None
        }
        return ParseResult(
            markdown="\n\n".join(rendered),
            pages=len(page_numbers) or None,
        )


class AtlasRegistryParser:
    """The shipped routing table, so the registry is measured on the same fixtures."""

    name = "atlas-registry"

    def __init__(self) -> None:
        from app.parsers import ParserRegistry

        self._registry = ParserRegistry()

    @staticmethod
    def supports(document_class: str) -> bool:
        return True

    def parse(self, path: Path) -> ParseResult:
        from app.parsers import ParseRequest

        parsed = self._registry.parse(
            ParseRequest(content=path.read_bytes(), filename=path.name)
        )
        return ParseResult(
            markdown=parsed.text,
            pages=parsed.structure.get("pages"),
        )

    def version(self) -> str:
        return importlib.metadata.version("atlas-knowledge")


PARSERS: dict[str, type[Parser]] = {
    "atlas-registry": AtlasRegistryParser,
    "pypdf": PyPdfParser,
    "docling": DoclingParser,
    "docling-rapidocr-full-page": DoclingOcrParser,
    "unstructured-fast": UnstructuredFastParser,
    "unstructured-ocr-only": UnstructuredOcrParser,
}


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(text)]


def _overlap_metrics(reference: str, candidate: str) -> dict[str, float]:
    reference_tokens = Counter(_tokens(reference))
    candidate_tokens = Counter(_tokens(candidate))
    overlap = sum((reference_tokens & candidate_tokens).values())
    reference_total = sum(reference_tokens.values())
    candidate_total = sum(candidate_tokens.values())
    precision = overlap / candidate_total if candidate_total else 0.0
    recall = overlap / reference_total if reference_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "token_precision": round(precision, 4),
        "token_recall": round(recall, 4),
        "token_f1": round(f1, 4),
    }


def _structure_metrics(text: str) -> dict[str, int]:
    lines = text.splitlines()
    return {
        "headings": sum(bool(re.match(r"^#{1,6}\s+\S", line)) for line in lines),
        "table_rows": sum(line.strip().startswith("|") for line in lines),
        "code_fences": text.count("```") // 2,
        "characters": len(text),
    }


def _anchor_recall(text: str, anchors: list[str]) -> tuple[float, list[str]]:
    normalized = text.casefold()
    missing = [anchor for anchor in anchors if anchor.casefold() not in normalized]
    score = (len(anchors) - len(missing)) / len(anchors) if anchors else 1.0
    return round(score, 4), missing


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row["status"] == "ok"]
    providers = sorted({str(row["provider"]) for row in rows})
    report: dict[str, Any] = {}
    for provider in providers:
        provider_rows = [
            row for row in successful if str(row["provider"]) == provider
        ]
        latencies = [int(row["processing_ms"]) for row in provider_rows]
        report[provider] = {
            "successful_fixtures": len(provider_rows),
            "failed_fixtures": sum(
                row["provider"] == provider
                and row["status"] not in {"ok", "skipped"}
                for row in rows
            ),
            "skipped_fixtures": sum(
                row["provider"] == provider and row["status"] == "skipped"
                for row in rows
            ),
            "mean_token_f1": round(
                statistics.mean(float(row["token_f1"]) for row in provider_rows), 4
            )
            if provider_rows
            else 0.0,
            "mean_anchor_recall": round(
                statistics.mean(
                    float(row["anchor_recall"]) for row in provider_rows
                ),
                4,
            )
            if provider_rows
            else 0.0,
            "median_processing_ms": round(statistics.median(latencies))
            if latencies
            else 0,
            "total_processing_ms": sum(latencies),
        }
    return report


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    fixture_ids = [fixture["id"] for fixture in manifest["fixtures"]]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise ValueError("Duplicate parsing fixture id")
    return manifest


def run_benchmark(
    manifest_path: Path,
    provider_names: list[str],
    fixture_ids: set[str] | None = None,
    artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    fixture_root = manifest_path.parent
    rows: list[dict[str, Any]] = []

    for provider_name in provider_names:
        parser_class = PARSERS[provider_name]
        try:
            parser = parser_class()
            provider_version = parser.version()
            provider_error = None
        except Exception as exc:  # pragma: no cover - depends on optional installs
            parser = None
            provider_version = "unavailable"
            provider_error = f"{type(exc).__name__}: {exc}"

        for fixture in manifest["fixtures"]:
            if fixture_ids and fixture["id"] not in fixture_ids:
                continue
            row: dict[str, Any] = {
                "provider": provider_name,
                "provider_version": provider_version,
                "fixture_id": fixture["id"],
                "document_class": fixture["document_class"],
            }
            if parser is not None and not parser.supports(fixture["document_class"]):
                row.update(
                    {
                        "status": "skipped",
                        "reason": "Profile is not intended for this document class.",
                    }
                )
                rows.append(row)
                continue
            if parser is None:
                row.update({"status": "unavailable", "error": provider_error})
                rows.append(row)
                continue

            source_path = fixture_root / fixture["source"]
            reference = (fixture_root / fixture["reference"]).read_text(
                encoding="utf-8"
            )
            try:
                started = time.perf_counter()
                result = parser.parse(source_path)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                if not result.markdown.strip():
                    raise ValueError("Parser returned no readable content.")
                anchor_recall, missing_anchors = _anchor_recall(
                    result.markdown, fixture["anchors"]
                )
                row.update(
                    {
                        "status": "ok",
                        "processing_ms": elapsed_ms,
                        "pages": result.pages,
                        "anchor_recall": anchor_recall,
                        "missing_anchors": missing_anchors,
                        "output_sha256": _sha256_text(result.markdown),
                        **_overlap_metrics(reference, result.markdown),
                        **{
                            f"output_{key}": value
                            for key, value in _structure_metrics(
                                result.markdown
                            ).items()
                        },
                        **{
                            f"reference_{key}": value
                            for key, value in _structure_metrics(reference).items()
                        },
                    }
                )
                if artifacts_dir:
                    target = artifacts_dir / provider_name / f"{fixture['id']}.md"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(result.markdown + "\n", encoding="utf-8")
            except Exception as exc:  # pragma: no cover - provider-specific failures
                row.update(
                    {
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            rows.append(row)

    return {
        "schema_version": "1.0",
        "manifest": manifest_path.relative_to(PROJECT_ROOT).as_posix(),
        "upstream": manifest["upstream"],
        "caveat": (
            "Reference Markdown comes from Docling upstream and is representation-biased. "
            "Use anchor recall, failure inspection, structure counts, and latency together."
        ),
        "summary": _aggregate(rows),
        "results": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Atlas document parser candidates.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=sorted(PARSERS),
        default=[
            "pypdf",
            "docling",
            "docling-rapidocr-full-page",
            "unstructured-fast",
            "unstructured-ocr-only",
        ],
    )
    parser.add_argument("--fixtures", nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_benchmark(
        args.manifest,
        args.providers,
        set(args.fixtures) if args.fixtures else None,
        args.artifacts_dir,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
