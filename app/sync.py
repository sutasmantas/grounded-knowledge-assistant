"""Connector synchronization.

One engine owns the lifecycle rules for every connector:

* identity — the connector supplies a stable source ID and canonical source
  URI; Atlas never invents a second identity for the same upstream item;
* change detection — a SHA-256 checksum of the fetched bytes decides whether
  the item is unchanged, so an unchanged run performs no vector work;
* versioning — changed content creates a new immutable version and the stale
  version's vectors are removed, so a citation can never point at content that
  is no longer indexed;
* disappearance — items that vanish upstream follow the configured deletion
  policy (`archive` keeps the version history but removes every retrieval
  representation, `delete` removes both);
* isolation — every read and write is scoped by tenant, collection and ACL;
* partial failure — a failed item is recorded and the run continues; a failure
  during discovery aborts before the deletion sweep so an unreachable source
  can never mass-archive a healthy index.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from app.access import (
    DEFAULT_ACCESS_CONTEXT,
    AccessContext,
    DocumentVisibility,
    can_manage,
)
from app.connectors.base import (
    Connector,
    ConnectorItemError,
    ConnectorSecurityError,
    DiscoveredItem,
)
from app.ingestion import chunk_pages
from app.observability import TRACER, tenant_hash
from app.parsers import ParseRequest, ParserRegistry, UnsupportedDocumentError
from app.schemas import DeletionPolicy, SyncItemResult, SyncReport
from app.storage import KnowledgeStore

LOGGER = logging.getLogger("atlas.sync")
ProgressCallback = Callable[[int, str], None]

DISCOVERY_PROGRESS = 8
ITEM_PROGRESS_START = 10
ITEM_PROGRESS_END = 85
SWEEP_PROGRESS = 92


class ConnectorSynchronizer:
    def __init__(
        self,
        *,
        store: KnowledgeStore,
        registry: ParserRegistry,
        chunk_size: int,
        chunk_overlap: int,
        chunking_profile: str,
        deletion_policy: DeletionPolicy = "archive",
        max_items: int = 500,
        lock: AbstractContextManager[object] | None = None,
    ) -> None:
        # Fetching and parsing stay outside the lock; only the read-check-write
        # against the index is serialized against concurrent uploads.
        self._lock = lock if lock is not None else nullcontext()
        self.store = store
        self.registry = registry
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunking_profile = chunking_profile
        self.deletion_policy = deletion_policy
        self.max_items = max_items

    def run(
        self,
        connector: Connector,
        *,
        collection: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
        progress: ProgressCallback | None = None,
    ) -> SyncReport:
        report = SyncReport(
            connector=connector.name,
            instance_id=connector.instance_id,
            collection=collection,
            deletion_policy=self.deletion_policy,
        )
        started = time.perf_counter()
        with TRACER.start_as_current_span("atlas.connector.sync") as span:
            span.set_attribute("atlas.connector.name", connector.name)
            span.set_attribute("atlas.tenant_hash", tenant_hash(access.tenant_id))
            self._report(progress, DISCOVERY_PROGRESS, "discovering")
            items = self._discover(connector)
            report.discovered = len(items)
            span.set_attribute("atlas.connector.discovered", len(items))

            for index, item in enumerate(items):
                self._report(
                    progress,
                    _item_progress(index, len(items)),
                    "synchronizing",
                )
                result = self._synchronize_item(
                    connector,
                    item,
                    collection=collection,
                    access=access,
                    visibility=visibility,
                    allowed_principals=allowed_principals,
                    allowed_groups=allowed_groups,
                )
                report.items.append(result)

            self._report(progress, SWEEP_PROGRESS, "reconciling_deletions")
            report.items.extend(
                self._reconcile_deletions(
                    connector,
                    discovered={item.source_id for item in items},
                    access=access,
                )
            )
            _tally(report)
            span.set_attribute("atlas.connector.created", report.created)
            span.set_attribute("atlas.connector.updated", report.updated)
            span.set_attribute("atlas.connector.unchanged", report.unchanged)
            span.set_attribute("atlas.connector.removed", report.removed)
            span.set_attribute("atlas.connector.failed", report.failed)
            LOGGER.info(
                "Connector synchronization completed",
                extra={
                    "event": "connector.sync.completed",
                    "connector": connector.name,
                    "items_discovered": report.discovered,
                    "items_failed": report.failed,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
        return report

    def _discover(self, connector: Connector) -> list[DiscoveredItem]:
        items: list[DiscoveredItem] = []
        seen: set[str] = set()
        for item in connector.discover():
            if item.source_id in seen:
                continue
            seen.add(item.source_id)
            items.append(item)
            if len(items) > self.max_items:
                raise ConnectorItemError(
                    f"The connector discovered more than {self.max_items} items."
                )
        return items

    def _synchronize_item(
        self,
        connector: Connector,
        item: DiscoveredItem,
        *,
        collection: str,
        access: AccessContext,
        visibility: DocumentVisibility,
        allowed_principals: tuple[str, ...],
        allowed_groups: tuple[str, ...],
    ) -> SyncItemResult:
        try:
            fetched = connector.fetch(item)
        except ConnectorSecurityError:
            raise
        except Exception as exc:
            return _failure(item, exc)

        with self._lock:
            existing = self.store.latest_for_source(item.source_id, access)
        if existing is not None and not can_manage(
            access=access,
            tenant_id=existing.tenant_id,
            owner_principal_id=existing.owner_principal_id,
        ):
            # Checked before the unchanged short-circuit so a caller who does
            # not own the source learns nothing about its current content.
            return _failure(
                item,
                PermissionError(
                    "The source is owned by another principal in this tenant."
                ),
            )
        if (
            existing is not None
            and existing.status == "indexed"
            and existing.sha256 == fetched.checksum
        ):
            return SyncItemResult(
                source_id=item.source_id,
                source_uri=item.source_uri,
                action="unchanged",
                document_id=existing.id,
                version=existing.version,
            )

        # Connector items emit the same extract/chunk/index spans as uploads so
        # one trace shape covers both ingestion paths.
        try:
            with TRACER.start_as_current_span("atlas.ingestion.extract") as span:
                span.set_attribute(
                    "atlas.document.mime_type",
                    fetched.media_type or item.media_type or "unknown",
                )
                span.set_attribute("atlas.document.size_bytes", fetched.size_bytes)
                parsed = self.registry.parse(
                    ParseRequest(
                        content=fetched.content,
                        filename=item.filename,
                        media_type=fetched.media_type or item.media_type,
                        source_uri=item.source_uri,
                        prefer_media_type=connector.name == "url",
                    )
                )
                span.set_attribute("atlas.parser.name", parsed.parser)
                span.set_attribute("atlas.parser.format", parsed.document_format)
                span.set_attribute("atlas.parser.degraded", parsed.degraded)
                span.set_attribute("atlas.document.page_count", len(parsed.pages))
            with TRACER.start_as_current_span("atlas.ingestion.chunk") as span:
                span.set_attribute("atlas.chunking.profile", self.chunking_profile)
                chunks = chunk_pages(
                    parsed.pages,
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap,
                    profile=self.chunking_profile,
                )
                span.set_attribute("atlas.chunk.count", len(chunks))
            if not chunks:
                raise UnsupportedDocumentError(
                    "The document produced no indexable text."
                )
        except Exception as exc:
            return _failure(item, exc)

        with self._lock:
            duplicate = self.store.find_by_hash(fetched.checksum, access)
        if duplicate is not None and duplicate.source_id != item.source_id:
            return SyncItemResult(
                source_id=item.source_id,
                source_uri=item.source_uri,
                action="skipped_duplicate",
                document_id=duplicate.id,
                version=duplicate.version,
                parser=parsed.parser,
                error_type="DuplicateContent",
                error_message=(
                    f"Identical content is already indexed as {duplicate.filename}."
                ),
            )

        try:
            with (
                TRACER.start_as_current_span("atlas.ingestion.index") as span,
                self._lock,
            ):
                span.set_attribute("atlas.tenant_hash", tenant_hash(access.tenant_id))
                span.set_attribute("atlas.chunk.count", len(chunks))
                document, action = self.store.index_source_version(
                    source_id=item.source_id,
                    source_uri=item.source_uri,
                    filename=item.filename,
                    title=parsed.title_hint or item.title,
                    collection=collection,
                    mime_type=parsed.media_type,
                    size_bytes=fetched.size_bytes,
                    sha256=fetched.checksum,
                    chunks=chunks,
                    connector_name=connector.name,
                    connector_instance=connector.instance_id,
                    access=access,
                    visibility=visibility,
                    allowed_principals=allowed_principals,
                    allowed_groups=allowed_groups,
                )
                span.set_attribute("atlas.document.id", document.id)
                span.set_attribute("atlas.document.version", document.version)
        except Exception as exc:
            LOGGER.warning(
                "Connector item could not be indexed",
                extra={
                    "event": "connector.item.failed",
                    "connector": connector.name,
                    "connector_action": "index",
                    "error_type": type(exc).__name__,
                },
            )
            return _failure(item, exc)

        return SyncItemResult(
            source_id=item.source_id,
            source_uri=item.source_uri,
            action=action,
            document_id=document.id,
            version=document.version,
            parser=parsed.parser,
        )

    def _reconcile_deletions(
        self,
        connector: Connector,
        *,
        discovered: set[str],
        access: AccessContext,
    ) -> list[SyncItemResult]:
        results: list[SyncItemResult] = []
        with self._lock:
            live = self.store.list_connector_documents(connector.instance_id, access)
        for document in live:
            if document.source_id in discovered:
                continue
            if not can_manage(
                access=access,
                tenant_id=document.tenant_id,
                owner_principal_id=document.owner_principal_id,
            ):
                # Another principal synchronized the same source. Their
                # documents are not this run's to reconcile.
                continue
            try:
                with self._lock:
                    if self.deletion_policy == "delete":
                        removed = self.store.delete_document(document.id, access)
                        action = "deleted"
                    else:
                        removed = self.store.archive_document(document.id, access)
                        action = "archived"
                if not removed:
                    raise PermissionError(
                        "The document could not be retired by this principal."
                    )
            except Exception as exc:
                results.append(
                    SyncItemResult(
                        source_id=document.source_id,
                        source_uri=document.source_uri,
                        action="failed",
                        document_id=document.id,
                        version=document.version,
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:500] or type(exc).__name__,
                    )
                )
                continue
            results.append(
                SyncItemResult(
                    source_id=document.source_id,
                    source_uri=document.source_uri,
                    action=action,
                    document_id=document.id,
                    version=document.version,
                )
            )
        return results

    @staticmethod
    def _report(progress: ProgressCallback | None, value: int, stage: str) -> None:
        if progress is not None:
            progress(value, stage)


def _item_progress(index: int, total: int) -> int:
    if total <= 0:
        return ITEM_PROGRESS_START
    span = ITEM_PROGRESS_END - ITEM_PROGRESS_START
    return ITEM_PROGRESS_START + round(span * index / total)


def _failure(item: DiscoveredItem, exc: Exception) -> SyncItemResult:
    return SyncItemResult(
        source_id=item.source_id,
        source_uri=item.source_uri,
        action="failed",
        error_type=type(exc).__name__,
        error_message=str(exc)[:500] or type(exc).__name__,
    )


def _tally(report: SyncReport) -> None:
    counters = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "removed": 0,
        "skipped": 0,
        "failed": 0,
    }
    for result in report.items:
        if result.action in {"archived", "deleted"}:
            counters["removed"] += 1
        elif result.action == "skipped_duplicate":
            counters["skipped"] += 1
        else:
            counters[result.action] += 1
    report.created = counters["created"]
    report.updated = counters["updated"]
    report.unchanged = counters["unchanged"]
    report.removed = counters["removed"]
    report.skipped = counters["skipped"]
    report.failed = counters["failed"]
