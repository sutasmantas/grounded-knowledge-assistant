from __future__ import annotations

import pytest

from app import ingestion
from app.ingestion import Chunk, PageText, chunk_pages


def test_fixed_chunking_splits_long_text() -> None:
    chunks = chunk_pages(
        [PageText(page=3, text="word " * 500)],
        chunk_size=400,
        overlap=50,
        profile="fixed",
    )

    assert len(chunks) > 3
    assert all(chunk.page == 3 for chunk in chunks)
    assert all(chunk.index_text is None for chunk in chunks)


def test_heading_aware_chunks_preserve_section_heading() -> None:
    text = "# Policy\n\n## Refunds\n\n" + ("refund evidence " * 80)
    chunks = chunk_pages(
        [PageText(page=1, text=text)],
        chunk_size=320,
        overlap=40,
        profile="heading-aware",
    )

    refund_chunks = [chunk for chunk in chunks if "refund evidence" in chunk.text]
    assert len(refund_chunks) > 1
    assert all(chunk.text.startswith("Refunds\n") for chunk in refund_chunks)


def test_parent_child_indexes_children_and_returns_parent_context() -> None:
    text = "## Security review\n\n" + ("incident evidence approval " * 25)
    chunks = chunk_pages(
        [PageText(page=2, text=text)],
        chunk_size=400,
        overlap=60,
        profile="parent-child",
    )

    assert len(chunks) > 2
    assert len({chunk.context_id for chunk in chunks}) == 1
    assert len({chunk.text for chunk in chunks}) == 1
    assert all(chunk.index_text for chunk in chunks)
    assert all(len(chunk.index_text or "") < len(chunk.text) for chunk in chunks)


def test_docling_hybrid_profile_routes_to_optional_chunker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [Chunk(page=1, text="contextualized chunk")]
    monkeypatch.setattr(
        ingestion,
        "_docling_hybrid_chunks",
        lambda pages: expected,
    )

    chunks = chunk_pages(
        [PageText(page=1, text="# Policy\n\nEvidence")],
        chunk_size=400,
        overlap=50,
        profile="docling-hybrid",
    )

    assert chunks == expected


def test_unknown_chunking_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported chunking profile"):
        chunk_pages(
            [PageText(page=1, text="policy text")],
            chunk_size=400,
            overlap=50,
            profile="unknown",
        )


def test_fixed_chunking_preserves_table_rows_as_rows() -> None:
    """A markdown table must survive chunking as rows, not as one run of pipes.

    Regression test for the defect Track I measured: `_windows` collapsed every newline, so a
    table arrived as `| a | b || c | d |` with no row boundaries. Header co-retrieval on the
    toolbox instrument was 0.333 for this profile against 0.833 for `docling-hybrid`, the one
    profile that does not go through `_windows`.
    """
    rows = [f"| Region {index} | {index * 11}.37 | {index * 7}.91 |" for index in range(1, 25)]
    text = "\n".join(["| Region | Revenue | Units |", "| --- | --- | --- |", *rows])

    chunks = chunk_pages(
        [PageText(page=1, text=text)],
        chunk_size=400,
        overlap=50,
        profile="fixed",
    )

    recovered = [line for chunk in chunks for line in chunk.text.splitlines()]
    assert "| Region 1 | 11.37 | 7.91 |" in recovered
    assert "| Region 24 | 264.37 | 168.91 |" in recovered

    # A fixed window has to break somewhere, so one partial row per chunk boundary is inherent
    # rather than a defect — that residue is what row integrity measures. What must not happen
    # is rows being run together wholesale: before this fix EVERY row was partial, because the
    # newlines were gone entirely.
    partial = [line for line in recovered if "|" in line
               and not (line.startswith("|") and line.endswith("|"))]
    assert len(partial) <= len(chunks) - 1
    intact = [line for line in recovered if line.startswith("|") and line.endswith("|")]
    assert len(intact) >= 24


def test_fixed_chunking_preserves_code_indentation() -> None:
    """Indentation is syntax in code, so losing it returns invalid Python, not untidy Python."""
    code = "\n".join(
        [
            "def retry(action, attempts=3):",
            "    for attempt in range(attempts):",
            "        try:",
            "            return action()",
            "        except TransientError:",
            "            if attempt == attempts - 1:",
            "                raise",
        ]
    )

    chunks = chunk_pages(
        [PageText(page=1, text=code)],
        chunk_size=400,
        overlap=50,
        profile="fixed",
    )

    body = "\n".join(chunk.text for chunk in chunks)
    assert "    for attempt in range(attempts):" in body
    assert "                raise" in body


def test_prose_whitespace_is_still_collapsed() -> None:
    """The structural fix must not stop prose runs of whitespace being normalised."""
    chunks = chunk_pages(
        [PageText(page=1, text="Refund   evidence\nwas    reviewed   twice.")],
        chunk_size=400,
        overlap=50,
        profile="fixed",
    )

    assert "  " not in chunks[0].text
    assert "Refund evidence" in chunks[0].text
