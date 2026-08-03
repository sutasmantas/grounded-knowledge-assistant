"""Connector contract shared by every Atlas source integration.

A connector is deliberately small: it discovers stable items, fetches one item's
bytes, and describes itself without leaking configuration secrets. Everything
else — checksums, versioning, deletion policy, retries, ACLs — belongs to the
synchronization engine so a new connector cannot accidentally reimplement (or
weaken) the lifecycle rules.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class ConnectorError(RuntimeError):
    """A connector could not complete an operation."""


class ConnectorSecurityError(ConnectorError):
    """The request violated a connector boundary and must not be retried."""


class ConnectorItemError(ConnectorError):
    """One item failed; the remaining items are still synchronizable."""


@dataclass(frozen=True)
class DiscoveredItem:
    """An upstream item and the identity Atlas will keep for it."""

    source_id: str
    source_uri: str
    filename: str
    title: str
    media_type: str | None = None
    size_bytes: int | None = None
    fingerprint: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchedItem:
    item: DiscoveredItem
    content: bytes
    media_type: str | None
    checksum: str
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        return len(self.content)


@runtime_checkable
class Connector(Protocol):
    name: str
    instance_id: str

    def discover(self) -> Iterator[DiscoveredItem]: ...

    def fetch(self, item: DiscoveredItem) -> FetchedItem: ...

    def describe(self) -> dict[str, str]: ...

    def close(self) -> None: ...


def stable_source_id(connector: str, instance_id: str, natural_key: str) -> str:
    """Deterministic identity for an upstream item.

    The same folder entry or URL always produces the same ID, so a repeated
    synchronization updates the existing version chain instead of creating a
    duplicate document.
    """
    digest = hashlib.sha256(
        b"\x00".join(
            part.encode("utf-8") for part in (connector, instance_id, natural_key)
        )
    ).hexdigest()
    return f"{connector}:{digest[:32]}"


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
