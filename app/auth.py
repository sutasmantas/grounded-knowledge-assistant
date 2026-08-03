from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import jwt

from app.access import (
    DEFAULT_PRINCIPAL_ID,
    DEFAULT_TENANT_ID,
    AccessContext,
    normalize_identity,
    parse_access_context,
)
from app.config import Settings


class AuthenticationError(ValueError):
    """Safe boundary error. Never include a token or unverified claims."""


class RequestAuthenticator(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> AccessContext: ...


class HeaderAuthenticator:
    """No-key demo mode; an upstream gateway is assumed to trust these headers."""

    def authenticate(self, headers: Mapping[str, str]) -> AccessContext:
        return parse_access_context(
            headers.get("X-Atlas-Tenant", DEFAULT_TENANT_ID),
            headers.get("X-Atlas-Principal", DEFAULT_PRINCIPAL_ID),
            headers.get("X-Atlas-Groups"),
        )


def _claim_values(claims: dict[str, Any], claim_name: str) -> tuple[str, ...]:
    raw = claims.get(claim_name)
    if raw is None:
        return ()
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise AuthenticationError("Invalid bearer token.")
    normalized = tuple(
        dict.fromkeys(normalize_identity(item, claim_name) for item in values)
    )
    if len(normalized) > 50:
        raise AuthenticationError("Invalid bearer token.")
    return normalized


class OIDCAuthenticator:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer
        self._audience = settings.oidc_audience
        self._algorithms = list(settings.oidc_algorithms)
        self._tenant_claim = settings.oidc_tenant_claim
        self._principal_claim = settings.oidc_principal_claim
        self._groups_claim = settings.oidc_groups_claim
        self._roles_claim = settings.oidc_roles_claim
        self._clock_skew_seconds = settings.oidc_clock_skew_seconds
        self._jwks = jwt.PyJWKClient(
            settings.oidc_jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=settings.oidc_jwks_cache_seconds,
            timeout=settings.oidc_jwks_timeout_seconds,
        )

    def authenticate(self, headers: Mapping[str, str]) -> AccessContext:
        authorization = headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("Invalid bearer token.")
        token = token.strip()
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_seconds,
                options={
                    "require": [
                        "exp",
                        "iss",
                        "aud",
                        self._tenant_claim,
                        self._principal_claim,
                    ]
                },
            )
            tenant = claims[self._tenant_claim]
            principal = claims[self._principal_claim]
            if not isinstance(tenant, str) or not isinstance(principal, str):
                raise AuthenticationError("Invalid bearer token.")
            groups = _claim_values(claims, self._groups_claim)
            roles = _claim_values(claims, self._roles_claim)
            return AccessContext(
                tenant_id=normalize_identity(tenant, self._tenant_claim),
                principal_id=normalize_identity(principal, self._principal_claim),
                groups=frozenset((*groups, *roles)),
            )
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("Invalid bearer token.") from exc


def create_authenticator(settings: Settings) -> RequestAuthenticator:
    if settings.auth_mode == "oidc":
        return OIDCAuthenticator(settings)
    return HeaderAuthenticator()
