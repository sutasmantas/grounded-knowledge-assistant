from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DocumentVisibility = Literal["tenant", "restricted"]

DEFAULT_TENANT_ID = "demo"
DEFAULT_PRINCIPAL_ID = "demo-user"
DEFAULT_VISIBILITY: DocumentVisibility = "tenant"
IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


@dataclass(frozen=True)
class AccessContext:
    """Identity established by an authenticated upstream gateway."""

    tenant_id: str = DEFAULT_TENANT_ID
    principal_id: str = DEFAULT_PRINCIPAL_ID
    groups: frozenset[str] = frozenset()


DEFAULT_ACCESS_CONTEXT = AccessContext()


def normalize_identity(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not IDENTITY_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must be 1-128 characters using letters, numbers, "
            "dot, underscore, colon, at sign, slash, or hyphen."
        )
    return normalized


def parse_access_context(
    tenant_id: str,
    principal_id: str,
    groups: str | None = None,
) -> AccessContext:
    return AccessContext(
        tenant_id=normalize_identity(tenant_id, "X-Atlas-Tenant"),
        principal_id=normalize_identity(principal_id, "X-Atlas-Principal"),
        groups=frozenset(parse_acl_values(groups, "X-Atlas-Groups")),
    )


def parse_acl_values(value: str | None, field_name: str) -> tuple[str, ...]:
    if not value:
        return ()
    values = tuple(
        dict.fromkeys(
            normalize_identity(item, field_name)
            for item in value.split(",")
            if item.strip()
        )
    )
    if len(values) > 50:
        raise ValueError(f"{field_name} supports at most 50 comma-separated values.")
    return values


def normalize_visibility(value: str) -> DocumentVisibility:
    normalized = value.strip().lower()
    if normalized not in {"tenant", "restricted"}:
        raise ValueError("visibility must be either 'tenant' or 'restricted'.")
    return normalized


def can_read(
    *,
    access: AccessContext,
    tenant_id: str,
    owner_principal_id: str,
    visibility: DocumentVisibility,
    allowed_principals: tuple[str, ...],
    allowed_groups: tuple[str, ...],
) -> bool:
    if tenant_id != access.tenant_id:
        return False
    if visibility == "tenant" or owner_principal_id == access.principal_id:
        return True
    if access.principal_id in allowed_principals:
        return True
    return bool(access.groups.intersection(allowed_groups))


def can_manage(
    *,
    access: AccessContext,
    tenant_id: str,
    owner_principal_id: str,
) -> bool:
    return (
        tenant_id == access.tenant_id
        and owner_principal_id == access.principal_id
    )
