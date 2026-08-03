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
