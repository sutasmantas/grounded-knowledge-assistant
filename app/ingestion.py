from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


@dataclass(frozen=True)
class PageText:
    page: int | None
    text: str


@dataclass(frozen=True)
class Chunk:
    page: int | None
    text: str
    index_text: str | None = None
    context_id: str | None = None


def extract_pages(path: Path) -> list[PageText]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Supported document types are PDF, Markdown and plain text.")
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pages = [
            PageText(page=index, text=(page.extract_text() or "").strip())
            for index, page in enumerate(reader.pages, start=1)
        ]
    else:
        text = path.read_text(encoding="utf-8")
        pages = [PageText(page=1, text=text.strip())]
    pages = [page for page in pages if page.text]
    if not pages:
        raise ValueError("No readable text was found in the document.")
    return pages


# Lines whose whitespace carries meaning and must survive chunking byte-for-byte: table rows,
# fenced code, and indented code blocks. Everything else is prose, where runs of spaces are
# noise from the extractor.
_STRUCTURED_LINE = re.compile(r"^(?:\s*\|| {0,3}(?:```|~~~)|[ \t]{4,}\S)")


def _normalise(text: str) -> str:
    """Collapse whitespace inside prose lines while preserving line structure.

    This used to be `re.sub(r"\\s+", " ", text)`, which flattened the whole document into one
    line. That is harmless for prose and destructive for anything whose layout is its meaning:

    * A markdown table became a single run of `| a | b | c |` with no row boundaries, so a
      retrieved chunk could not be rendered or read back as a table.
    * Python indentation disappeared, so a returned function was not merely reformatted but
      syntactically invalid, and a reader could not tell which lines were inside a loop.

    Measured on the toolbox's Track I instruments before this change: 0.000 indentation
    survival on code and 0.333 header co-retrieval on tables for every profile built on this
    function, against 1.000 and 0.833 for `docling-hybrid`, which is the one profile that does
    not use it. The gap was this single line.
    """
    lines: list[str] = []
    for line in text.splitlines():
        if _STRUCTURED_LINE.match(line):
            lines.append(line.rstrip())
        else:
            lines.append(re.sub(r"[ \t]+", " ", line).strip())

    # One blank line is a paragraph break worth keeping; more than one carries no information.
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip("\n")


def _windows(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = _normalise(text)
    windows: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        if end < len(normalized):
            # A line boundary is preferred over a word boundary, so a table row or a line of
            # code is split across chunks only when it cannot be avoided.
            boundary = normalized.rfind("\n", start + chunk_size // 2, end)
            if boundary <= start:
                boundary = normalized.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        window = normalized[start:end].strip()
        if window:
            windows.append(window)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return windows


def _markdown_sections(text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            if body or heading:
                sections.append((heading, "\n".join(body).strip()))
            heading = match.group(1).strip()
            body = []
        else:
            body.append(line)
    if body or heading:
        sections.append((heading, "\n".join(body).strip()))
    return [(section_heading, body) for section_heading, body in sections if body]


def _fixed_chunks(
    pages: list[PageText], chunk_size: int, overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        chunks.extend(
            Chunk(page=page.page, text=text)
            for text in _windows(page.text, chunk_size, overlap)
        )
    return chunks


def _heading_chunks(
    pages: list[PageText], chunk_size: int, overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in pages:
        sections = _markdown_sections(page.text)
        if not sections or not any(heading for heading, _ in sections):
            chunks.extend(_fixed_chunks([page], chunk_size, overlap))
            continue
        for heading, body in sections:
            prefix = f"{heading}\n" if heading else ""
            body_size = max(120, chunk_size - len(prefix))
            for window in _windows(body, body_size, overlap):
                chunks.append(Chunk(page=page.page, text=f"{prefix}{window}".strip()))
    return chunks


def _parent_child_chunks(
    pages: list[PageText], chunk_size: int, overlap: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    child_size = max(240, chunk_size // 2)
    child_overlap = min(overlap, child_size // 3)
    parent_size = min(2400, chunk_size * 2)
    for page in pages:
        sections = _markdown_sections(page.text)
        if not sections:
            sections = [(None, page.text)]
        parent_index = 0
        for heading, body in sections:
            prefix = f"{heading}\n" if heading else ""
            for parent_body in _windows(body, max(300, parent_size - len(prefix)), 0):
                parent_text = f"{prefix}{parent_body}".strip()
                context_id = f"{page.page or 0}:{parent_index}"
                parent_index += 1
                for child in _windows(parent_text, child_size, child_overlap):
                    chunks.append(
                        Chunk(
                            page=page.page,
                            text=parent_text,
                            index_text=child,
                            context_id=context_id,
                        )
                    )
    return chunks


def _docling_hybrid_chunks(pages: list[PageText]) -> list[Chunk]:
    try:
        from docling.chunking import HybridChunker
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter
        from docling_core.transforms.chunker.tokenizer.huggingface import (
            HuggingFaceTokenizer,
        )
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Docling hybrid chunking requires the parsing-benchmark extra."
        ) from exc

    embedding_model = "BAAI/bge-small-en-v1.5"
    tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(embedding_model),
        max_tokens=512,
    )
    chunker = HybridChunker(tokenizer=tokenizer, merge_peers=True)
    content = "\n\n".join(page.text for page in pages)
    document = DocumentConverter().convert_string(
        content,
        InputFormat.MD,
        name="atlas-document",
    ).document
    page = pages[0].page if len(pages) == 1 else None
    return [
        Chunk(page=page, text=chunker.contextualize(chunk).strip())
        for chunk in chunker.chunk(document)
        if chunk.text.strip()
    ]


def chunk_pages(
    pages: list[PageText],
    chunk_size: int,
    overlap: int,
    profile: str = "fixed",
) -> list[Chunk]:
    if profile == "heading-aware":
        return _heading_chunks(pages, chunk_size, overlap)
    if profile == "parent-child":
        return _parent_child_chunks(pages, chunk_size, overlap)
    if profile == "docling-hybrid":
        return _docling_hybrid_chunks(pages)
    if profile == "fixed":
        return _fixed_chunks(pages, chunk_size, overlap)
    raise ValueError(f"Unsupported chunking profile: {profile}")
