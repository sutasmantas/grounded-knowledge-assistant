from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.access import AccessContext
from app.config import Settings
from app.connectors.base import ConnectorSecurityError
from app.schemas import LocalFolderSyncRequest
from app.service import KnowledgeService, UnknownConnectorRootError

TENANT_A = AccessContext(tenant_id="tenant-a", principal_id="alice")
TENANT_B = AccessContext(tenant_id="tenant-b", principal_id="bob")


def build_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        sample_documents_dir=tmp_path / "no-samples",
        embedding_provider="hash",
        generation_provider="extractive",
        ingestion_worker_enabled=False,
        connector_local_roots={"handbook": tmp_path / "handbook"},
        **overrides,
    )


@pytest.fixture
def handbook(tmp_path: Path) -> Path:
    root = tmp_path / "handbook"
    root.mkdir()
    (root / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Mercury.",
        encoding="utf-8",
    )
    (root / "retention.md").write_text(
        "# Retention Policy\n\nThe retention owner is the Records desk.",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def service(tmp_path: Path, handbook: Path) -> Iterator[KnowledgeService]:
    instance = KnowledgeService(build_settings(tmp_path))
    try:
        yield instance
    finally:
        instance.close()


def sync(
    service: KnowledgeService,
    *,
    access: AccessContext = TENANT_A,
    subpath: str = "",
    collection: str = "Operations",
    visibility: str = "tenant",
    allowed_groups: tuple[str, ...] = (),
):
    request = LocalFolderSyncRequest(
        root="handbook",
        subpath=subpath,
        collection=collection,
        visibility=visibility,
        allowed_groups=list(allowed_groups),
    )
    connector = service.build_local_folder_connector(request)
    return service.run_connector_sync(
        connector,
        collection=collection,
        access=access,
        visibility=visibility,
        allowed_groups=allowed_groups,
    )


def test_initial_sync_indexes_every_supported_document(
    service: KnowledgeService,
) -> None:
    report = sync(service)

    assert (report.discovered, report.created, report.updated) == (2, 2, 0)
    assert report.unchanged == report.removed == report.failed == 0
    documents = service.list_documents(TENANT_A)
    assert {document.source_uri for document in documents} == {
        "local://handbook/routing.md",
        "local://handbook/retention.md",
    }
    assert {document.version for document in documents} == {1}
    assert all(
        document.connector_name == "local-folder" for document in documents
    )

    answer = service.query("Which desk owns incident routing?", [], 5, access=TENANT_A)
    assert "Mercury" in " ".join(source.passage for source in answer.sources)
    assert {source.source_uri for source in answer.sources} <= {
        "local://handbook/routing.md",
        "local://handbook/retention.md",
    }


def test_unchanged_content_is_skipped_without_creating_versions(
    service: KnowledgeService,
) -> None:
    first = sync(service)
    before = {document.source_id: document.id for document in service.list_documents(TENANT_A)}

    second = sync(service)

    assert (second.created, second.updated, second.unchanged) == (0, 0, 2)
    assert second.removed == second.failed == 0
    after = {document.source_id: document.id for document in service.list_documents(TENANT_A)}
    assert after == before
    assert {document.version for document in service.list_documents(TENANT_A)} == {1}
    assert first.discovered == second.discovered


def test_repeated_sync_is_idempotent(service: KnowledgeService) -> None:
    sync(service)
    reports = [sync(service) for _ in range(3)]

    assert [report.model_dump(exclude={"items"}) for report in reports] == [
        reports[0].model_dump(exclude={"items"})
    ] * 3
    assert len(service.list_documents(TENANT_A)) == 2
    assert service.store.all_vector_document_ids() == {
        document.id for document in service.list_documents(TENANT_A)
    }


def test_changed_content_creates_a_new_version_and_retires_stale_vectors(
    service: KnowledgeService,
    handbook: Path,
) -> None:
    sync(service)
    original = next(
        document
        for document in service.list_documents(TENANT_A)
        if document.source_uri.endswith("routing.md")
    )

    (handbook / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Atlas.",
        encoding="utf-8",
    )
    report = sync(service)

    assert (report.created, report.updated, report.unchanged) == (0, 1, 1)
    current = next(
        document
        for document in service.list_documents(TENANT_A)
        if document.source_uri.endswith("routing.md")
    )
    assert current.version == 2
    assert current.source_id == original.source_id
    assert current.supersedes_document_id == original.id
    assert service.store.count_vectors_for_document(original.id) == 0

    versions = service.store.list_document_versions(original.source_id, TENANT_A)
    assert [(version.version, version.status) for version in versions] == [
        (2, "indexed"),
        (1, "superseded"),
    ]

    answer = service.query("Which desk owns incident routing?", [], 5, access=TENANT_A)
    passages = " ".join(source.passage for source in answer.sources)
    assert "Atlas" in passages
    assert "Mercury" not in passages


def test_upstream_deletion_archives_and_removes_every_vector(
    service: KnowledgeService,
    handbook: Path,
) -> None:
    sync(service)
    removed = next(
        document
        for document in service.list_documents(TENANT_A)
        if document.source_uri.endswith("retention.md")
    )

    (handbook / "retention.md").unlink()
    report = sync(service)

    assert (report.discovered, report.removed, report.unchanged) == (1, 1, 1)
    assert [item.action for item in report.items if item.document_id == removed.id] == [
        "archived"
    ]
    assert service.store.count_vectors_for_document(removed.id) == 0
    assert removed.id not in {
        document.id for document in service.list_documents(TENANT_A)
    }
    history = service.store.list_document_versions(removed.source_id, TENANT_A)
    assert [version.status for version in history] == ["archived"]

    answer = service.query("Who is the retention owner?", [], 5, access=TENANT_A)
    assert answer.sources == []


def test_delete_policy_removes_metadata_as_well(
    tmp_path: Path,
    handbook: Path,
) -> None:
    service = KnowledgeService(
        build_settings(tmp_path, connector_deletion_policy="delete")
    )
    try:
        sync(service)
        removed = next(
            document
            for document in service.list_documents(TENANT_A)
            if document.source_uri.endswith("retention.md")
        )
        (handbook / "retention.md").unlink()
        report = sync(service)

        assert report.removed == 1
        assert [item.action for item in report.items if item.document_id == removed.id] == [
            "deleted"
        ]
        assert service.store.list_document_versions(removed.source_id, TENANT_A) == []
        assert service.store.count_vectors_for_document(removed.id) == 0
    finally:
        service.close()


def test_reappearing_source_continues_its_version_sequence(
    service: KnowledgeService,
    handbook: Path,
) -> None:
    sync(service)
    source_id = next(
        document.source_id
        for document in service.list_documents(TENANT_A)
        if document.source_uri.endswith("retention.md")
    )
    (handbook / "retention.md").unlink()
    sync(service)

    (handbook / "retention.md").write_text(
        "# Retention Policy\n\nThe retention owner is the Archive desk.",
        encoding="utf-8",
    )
    report = sync(service)

    assert report.created == 1
    revived = next(
        document
        for document in service.list_documents(TENANT_A)
        if document.source_id == source_id
    )
    assert revived.version == 2
    assert revived.source_id == source_id


def test_no_orphaned_vectors_remain_after_a_full_lifecycle(
    service: KnowledgeService,
    handbook: Path,
) -> None:
    sync(service)
    (handbook / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Atlas.",
        encoding="utf-8",
    )
    sync(service)
    (handbook / "retention.md").unlink()
    sync(service)

    live = {document.id for document in service.list_documents(TENANT_A)}
    assert service.store.all_vector_document_ids() == live


def test_partial_failure_does_not_corrupt_already_indexed_content(
    tmp_path: Path,
    handbook: Path,
) -> None:
    (handbook / "oversized.md").write_text("# Oversized\n" + "x " * 4000, encoding="utf-8")
    service = KnowledgeService(build_settings(tmp_path, connector_max_document_mb=1))
    try:
        service.synchronizer.max_items = 100
        connector = service.build_local_folder_connector(
            LocalFolderSyncRequest(root="handbook", collection="Operations")
        )
        connector.max_bytes = 200
        report = service.run_connector_sync(
            connector,
            collection="Operations",
            access=TENANT_A,
        )

        assert report.discovered == 3
        assert report.failed == 1
        assert report.created == 2
        assert report.removed == 0
        assert [
            item.error_type for item in report.items if item.action == "failed"
        ] == ["ConnectorItemError"]

        # The two healthy documents survived the partial failure.
        assert len(service.list_documents(TENANT_A)) == 2

        # A second run with a workable limit indexes the remaining document and
        # leaves the already indexed ones untouched.
        connector = service.build_local_folder_connector(
            LocalFolderSyncRequest(root="handbook", collection="Operations")
        )
        recovery = service.run_connector_sync(
            connector,
            collection="Operations",
            access=TENANT_A,
        )
        assert (recovery.created, recovery.unchanged, recovery.failed) == (1, 2, 0)
        assert len(service.list_documents(TENANT_A)) == 3
    finally:
        service.close()


def test_one_failing_item_leaves_the_other_documents_indexed(
    service: KnowledgeService,
    handbook: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync(service)
    (handbook / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Atlas.",
        encoding="utf-8",
    )
    (handbook / "escalation.md").write_text(
        "# Escalation\n\nThe escalation owner is Nova.",
        encoding="utf-8",
    )

    original_parse = service.parsers.parse

    def fail_for_routing(request):
        if request.filename == "routing.md":
            raise RuntimeError("simulated parser failure")
        return original_parse(request)

    monkeypatch.setattr(service.parsers, "parse", fail_for_routing)
    report = sync(service)

    assert report.failed == 1
    assert report.created == 1
    assert report.unchanged == 1
    assert report.removed == 0
    surviving = {
        document.source_uri: document.version
        for document in service.list_documents(TENANT_A)
    }
    assert surviving["local://handbook/routing.md"] == 1
    assert surviving["local://handbook/escalation.md"] == 1


def test_unsupported_files_are_not_discovered(
    service: KnowledgeService,
    handbook: Path,
) -> None:
    (handbook / "archive.zip").write_bytes(b"PK\x03\x04")
    (handbook / ".hidden.md").write_text("# Hidden\nSecret.", encoding="utf-8")
    report = sync(service)

    assert report.discovered == 2


def test_unknown_root_is_rejected(service: KnowledgeService) -> None:
    with pytest.raises(UnknownConnectorRootError):
        service.build_local_folder_connector(
            LocalFolderSyncRequest(root="not-configured")
        )


@pytest.mark.parametrize(
    "subpath",
    ["..", "../..", "nested/../..", "/etc", "nested/../../outside"],
)
def test_path_traversal_is_rejected(
    service: KnowledgeService,
    handbook: Path,
    subpath: str,
) -> None:
    (handbook / "nested").mkdir(exist_ok=True)
    with pytest.raises(ConnectorSecurityError):
        service.build_local_folder_connector(
            LocalFolderSyncRequest(root="handbook", subpath=subpath)
        )


def test_symlinked_subpath_outside_the_root_is_rejected(
    service: KnowledgeService,
    handbook: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = handbook / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("This platform does not allow creating symbolic links.")

    with pytest.raises(ConnectorSecurityError):
        service.build_local_folder_connector(
            LocalFolderSyncRequest(root="handbook", subpath="escape")
        )


def test_symlinked_file_inside_the_root_is_never_followed(
    service: KnowledgeService,
    handbook: Path,
    tmp_path: Path,
) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("# Secret\nThe vault code is 1234.", encoding="utf-8")
    link = handbook / "linked.md"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("This platform does not allow creating symbolic links.")

    report = sync(service)

    assert report.discovered == 2
    assert all(
        not item.source_uri.endswith("linked.md") for item in report.items
    )
    answer = service.query("What is the vault code?", [], 5, access=TENANT_A)
    assert answer.sources == []


def test_item_fetch_refuses_a_path_that_leaves_the_root(
    service: KnowledgeService,
) -> None:
    connector = service.build_local_folder_connector(
        LocalFolderSyncRequest(root="handbook")
    )
    item = next(connector.discover())
    escaped = item.__class__(
        source_id=item.source_id,
        source_uri=item.source_uri,
        filename=item.filename,
        title=item.title,
        metadata={"relative_path": "../outside.md"},
    )
    with pytest.raises(ConnectorSecurityError):
        connector.fetch(escaped)


def test_connector_description_never_exposes_the_absolute_root(
    service: KnowledgeService,
    tmp_path: Path,
) -> None:
    connector = service.build_local_folder_connector(
        LocalFolderSyncRequest(root="handbook")
    )
    description = connector.describe()

    assert description["root"] == "handbook"
    assert str(tmp_path) not in " ".join(description.values())
    catalogue = service.available_connectors()
    assert [entry.name for entry in catalogue] == ["local-folder", "url"]
    assert catalogue[0].configured_roots == ["handbook"]


def test_another_tenant_cannot_see_or_replace_synchronized_documents(
    service: KnowledgeService,
) -> None:
    sync(service, access=TENANT_A)

    assert service.list_documents(TENANT_B) == []
    assert service.query("Which desk owns incident routing?", [], 5, access=TENANT_B).sources == []

    report = sync(service, access=TENANT_B)

    assert report.created == 2
    assert len(service.list_documents(TENANT_A)) == 2
    assert len(service.list_documents(TENANT_B)) == 2
    assert {document.id for document in service.list_documents(TENANT_A)}.isdisjoint(
        {document.id for document in service.list_documents(TENANT_B)}
    )


def test_restricted_visibility_is_applied_to_synchronized_documents(
    service: KnowledgeService,
) -> None:
    sync(service, visibility="restricted", allowed_groups=("records",))

    outsider = AccessContext(tenant_id="tenant-a", principal_id="carol")
    member = AccessContext(
        tenant_id="tenant-a",
        principal_id="carol",
        groups=frozenset({"records"}),
    )

    assert service.list_documents(outsider) == []
    assert service.query("Which desk owns incident routing?", [], 5, access=outsider).sources == []
    assert len(service.list_documents(member)) == 2
    assert service.query(
        "Which desk owns incident routing?", [], 5, access=member
    ).sources


def test_a_second_principal_cannot_hijack_another_principals_source(
    service: KnowledgeService,
    handbook: Path,
) -> None:
    sync(service, access=TENANT_A)
    intruder = AccessContext(tenant_id="tenant-a", principal_id="mallory")
    (handbook / "routing.md").write_text(
        "# Routing Policy\n\nThe incident routing desk is Rogue.",
        encoding="utf-8",
    )

    connector = service.build_local_folder_connector(
        LocalFolderSyncRequest(root="handbook", collection="Operations")
    )
    report = service.run_connector_sync(
        connector,
        collection="Operations",
        access=intruder,
    )

    assert report.failed == 2
    assert all(
        item.error_type == "PermissionError"
        for item in report.items
        if item.action == "failed"
    )
    owner_documents = {
        document.source_uri: document.version
        for document in service.list_documents(TENANT_A)
    }
    assert owner_documents["local://handbook/routing.md"] == 1
