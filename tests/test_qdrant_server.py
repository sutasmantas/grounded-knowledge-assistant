from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.access import AccessContext
from app.config import Settings
from app.ingestion import Chunk
from app.service import KnowledgeService
from app.storage import QDRANT_PAYLOAD_INDEX_FIELDS

QDRANT_URL = os.getenv("ATLAS_TEST_QDRANT_URL", "")
requires_qdrant_server = pytest.mark.skipif(
    not QDRANT_URL,
    reason="Set ATLAS_TEST_QDRANT_URL to run the external-Qdrant gate.",
)


@requires_qdrant_server
def test_server_mode_indexes_lifecycle_acl_and_restart(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        qdrant_mode="server",
        qdrant_url=QDRANT_URL,
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
    )
    owner = AccessContext(tenant_id="acme", principal_id="owner")
    legal_reader = AccessContext(
        tenant_id="acme",
        principal_id="counsel",
        groups=frozenset({"legal"}),
    )
    outsider = AccessContext(tenant_id="acme", principal_id="outsider")
    other_tenant = AccessContext(tenant_id="globex", principal_id="owner")
    source = tmp_path / "routing.md"
    source.write_text(
        "# Routing Policy\nThe restricted routing desk is Mercury.",
        encoding="utf-8",
    )

    service = KnowledgeService(settings)
    try:
        assert QDRANT_PAYLOAD_INDEX_FIELDS <= service.store.payload_index_fields()
        original = service.ingest_path(
            source,
            filename="routing.md",
            title="Routing Policy",
            collection="Operations",
            mime_type="text/markdown",
            source_uri="handbook://routing",
            access=owner,
            visibility="restricted",
            allowed_groups=("legal",),
        )
        assert service.query("Which desk is Mercury?", [], 5, access=outsider).sources == []
        assert service.query("Which desk is Mercury?", [], 5, access=other_tenant).sources == []
        assert {
            result.document_id
            for result in service.query(
                "Which desk is Mercury?", [], 5, access=legal_reader
            ).sources
        } == {original.id}

        replacement = service.store.replace_document(
            current=original,
            filename="routing.md",
            title="Routing Policy",
            collection="Operations",
            mime_type="text/markdown",
            size_bytes=57,
            sha256="server-replacement-checksum",
            chunks=[Chunk(page=1, text="The restricted routing desk is Atlas.")],
            source_uri=original.source_uri,
        )
        assert service.store.count_vectors_for_document(original.id) == 0
        assert service.store.count_vectors_for_document(replacement.id) == 1
    finally:
        service.close()

    restarted = KnowledgeService(settings)
    try:
        response = restarted.query(
            "Which desk is Atlas?", [], 5, access=legal_reader
        )
        assert {result.document_id for result in response.sources} == {replacement.id}
        assert all("Mercury" not in result.passage for result in response.sources)
        assert restarted.delete_document(replacement.id, owner) is True
        assert restarted.store.count_vectors_for_document(replacement.id) == 0
    finally:
        restarted.close()
