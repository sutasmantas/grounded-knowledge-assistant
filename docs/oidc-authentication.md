# OIDC/JWT authentication

Atlas has an explicit boundary between its no-key demo and an untrusted API
edge:

- `ATLAS_AUTH_MODE=headers` trusts `X-Atlas-*` identity headers. It is the
  default so the portfolio demo remains runnable without an identity provider.
  Deploy it only behind a gateway that overwrites those headers.
- `ATLAS_AUTH_MODE=oidc` accepts bearer tokens on data APIs, ignores every
  `X-Atlas-*` identity header, and maps only cryptographically verified claims
  into `AccessContext`.

Liveness and readiness are public in either mode. Static frontend assets are
also public. `/api/health` and every document, connector, ingestion, query, and
evaluation endpoint require a bearer token in OIDC mode.

## Configuration

```dotenv
ATLAS_AUTH_MODE=oidc
ATLAS_OIDC_ISSUER=https://identity.example/realms/company
ATLAS_OIDC_AUDIENCE=atlas-api
ATLAS_OIDC_JWKS_URL=https://identity.example/realms/company/protocol/openid-connect/certs
ATLAS_OIDC_ALGORITHMS=["RS256"]
ATLAS_OIDC_TENANT_CLAIM=tenant_id
ATLAS_OIDC_PRINCIPAL_CLAIM=sub
ATLAS_OIDC_GROUPS_CLAIM=groups
ATLAS_OIDC_ROLES_CLAIM=roles
ATLAS_OIDC_JWKS_CACHE_SECONDS=300
ATLAS_OIDC_JWKS_TIMEOUT_SECONDS=5
ATLAS_OIDC_CLOCK_SKEW_SECONDS=30
```

Issuer, audience, and JWKS URL are mandatory in OIDC mode. The JWKS URL must
use HTTPS; loopback HTTP exists only for local tests. Atlas accepts configured
asymmetric signature algorithms only and never derives the algorithm from an
unverified claim without restricting it to that allow-list.

The token must contain valid `exp`, `iss`, and `aud` values plus the configured
tenant and principal claims. Group and role claims may be JSON arrays of
strings or a single string. Atlas normalizes and bounds those values, unions
them into the ACL group set, and rejects malformed shapes. Unknown key IDs
cause the PyJWT JWKS client to refresh the key set, which supports normal key
rotation without accepting an unverifiable token.

Authentication failures return the same `401` body and `WWW-Authenticate:
Bearer` header. Token values and unverified claims are not included in the
response or structured log fields.

## Deliberate limits

Atlas is an OIDC-protected resource server, not an authorization server or an
OAuth client. It does not provide interactive login, token issuance, refresh,
logout, provider discovery, or browser session storage. Configure those at the
identity provider and client/gateway. Changing claim names is deployment
policy; test them against representative provider tokens before rollout.

The regression suite uses real RSA signatures and a live local JWKS HTTP
server. It verifies signature, issuer, audience, expiry, required claims,
unknown-`kid` refresh, role/group ACL mapping, cross-tenant denial, and that
malicious `X-Atlas-*` headers cannot replace verified OIDC identity.
