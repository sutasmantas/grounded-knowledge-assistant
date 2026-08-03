from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.parsers import (
    DOCX_MEDIA_TYPE,
    DoclingParser,
    EmptyTextLayerError,
    ParseRequest,
    ParserRegistry,
    ParserUnavailableError,
    UnsupportedDocumentError,
    resolve_format,
)

FIXTURES = Path("evals/parsing")

# The quality parser lives in the optional `parsing-benchmark` extra. These
# cases run whenever it is installed, so the shipped Docling adapter is never
# unexecuted code: `.github/workflows/quality-parser.yml` installs the extra.
requires_docling = pytest.mark.skipif(
    not DoclingParser.available(),
    reason='Docling is not installed; run `pip install -e ".[parsing-benchmark]"`.',
)


@pytest.fixture
def registry() -> ParserRegistry:
    return ParserRegistry()


@pytest.fixture
def core_registry(monkeypatch: pytest.MonkeyPatch) -> ParserRegistry:
    """A registry behaving as the core install does, even if Docling is present.

    The fallback and escalation contracts must hold on the bundled dependency
    set, so these cases pin Docling as unavailable rather than changing meaning
    depending on which extras happen to be installed.
    """
    instance = ParserRegistry()
    monkeypatch.setattr(instance._docling, "available", staticmethod(lambda: False))
    return instance


def test_format_resolution_prefers_suffix_then_media_type() -> None:
    assert resolve_format("handbook.md", None) == "markdown"
    assert resolve_format("handbook.pdf", "text/plain") == "pdf"
    assert resolve_format("page", "text/html; charset=utf-8") == "html"
    assert resolve_format("roster.csv", None) == "csv"
    assert resolve_format("notes.docx", None) == "docx"
    assert resolve_format("report.txt", None) == "text"


def test_url_responses_trust_the_declared_content_type() -> None:
    assert resolve_format("index.txt", "text/html", prefer_media_type=True) == "html"
    assert resolve_format("download", "application/pdf", prefer_media_type=True) == "pdf"


def test_unsupported_format_is_rejected_with_an_actionable_message() -> None:
    with pytest.raises(UnsupportedDocumentError, match="Supported document types"):
        resolve_format("archive.zip", "application/zip")


def test_registry_reports_the_formats_it_can_route(registry: ParserRegistry) -> None:
    assert set(registry.supported_formats) == {
        "csv",
        "docx",
        "html",
        "markdown",
        "pdf",
        "text",
    }
    assert ".pdf" in registry.supported_suffixes
    assert "text/csv" in registry.supported_media_types
    assert DOCX_MEDIA_TYPE in registry.supported_media_types


def test_ordinary_text_pdf_stays_on_the_fast_pypdf_route(
    registry: ParserRegistry,
) -> None:
    source = FIXTURES / "sources" / "multi_page.pdf"
    document_format, parser_name = registry.route(
        ParseRequest(content=b"", filename=source.name)
    )
    assert (document_format, parser_name) == ("pdf", "pypdf")

    parsed = registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )
    assert parsed.parser == "pypdf"
    assert parsed.degraded is False
    assert parsed.structure["pages"] > 1
    assert "The Evolution of the Word Processor" in parsed.text


def test_scanned_pdf_is_escalated_and_never_silently_indexed_empty(
    core_registry: ParserRegistry,
) -> None:
    source = FIXTURES / "sources" / "ocr_test.pdf"
    with pytest.raises(UnsupportedDocumentError, match="no usable text layer"):
        core_registry.parse(
            ParseRequest(content=source.read_bytes(), filename=source.name)
        )


def test_scanned_pdf_uses_the_docling_route_when_it_is_available(
    registry: ParserRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubDocling:
        name = "docling"
        calls: list[str] = []

        @staticmethod
        def available() -> bool:
            return True

        def parse(self, request: ParseRequest):
            StubDocling.calls.append(request.filename)
            from app.ingestion import PageText
            from app.parsers import ParsedDocument

            return ParsedDocument(
                pages=[PageText(page=1, text="Recovered scanned text.")],
                parser=self.name,
                document_format="pdf",
                media_type="application/pdf",
                structure={"pages": 1, "characters": 23},
            )

    monkeypatch.setattr(registry, "_docling", StubDocling())
    source = FIXTURES / "sources" / "ocr_test.pdf"
    parsed = registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )
    assert parsed.parser == "docling"
    assert parsed.document_format == "pdf"
    assert "Escalated to Docling" in " ".join(parsed.notes)
    assert StubDocling.calls == ["ocr_test.pdf"]


def test_docx_and_html_prefer_docling_when_installed(
    registry: ParserRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry._docling, "available", staticmethod(lambda: True))
    assert registry.parser_for("docx").name == "docling"
    assert registry.parser_for("html").name == "docling"
    monkeypatch.setattr(registry._docling, "available", staticmethod(lambda: False))
    assert registry.parser_for("docx").name == "docx-fallback"
    assert registry.parser_for("html").name == "html-fallback"


def test_html_fallback_keeps_headings_and_table_rows(
    core_registry: ParserRegistry,
) -> None:
    source = FIXTURES / "sources" / "html_rich_table_cells.html"
    parsed = core_registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )
    assert parsed.parser == "html-fallback"
    assert parsed.degraded is True
    assert parsed.structure["table_rows"] >= 20
    assert "Fulvous Whistling Duck" in parsed.text


def test_docx_fallback_keeps_table_rows(core_registry: ParserRegistry) -> None:
    source = FIXTURES / "sources" / "word_tables.docx"
    parsed = core_registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )
    assert parsed.parser == "docx-fallback"
    assert parsed.degraded is True
    assert parsed.structure["table_rows"] >= 25
    assert "Test with tables" in parsed.text


def test_csv_is_parsed_as_an_addressable_table(registry: ParserRegistry) -> None:
    parsed = registry.parse(
        ParseRequest(
            content=b"owner,team\nAtlas,Operations\nMercury,Support\n",
            filename="roster.csv",
        )
    )
    assert parsed.parser == "csv"
    assert parsed.structure["rows"] == 3
    assert parsed.structure["columns"] == 2
    assert "| owner | team |" in parsed.text
    assert "| Atlas | Operations |" in parsed.text


def test_markdown_title_is_used_as_a_hint(registry: ParserRegistry) -> None:
    parsed = registry.parse(
        ParseRequest(
            content=b"# Routing Policy\n\nThe routing owner is Atlas.",
            filename="routing.md",
        )
    )
    assert parsed.document_format == "markdown"
    assert parsed.title_hint == "Routing Policy"


def test_empty_document_is_rejected(registry: ParserRegistry) -> None:
    with pytest.raises(UnsupportedDocumentError, match="No readable text"):
        registry.parse(ParseRequest(content=b"   \n  ", filename="blank.txt"))


def test_corrupt_docx_container_is_rejected(core_registry: ParserRegistry) -> None:
    with pytest.raises(UnsupportedDocumentError, match="DOCX container"):
        core_registry.parse(
            ParseRequest(content=b"not a zip archive", filename="broken.docx")
        )


def test_docx_without_a_document_part_is_rejected(
    core_registry: ParserRegistry,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/other.xml", "<root/>")
    with pytest.raises(UnsupportedDocumentError, match="DOCX container"):
        core_registry.parse(
            ParseRequest(content=buffer.getvalue(), filename="empty.docx")
        )


def test_a_broken_quality_install_is_an_operator_error_not_a_caller_error(
    registry: ParserRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing native library must not look like a malformed document."""

    class BrokenConverter:
        @staticmethod
        def convert(_stream: object):
            raise ImportError("libxcb.so.1: cannot open shared object file")

    class Stream:
        def __init__(self, name: str, stream: object) -> None:
            del name, stream

    monkeypatch.setattr(
        registry._docling,
        "_load",
        lambda: (BrokenConverter(), Stream),
    )
    monkeypatch.setattr(
        registry._docling, "available", staticmethod(lambda: True)
    )
    with pytest.raises(ParserUnavailableError, match="native dependency"):
        registry.parse(
            ParseRequest(content=b"payload", filename="report.docx")
        )


def test_a_document_the_quality_parser_cannot_read_is_a_caller_error(
    registry: ParserRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingConverter:
        @staticmethod
        def convert(_stream: object):
            raise RuntimeError("conversion failed")

    class Stream:
        def __init__(self, name: str, stream: object) -> None:
            del name, stream

    monkeypatch.setattr(
        registry._docling,
        "_load",
        lambda: (FailingConverter(), Stream),
    )
    monkeypatch.setattr(
        registry._docling, "available", staticmethod(lambda: True)
    )
    with pytest.raises(UnsupportedDocumentError, match="could not read"):
        registry.parse(
            ParseRequest(content=b"payload", filename="report.docx")
        )


def test_pypdf_reports_an_empty_text_layer(registry: ParserRegistry) -> None:
    source = FIXTURES / "sources" / "ocr_test.pdf"
    with pytest.raises(EmptyTextLayerError):
        registry.parser_for("pdf").parse(
            ParseRequest(content=source.read_bytes(), filename=source.name)
        )


@requires_docling
def test_docling_recovers_a_scanned_pdf_through_the_registry(
    registry: ParserRegistry,
) -> None:
    source = FIXTURES / "sources" / "ocr_test.pdf"
    parsed = registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )

    assert parsed.parser == "docling"
    assert parsed.document_format == "pdf"
    assert "Escalated to Docling" in " ".join(parsed.notes)
    for anchor in ("Docling bundles PDF document conversion", "JSON and Markdown"):
        assert anchor.casefold() in parsed.text.casefold()


@requires_docling
def test_docling_preserves_docx_tables_the_fallback_loses(
    registry: ParserRegistry,
) -> None:
    source = FIXTURES / "sources" / "word_tables.docx"
    parsed = registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )

    assert parsed.parser == "docling"
    assert parsed.degraded is False
    # The standard-library fallback recovers 30 of the 34 reference rows.
    assert parsed.structure["table_rows"] >= 34
    assert "Merged Cell 4.4 5.4".casefold() in parsed.text.casefold()


@requires_docling
def test_docling_preserves_structured_html_tables(registry: ParserRegistry) -> None:
    source = FIXTURES / "sources" / "html_rich_table_cells.html"
    parsed = registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )

    assert parsed.parser == "docling"
    assert parsed.degraded is False
    assert parsed.structure["table_rows"] >= 22
    assert "Fulvous Whistling Duck".casefold() in parsed.text.casefold()


@requires_docling
def test_a_corrupt_docx_is_rejected_cleanly_through_the_quality_route(
    registry: ParserRegistry,
) -> None:
    with pytest.raises(UnsupportedDocumentError, match="could not read"):
        registry.parse(
            ParseRequest(content=b"not a zip archive", filename="broken.docx")
        )


@requires_docling
def test_ordinary_text_pdfs_still_avoid_the_quality_route(
    registry: ParserRegistry,
) -> None:
    """Installing Docling must not silently take over the fast PDF path."""
    source = FIXTURES / "sources" / "multi_page.pdf"
    parsed = registry.parse(
        ParseRequest(content=source.read_bytes(), filename=source.name)
    )

    assert parsed.parser == "pypdf"
    assert registry.route(
        ParseRequest(content=b"", filename="handbook.pdf")
    ) == ("pdf", "pypdf")


def test_a_format_parser_can_be_replaced(registry: ParserRegistry) -> None:
    class ShoutingParser:
        name = "shouting"

        def parse(self, request: ParseRequest):
            from app.ingestion import PageText
            from app.parsers import ParsedDocument

            return ParsedDocument(
                pages=[PageText(page=1, text=request.content.decode().upper())],
                parser=self.name,
                document_format="text",
                media_type="text/plain",
            )

    registry.register("text", ShoutingParser())
    parsed = registry.parse(
        ParseRequest(content=b"quiet text", filename="notes.txt")
    )
    assert parsed.parser == "shouting"
    assert parsed.text == "QUIET TEXT"
