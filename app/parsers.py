"""Replaceable document parser registry.

The routing follows the measured Phase A1 decisions rather than a single
"best" parser:

* ordinary text PDFs stay on the fast `pypdf` path;
* PDFs whose text layer is effectively empty (scanned or layout-heavy) are
  escalated to Docling, which was the only candidate that recovered every
  anchor on the pinned scanned fixture;
* DOCX and structured HTML are routed to Docling because it preserved the
  pinned table structure that Unstructured flattened;
* Markdown, plain text and CSV keep dependency-free deterministic parsers.

Docling ships in the optional `parsing-benchmark` extra because it pulls a
large model stack. When it is absent, the DOCX and HTML formats fall back to
bounded standard-library readers that are explicitly reported as `degraded`
so a fallback result is never presented as the measured quality route. The
scanned-PDF escalation has no fallback: an empty text layer fails loudly
instead of indexing an empty document.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ElementTree
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol

from pypdf import PdfReader

from app.ingestion import PageText

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

FORMAT_SUFFIXES: dict[str, str] = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".docx": "docx",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".csv": "csv",
}

FORMAT_MEDIA_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "text/plain": "text",
    DOCX_MEDIA_TYPE: "docx",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/csv": "csv",
    "application/csv": "csv",
}

DEFAULT_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "markdown": "text/markdown",
    "text": "text/plain",
    "docx": DOCX_MEDIA_TYPE,
    "html": "text/html",
    "csv": "text/csv",
}

HEADING_LINE = re.compile(r"^#{1,6}\s+\S")
WHITESPACE = re.compile(r"[ \t]+")
BLANK_LINES = re.compile(r"\n{3,}")
DOCX_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SKIPPED_HTML_TAGS = {"script", "style", "noscript", "template", "svg"}


class UnsupportedDocumentError(ValueError):
    """The document format is not covered by the registry."""


class ParserUnavailableError(RuntimeError):
    """The route exists but its parser dependency is not installed."""


@dataclass(frozen=True)
class ParseRequest:
    content: bytes
    filename: str
    media_type: str | None = None
    source_uri: str = ""
    prefer_media_type: bool = False


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[PageText]
    parser: str
    document_format: str
    media_type: str
    structure: dict[str, int] = field(default_factory=dict)
    title_hint: str | None = None
    degraded: bool = False
    notes: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


class DocumentParser(Protocol):
    name: str

    def parse(self, request: ParseRequest) -> ParsedDocument: ...


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def structure_metrics(text: str) -> dict[str, int]:
    lines = text.splitlines()
    return {
        "headings": sum(bool(HEADING_LINE.match(line)) for line in lines),
        "table_rows": sum(line.strip().startswith("|") for line in lines),
        "characters": len(text),
    }


def _pages_from_text(text: str, page: int | None = 1) -> list[PageText]:
    cleaned = BLANK_LINES.sub("\n\n", text).strip()
    if not cleaned:
        raise UnsupportedDocumentError("No readable text was found in the document.")
    return [PageText(page=page, text=cleaned)]


class TextParser:
    """Deterministic reader for Markdown and plain text."""

    name = "text"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        text = decode_text(request.content)
        document_format = "markdown" if _looks_like_markdown(text) else "text"
        return ParsedDocument(
            pages=_pages_from_text(text),
            parser=self.name,
            document_format=document_format,
            media_type=DEFAULT_MEDIA_TYPES[document_format],
            structure=structure_metrics(text),
            title_hint=_markdown_title(text),
        )


def _looks_like_markdown(text: str) -> bool:
    return any(HEADING_LINE.match(line) for line in text.splitlines())


def _markdown_title(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


class PyPdfParser:
    """Fast ordinary-text PDF path kept from the Phase A1 measurement."""

    name = "pypdf"

    def __init__(self, min_characters_per_page: int = 24) -> None:
        self.min_characters_per_page = min_characters_per_page

    def parse(self, request: ParseRequest) -> ParsedDocument:
        pages = self.extract(request.content)
        if not self.has_text_layer(pages):
            raise EmptyTextLayerError(
                "The PDF text layer is empty or unusably sparse."
            )
        text = "\n\n".join(page.text for page in pages)
        return ParsedDocument(
            pages=pages,
            parser=self.name,
            document_format="pdf",
            media_type=DEFAULT_MEDIA_TYPES["pdf"],
            structure={**structure_metrics(text), "pages": len(pages)},
        )

    @staticmethod
    def extract(content: bytes) -> list[PageText]:
        reader = PdfReader(io.BytesIO(content))
        pages = [
            PageText(page=index, text=(page.extract_text() or "").strip())
            for index, page in enumerate(reader.pages, start=1)
        ]
        return [page for page in pages if page.text]

    def has_text_layer(self, pages: list[PageText]) -> bool:
        return any(
            len(WHITESPACE.sub("", page.text)) >= self.min_characters_per_page
            for page in pages
        )


class EmptyTextLayerError(ValueError):
    """pypdf produced no usable text, so the document needs the quality route."""


class DoclingParser:
    """Quality route for scanned/layout PDFs, DOCX and structured HTML."""

    name = "docling"

    def __init__(self) -> None:
        self._converter = None

    @staticmethod
    def available() -> bool:
        try:
            import docling.document_converter  # noqa: F401
        except Exception:
            return False
        return True

    def _load(self):
        try:
            from docling.datamodel.base_models import DocumentStream
            from docling.document_converter import DocumentConverter
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ParserUnavailableError(
                "Docling is required for this document. Install it with "
                '`pip install -e ".[parsing-benchmark]"`.'
            ) from exc
        if self._converter is None:
            self._converter = DocumentConverter()
        return self._converter, DocumentStream

    def parse(self, request: ParseRequest) -> ParsedDocument:
        converter, DocumentStream = self._load()
        stream = DocumentStream(
            name=request.filename or "document",
            stream=io.BytesIO(request.content),
        )
        # Docling raises its own exception types. Translate them so a malformed
        # document is a caller error and a broken installation is an operator
        # error, instead of either surfacing as an unhandled 500.
        try:
            result = converter.convert(stream)
            markdown = result.document.export_to_markdown()
        except (ImportError, OSError) as exc:
            raise ParserUnavailableError(
                "The Docling quality route is installed but a native dependency "
                f"is missing ({exc}). OpenCV needs system libraries such as "
                "libgl1, libglib2.0-0 and libxcb1."
            ) from exc
        except Exception as exc:
            raise UnsupportedDocumentError(
                "The quality parser could not read this document "
                f"({type(exc).__name__})."
            ) from exc
        page_count = len(result.document.pages) if result.document.pages else 1
        document_format = resolve_format(
            request.filename,
            request.media_type,
            prefer_media_type=request.prefer_media_type,
        )
        return ParsedDocument(
            pages=_pages_from_text(markdown),
            parser=self.name,
            document_format=document_format,
            media_type=DEFAULT_MEDIA_TYPES[document_format],
            structure={**structure_metrics(markdown), "pages": page_count},
            title_hint=_markdown_title(markdown),
        )


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.title: str | None = None
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._heading_level = 0
        self._table_depth = 0
        self._row: list[str] | None = None
        self._rows: list[list[str]] = []
        self._list_item = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_HTML_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "br":
            self._flush()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._heading_level = int(tag[1])
        elif tag == "table":
            self._flush()
            self._table_depth += 1
            self._rows = []
        elif tag == "tr" and self._table_depth:
            self._row = []
        elif tag in {"td", "th"} and self._table_depth:
            self._buffer = []
        elif tag == "li":
            self._flush()
            self._list_item = True
        elif tag in {"p", "div", "section", "article", "ul", "ol", "pre"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_HTML_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._heading_level = 0
        elif tag in {"td", "th"} and self._row is not None:
            self._row.append(" ".join("".join(self._buffer).split()))
            self._buffer = []
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            self._table_depth = max(0, self._table_depth - 1)
            self._emit_table()
        elif tag == "li":
            self._flush()
            self._list_item = False
        elif tag in {"p", "div", "section", "article", "ul", "ol", "pre"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title = (self.title or "") + data.strip()
            return
        self._buffer.append(data)

    def _flush(self) -> None:
        if self._row is not None:
            return
        text = " ".join("".join(self._buffer).split())
        self._buffer = []
        if not text:
            return
        if self._heading_level:
            self.blocks.append(f"{'#' * self._heading_level} {text}")
        elif self._list_item:
            self.blocks.append(f"- {text}")
        else:
            self.blocks.append(text)

    def _emit_table(self) -> None:
        rows = [row for row in self._rows if any(cell for cell in row)]
        self._rows = []
        if not rows:
            return
        width = max(len(row) for row in rows)
        rendered = ["| " + " | ".join((row + [""] * width)[:width]) + " |" for row in rows]
        rendered.insert(1, "| " + " | ".join(["---"] * width) + " |")
        self.blocks.append("\n".join(rendered))

    def result(self) -> str:
        self._flush()
        return "\n\n".join(self.blocks)


class HtmlFallbackParser:
    """Standard-library HTML reader used only when Docling is unavailable."""

    name = "html-fallback"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        extractor = _HtmlTextExtractor()
        extractor.feed(decode_text(request.content))
        extractor.close()
        text = extractor.result()
        return ParsedDocument(
            pages=_pages_from_text(text),
            parser=self.name,
            document_format="html",
            media_type=DEFAULT_MEDIA_TYPES["html"],
            structure=structure_metrics(text),
            title_hint=extractor.title or None,
            degraded=True,
            notes=(
                "Docling is not installed; HTML was read with the bounded "
                "standard-library fallback.",
            ),
        )


class DocxFallbackParser:
    """Standard-library DOCX reader used only when Docling is unavailable."""

    name = "docx-fallback"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(request.content)) as archive:
                xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise UnsupportedDocumentError(
                "The DOCX container could not be read."
            ) from exc
        root = ElementTree.fromstring(xml)
        body = root.find(f"{DOCX_NAMESPACE}body")
        blocks: list[str] = []
        for element in list(body) if body is not None else []:
            if element.tag == f"{DOCX_NAMESPACE}p":
                text = _docx_paragraph_text(element)
                if text:
                    blocks.append(text)
            elif element.tag == f"{DOCX_NAMESPACE}tbl":
                table = _docx_table_markdown(element)
                if table:
                    blocks.append(table)
        text = "\n\n".join(blocks)
        return ParsedDocument(
            pages=_pages_from_text(text),
            parser=self.name,
            document_format="docx",
            media_type=DEFAULT_MEDIA_TYPES["docx"],
            structure=structure_metrics(text),
            degraded=True,
            notes=(
                "Docling is not installed; DOCX was read with the bounded "
                "standard-library fallback.",
            ),
        )


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts = [node.text or "" for node in paragraph.iter(f"{DOCX_NAMESPACE}t")]
    return " ".join("".join(parts).split())


def _docx_table_markdown(table: ElementTree.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{DOCX_NAMESPACE}tr"):
        cells = [
            " ".join(
                _docx_paragraph_text(paragraph)
                for paragraph in cell.findall(f"{DOCX_NAMESPACE}p")
            ).strip()
            for cell in row.findall(f"{DOCX_NAMESPACE}tc")
        ]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rendered = ["| " + " | ".join((row + [""] * width)[:width]) + " |" for row in rows]
    rendered.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(rendered)


class CsvParser:
    """Structured CSV reader that keeps rows addressable as a Markdown table."""

    name = "csv"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        raw = decode_text(request.content)
        delimiter = _sniff_delimiter(raw)
        rows = [
            row
            for row in csv.reader(io.StringIO(raw), delimiter=delimiter)
            if any(cell.strip() for cell in row)
        ]
        if not rows:
            raise UnsupportedDocumentError("The CSV file contains no rows.")
        width = max(len(row) for row in rows)
        rendered = [
            "| "
            + " | ".join(
                cell.replace("|", "\\|").strip()
                for cell in (row + [""] * width)[:width]
            )
            + " |"
            for row in rows
        ]
        rendered.insert(1, "| " + " | ".join(["---"] * width) + " |")
        text = "\n".join(rendered)
        return ParsedDocument(
            pages=_pages_from_text(text),
            parser=self.name,
            document_format="csv",
            media_type=DEFAULT_MEDIA_TYPES["csv"],
            structure={**structure_metrics(text), "rows": len(rows), "columns": width},
        )


def _sniff_delimiter(raw: str) -> str:
    sample = raw[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def resolve_format(
    filename: str,
    media_type: str | None,
    *,
    prefer_media_type: bool = False,
) -> str:
    normalized_media = (media_type or "").split(";")[0].strip().lower()
    suffix = ""
    if "." in filename:
        suffix = f".{filename.rsplit('.', 1)[1].lower()}"
    from_media = FORMAT_MEDIA_TYPES.get(normalized_media)
    from_suffix = FORMAT_SUFFIXES.get(suffix)
    resolved = (
        (from_media or from_suffix)
        if prefer_media_type
        else (from_suffix or from_media)
    )
    if resolved is None:
        raise UnsupportedDocumentError(
            "Supported document types are PDF, Markdown, plain text, DOCX, "
            f"HTML and CSV. Received filename '{filename}' with content type "
            f"'{normalized_media or 'unknown'}'."
        )
    return resolved


class ParserRegistry:
    """Format-to-parser routing table with replaceable entries."""

    def __init__(self, *, pdf_min_characters_per_page: int = 24) -> None:
        self._docling = DoclingParser()
        self._pypdf = PyPdfParser(pdf_min_characters_per_page)
        self._text = TextParser()
        self._csv = CsvParser()
        self._html_fallback = HtmlFallbackParser()
        self._docx_fallback = DocxFallbackParser()
        self._parsers: dict[str, DocumentParser] = {}
        self.register("markdown", self._text)
        self.register("text", self._text)
        self.register("csv", self._csv)
        self.register("pdf", self._pypdf)
        self.register("docx", self._docx_fallback)
        self.register("html", self._html_fallback)

    def register(self, document_format: str, parser: DocumentParser) -> None:
        """Replace the parser used for one format."""
        self._parsers[document_format] = parser

    def parser_for(self, document_format: str) -> DocumentParser:
        if document_format in {"docx", "html"} and self._docling.available():
            return self._docling
        try:
            return self._parsers[document_format]
        except KeyError as exc:
            raise UnsupportedDocumentError(
                f"No parser is registered for '{document_format}'."
            ) from exc

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return tuple(sorted(self._parsers))

    @property
    def supported_suffixes(self) -> frozenset[str]:
        return frozenset(
            suffix
            for suffix, document_format in FORMAT_SUFFIXES.items()
            if document_format in self._parsers
        )

    @property
    def supported_media_types(self) -> frozenset[str]:
        return frozenset(
            media_type
            for media_type, document_format in FORMAT_MEDIA_TYPES.items()
            if document_format in self._parsers
        )

    def route(self, request: ParseRequest) -> tuple[str, str]:
        """Return the format and the parser name that would be used."""
        document_format = resolve_format(
            request.filename,
            request.media_type,
            prefer_media_type=request.prefer_media_type,
        )
        return document_format, self.parser_for(document_format).name

    def parse(self, request: ParseRequest) -> ParsedDocument:
        document_format = resolve_format(
            request.filename,
            request.media_type,
            prefer_media_type=request.prefer_media_type,
        )
        if document_format == "pdf":
            return self._parse_pdf(request)
        return self.parser_for(document_format).parse(request)

    def _parse_pdf(self, request: ParseRequest) -> ParsedDocument:
        parser = self._parsers["pdf"]
        try:
            return parser.parse(request)
        except EmptyTextLayerError as exc:
            if not self._docling.available():
                raise UnsupportedDocumentError(
                    "This PDF has no usable text layer. Scanned or "
                    "layout-heavy PDFs need the Docling quality route: "
                    'install it with `pip install -e ".[parsing-benchmark]"`.'
                ) from exc
            parsed = self._docling.parse(request)
            return ParsedDocument(
                pages=parsed.pages,
                parser=parsed.parser,
                document_format="pdf",
                media_type=DEFAULT_MEDIA_TYPES["pdf"],
                structure=parsed.structure,
                title_hint=parsed.title_hint,
                degraded=parsed.degraded,
                notes=(
                    *parsed.notes,
                    "Escalated to Docling because the pypdf text layer was empty.",
                ),
            )


DEFAULT_REGISTRY = ParserRegistry()
