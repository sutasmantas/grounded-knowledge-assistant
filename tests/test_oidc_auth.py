from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import AuthenticationError, OIDCAuthenticator
from app.config import Settings
from app.main import create_app

ISSUER = "https://issuer.example"
AUDIENCE = "atlas-api"


def _base64url_uint(value: int) -> str:
    width = (value.bit_length() + 7) // 8
    return jwt.utils.base64url_encode(value.to_bytes(width, "big")).decode()


def signing_key(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _base64url_uint(numbers.n),
        "e": _base64url_uint(numbers.e),
    }
    return private_key, jwk


def token_for(
    private_key,
    kid: str,
    *,
    tenant: str = "acme",
    principal: str = "alice",
    groups: list[str] | Any | None = None,
    roles: list[str] | Any | None = None,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_at: datetime | None = None,
    include_expiry: bool = True,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "tenant_id": tenant,
        "sub": principal,
        "groups": [] if groups is None else groups,
        "roles": [] if roles is None else roles,
    }
    if include_expiry:
        claims["exp"] = expires_at or now + timedelta(minutes=5)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.fixture
def jwks_server():
    state: dict[str, Any] = {"keys": [], "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            state["requests"] += 1
            body = json.dumps({"keys": state["keys"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield state, f"http://{host}:{port}/jwks.json"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def oidc_settings(tmp_path: Path, jwks_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "data_dir": tmp_path / "runtime",
        "sample_documents_dir": tmp_path / "no-samples",
        "embedding_provider": "hash",
        "generation_provider": "extractive",
        "ingestion_worker_enabled": False,
        "auth_mode": "oidc",
        "oidc_issuer": ISSUER,
        "oidc_audience": AUDIENCE,
        "oidc_jwks_url": jwks_url,
        "oidc_clock_skew_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def bearer(token: str, **headers: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} | headers


def test_oidc_mode_requires_complete_secure_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Missing settings for OIDC mode"):
        Settings(data_dir=tmp_path, auth_mode="oidc")

    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            data_dir=tmp_path,
            auth_mode="oidc",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_jwks_url="http://identity.example/jwks.json",
        )

    with pytest.raises(ValidationError, match="approved asymmetric algorithms"):
        Settings(
            data_dir=tmp_path,
            auth_mode="oidc",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_jwks_url="https://identity.example/jwks.json",
            oidc_algorithms=["HS256"],
        )


def test_verified_groups_and_roles_map_into_access_context(
    tmp_path: Path,
    jwks_server,
) -> None:
    state, url = jwks_server
    private_key, public_jwk = signing_key("key-1")
    state["keys"] = [public_jwk]
    authenticator = OIDCAuthenticator(oidc_settings(tmp_path, url))

    access = authenticator.authenticate(
        bearer(
            token_for(
                private_key,
                "key-1",
                groups=["engineering"],
                roles=["legal", "reviewer"],
            )
        )
    )

    assert access.tenant_id == "acme"
    assert access.principal_id == "alice"
    assert access.groups == frozenset({"engineering", "legal", "reviewer"})


def test_unknown_kid_refreshes_jwks_for_key_rotation(
    tmp_path: Path,
    jwks_server,
) -> None:
    state, url = jwks_server
    private_one, jwk_one = signing_key("key-1")
    private_two, jwk_two = signing_key("key-2")
    state["keys"] = [jwk_one]
    authenticator = OIDCAuthenticator(oidc_settings(tmp_path, url))

    assert authenticator.authenticate(
        bearer(token_for(private_one, "key-1"))
    ).principal_id == "alice"
    first_request_count = state["requests"]
    state["keys"] = [jwk_two]
    assert authenticator.authenticate(
        bearer(token_for(private_two, "key-2", principal="rotated-user"))
    ).principal_id == "rotated-user"

    assert state["requests"] > first_request_count


def test_signature_issuer_audience_expiry_and_claim_shape_are_rejected(
    tmp_path: Path,
    jwks_server,
) -> None:
    state, url = jwks_server
    trusted_private, trusted_jwk = signing_key("trusted")
    attacker_private, _ = signing_key("attacker")
    state["keys"] = [trusted_jwk]
    settings = oidc_settings(tmp_path, url)
    invalid_tokens = [
        token_for(attacker_private, "trusted"),
        token_for(trusted_private, "trusted", issuer="https://wrong.example"),
        token_for(trusted_private, "trusted", audience="wrong-api"),
        token_for(
            trusted_private,
            "trusted",
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        ),
        token_for(trusted_private, "trusted", include_expiry=False),
        token_for(trusted_private, "trusted", groups={"not": "a list"}),
    ]

    with TestClient(create_app(settings)) as client:
        for invalid in invalid_tokens:
            response = client.get("/api/documents", headers=bearer(invalid))
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid bearer token."}
            assert response.headers["WWW-Authenticate"] == "Bearer"

        missing = client.get("/api/documents")
        assert missing.status_code == 401
        assert missing.json() == {"detail": "Invalid bearer token."}
        assert client.get("/api/health/ready").status_code == 200


def test_verified_claims_enforce_role_acl_and_cross_tenant_denial(
    tmp_path: Path,
    jwks_server,
) -> None:
    state, url = jwks_server
    private_key, public_jwk = signing_key("access-key")
    state["keys"] = [public_jwk]
    settings = oidc_settings(tmp_path, url)
    owner = bearer(
        token_for(private_key, "access-key", principal="owner"),
        **{"X-Atlas-Tenant": "globex", "X-Atlas-Principal": "attacker"},
    )
    role_reader = bearer(
        token_for(private_key, "access-key", principal="counsel", roles=["legal"])
    )
    outsider = bearer(token_for(private_key, "access-key", principal="outsider"))
    other_tenant = bearer(
        token_for(
            private_key,
            "access-key",
            tenant="globex",
            principal="owner",
            roles=["legal"],
        )
    )
    canary = "OIDC_TENANT_CANARY_731"

    with TestClient(create_app(settings)) as client:
        created_response = client.post(
            "/api/documents",
            headers=owner,
            data={
                "collection": "Mergers",
                "visibility": "restricted",
                "allowed_groups": "legal",
            },
            files={
                "file": (
                    "acquisition.md",
                    f"# Acquisition\nThe confidential code is {canary}.".encode(),
                    "text/markdown",
                )
            },
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["tenant_id"] == "acme"
        assert created["owner_principal_id"] == "owner"

        assert [
            item["id"]
            for item in client.get("/api/documents", headers=role_reader).json()
        ] == [created["id"]]
        for denied in (outsider, other_tenant):
            assert client.get("/api/documents", headers=denied).json() == []
            assert client.get(
                f"/api/documents/{created['id']}/versions", headers=denied
            ).status_code == 404
            query = client.post(
                "/api/query",
                headers=denied,
                json={"question": f"What is {canary}?"},
            ).json()
            assert query["sources"] == []
            assert canary not in query["answer"]


def test_authentication_error_never_contains_unverified_token_data(
    tmp_path: Path,
    jwks_server,
) -> None:
    _state, url = jwks_server
    authenticator = OIDCAuthenticator(oidc_settings(tmp_path, url))

    with pytest.raises(AuthenticationError) as captured:
        authenticator.authenticate({"Authorization": "Bearer secret-token-value"})

    assert str(captured.value) == "Invalid bearer token."
    assert "secret-token-value" not in str(captured.value)
