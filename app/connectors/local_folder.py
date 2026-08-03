"""Local-folder connector.

The folder is never addressed by absolute path from the API. An operator
configures named roots (`ATLAS_CONNECTOR_LOCAL_ROOTS`), and a request may only
select a root name plus a relative subpath. Every candidate path is re-resolved
against the real root before discovery and again before reading, so neither
`..` traversal nor a symlink planted inside the root can escape it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from app.connectors.base import (
    ConnectorItemError,
    ConnectorSecurityError,
    DiscoveredItem,
    FetchedItem,
    checksum,
    stable_source_id,
)
from app.parsers import ParserRegistry

SKIPPED_DIRECTORY_NAMES = {".git", ".svn", "__pycache__", "node_modules"}


class LocalFolderConnector:
    name = "local-folder"

    def __init__(
        self,
        *,
        root_name: str,
        root: Path,
        subpath: str = "",
        recursive: bool = True,
        registry: ParserRegistry,
        max_bytes: int,
        max_items: int,
        instance_id: str | None = None,
    ) -> None:
        self.root_name = root_name
        self.registry = registry
        self.max_bytes = max_bytes
        self.max_items = max_items
        self.recursive = recursive
        self._root = self._resolve_root(root)
        self._base = self._resolve_within_root(subpath)
        self.subpath = self._relative(self._base)
        self.instance_id = instance_id or f"local-folder:{root_name}:{self.subpath}"

    @staticmethod
    def _resolve_root(root: Path) -> Path:
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise ConnectorSecurityError(
                "The configured connector root does not exist."
            ) from exc
        if not resolved.is_dir():
            raise ConnectorSecurityError(
                "The configured connector root is not a directory."
            )
        return resolved

    def _resolve_within_root(self, subpath: str) -> Path:
        candidate = (subpath or "").strip().replace("\\", "/").strip("/")
        if not candidate:
            return self._root
        raw = Path(candidate)
        if raw.is_absolute() or raw.drive or raw.anchor:
            raise ConnectorSecurityError(
                "The connector subpath must be relative to the configured root."
            )
        try:
            resolved = (self._root / raw).resolve(strict=True)
        except OSError as exc:
            raise ConnectorSecurityError(
                "The connector subpath does not exist inside the configured root."
            ) from exc
        self._require_inside_root(resolved)
        if not resolved.is_dir():
            raise ConnectorSecurityError("The connector subpath is not a directory.")
        return resolved

    def _require_inside_root(self, resolved: Path) -> None:
        if resolved != self._root and not resolved.is_relative_to(self._root):
            raise ConnectorSecurityError(
                "The resolved path escapes the configured connector root."
            )

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix() if path != self._root else ""

    def describe(self) -> dict[str, str]:
        """Redacted description: the absolute root is never returned."""
        return {
            "connector": self.name,
            "instance_id": self.instance_id,
            "root": self.root_name,
            "subpath": self.subpath,
            "recursive": str(self.recursive).lower(),
        }

    def discover(self) -> Iterator[DiscoveredItem]:
        supported = self.registry.supported_suffixes
        discovered = 0
        for path in self._walk():
            if path.suffix.lower() not in supported:
                continue
            discovered += 1
            if discovered > self.max_items:
                raise ConnectorItemError(
                    f"The folder exposes more than {self.max_items} supported "
                    "documents; narrow the subpath or raise the configured limit."
                )
            relative = path.relative_to(self._root).as_posix()
            stats = path.stat()
            yield DiscoveredItem(
                source_id=stable_source_id(self.name, self.instance_id, relative),
                source_uri=f"local://{self.root_name}/{relative}",
                filename=path.name,
                title=_title_from_filename(path.name),
                media_type=None,
                size_bytes=stats.st_size,
                fingerprint=f"{stats.st_size}:{int(stats.st_mtime)}",
                metadata={"relative_path": relative},
            )

    def _walk(self) -> Iterator[Path]:
        for directory, directory_names, filenames in os.walk(
            self._base, followlinks=False
        ):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not name.startswith(".")
                and name not in SKIPPED_DIRECTORY_NAMES
                and not Path(directory, name).is_symlink()
            )
            if not self.recursive:
                directory_names[:] = []
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                candidate = Path(directory, filename)
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                try:
                    self._require_inside_root(candidate.resolve(strict=True))
                except (OSError, ConnectorSecurityError):
                    continue
                yield candidate

    def fetch(self, item: DiscoveredItem) -> FetchedItem:
        relative = item.metadata.get("relative_path", "")
        if not relative:
            raise ConnectorItemError("The discovered item has no folder path.")
        path = self._safe_path(relative)
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ConnectorItemError(
                f"{item.filename} is larger than the configured "
                f"{self.max_bytes // (1024 * 1024)} MB connector document limit."
            )
        content = path.read_bytes()
        if len(content) > self.max_bytes:
            raise ConnectorItemError(
                f"{item.filename} exceeded the connector document limit while reading."
            )
        if not content:
            raise ConnectorItemError(f"{item.filename} is empty.")
        return FetchedItem(
            item=item,
            content=content,
            media_type=item.media_type,
            checksum=checksum(content),
            metadata={"relative_path": relative},
        )

    def _safe_path(self, relative: str) -> Path:
        """Re-validate immediately before reading to close the discovery gap."""
        raw = Path(relative.replace("\\", "/"))
        if raw.is_absolute() or raw.drive or raw.anchor or ".." in raw.parts:
            raise ConnectorSecurityError(
                "The connector item path must stay inside the configured root."
            )
        candidate = self._root / raw
        if candidate.is_symlink():
            raise ConnectorSecurityError(
                "Symbolic links are not followed by the local-folder connector."
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ConnectorItemError(
                f"{relative} disappeared before it could be read."
            ) from exc
        self._require_inside_root(resolved)
        if not resolved.is_file():
            raise ConnectorSecurityError("Only regular files can be synchronized.")
        return resolved

    def close(self) -> None:
        return None


def _title_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip().title() or filename
