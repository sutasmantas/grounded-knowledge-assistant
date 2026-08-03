from __future__ import annotations

from app.config import PROJECT_ROOT
from app.parsing_benchmark import PARSERS, ParseResult, load_manifest, run_benchmark


def test_parsing_fixture_manifest_is_complete() -> None:
    manifest_path = PROJECT_ROOT / "evals" / "parsing" / "manifest.json"
    manifest = load_manifest(manifest_path)

    assert len(manifest["fixtures"]) == 7
    for fixture in manifest["fixtures"]:
        assert (manifest_path.parent / fixture["source"]).is_file()
        assert (manifest_path.parent / fixture["reference"]).is_file()
        assert len(fixture["anchors"]) >= 3


def test_pypdf_parser_benchmark_produces_inspectable_metrics(tmp_path) -> None:
    report = run_benchmark(
        PROJECT_ROOT / "evals" / "parsing" / "manifest.json",
        ["pypdf"],
        {"code_and_formula"},
        tmp_path / "artifacts",
    )

    assert report["summary"]["pypdf"]["successful_fixtures"] == 1
    result = report["results"][0]
    assert result["status"] == "ok"
    assert result["anchor_recall"] >= 0.75
    assert result["token_recall"] > 0.5
    assert result["processing_ms"] >= 0
    assert (tmp_path / "artifacts" / "pypdf" / "code_and_formula.md").is_file()


def test_empty_parser_output_is_a_failed_fixture(monkeypatch) -> None:
    class EmptyParser:
        name = "empty"

        @staticmethod
        def supports(document_class: str) -> bool:
            return True

        @staticmethod
        def version() -> str:
            return "test"

        @staticmethod
        def parse(path) -> ParseResult:
            return ParseResult(markdown="", pages=1)

    monkeypatch.setitem(PARSERS, "empty", EmptyParser)
    report = run_benchmark(
        PROJECT_ROOT / "evals" / "parsing" / "manifest.json",
        ["empty"],
        {"ocr_test"},
    )

    assert report["summary"]["empty"]["successful_fixtures"] == 0
    assert report["summary"]["empty"]["failed_fixtures"] == 1
    assert report["results"][0]["status"] == "error"
    assert "no readable content" in report["results"][0]["error"]
