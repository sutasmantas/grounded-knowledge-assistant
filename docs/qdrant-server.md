# External Qdrant server mode

Atlas keeps embedded Qdrant as the zero-service default and adds an explicit
server mode through the official Python client's existing constructor. There
is one `KnowledgeStore`; server mode does not fork lifecycle, retrieval, ACL,
or reconciliation behavior.

## Configuration

Embedded mode remains the default:

```dotenv
ATLAS_QDRANT_MODE=embedded
ATLAS_QDRANT_URL=
```

Server mode requires an explicit URL and never silently falls back:

```dotenv
ATLAS_QDRANT_MODE=server
ATLAS_QDRANT_URL=https://qdrant.example
ATLAS_QDRANT_API_KEY=replace-with-a-secret
ATLAS_QDRANT_TIMEOUT_SECONDS=5
```

For a local server-backed stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.qdrant.yml up --build
```

The overlay pins Qdrant 1.18.3 by image digest. Its published port is bound to
localhost for inspection. A deployed stack should keep Qdrant on a private
network, set an API key, and avoid publishing port 6333 unless an operator
actually needs it.

## Payload indexes

Server mode creates indexes before first ingestion for every field Atlas uses
in vector filters:

| Field | Index | Purpose |
| --- | --- | --- |
| `tenant_id` | keyword, `is_tenant=true` | tenant filter and Qdrant tenant locality |
| `document_id` | keyword | version deletion, vector audit, reconciliation |
| `collection` | keyword | collection-scoped retrieval |
| `is_latest` | bool | exclude stale/archived versions |
| `visibility` | keyword | tenant vs restricted ACL branch |
| `owner_principal_id` | keyword | owner access |
| `allowed_principals` | keyword | named-principal ACL |
| `allowed_groups` | keyword | group ACL |

Index creation is idempotent, so reopening Atlas against the same server keeps
the schema current without rebuilding the collection.

## Gate evidence

The gated server integration uses
`ATLAS_TEST_QDRANT_URL=http://host.docker.internal:16333` and runs
`tests/test_qdrant_server.py` against the pinned real server. It proves:

- all eight payload indexes are present;
- restricted content is visible to an allowed group but not an unlisted user
  or another tenant;
- reindex creates a replacement and removes every stale-version vector;
- closing and reopening `KnowledgeService` recovers the replacement from the
  same SQLite/Qdrant state;
- deletion removes the replacement vectors.

Live container evidence adds the operational cases:

- a clean Compose project built both services and became healthy with six
  seeded documents;
- restarting Qdrant preserved six documents and Atlas readiness stayed/recovered
  at HTTP 200;
- stopping Qdrant made readiness return HTTP 503 with metadata unavailable;
- a query while Qdrant was stopped returned a safe HTTP 503 rather than a
  generic 500;
- restarting Qdrant restored readiness and all six documents.

Final clean verification with the real server test enabled: Ruff passed; 199
tests passed, the five expected Docling-extra tests skipped, and no test failed.

## Deliberate boundary

Changing `ATLAS_QDRANT_MODE` does not copy vectors between embedded storage and
an external server. Use a fresh Atlas data directory and re-ingest or re-sync
the authoritative sources when moving backends. Reusing an old SQLite metadata
database with an empty Qdrant server is unsupported because it would describe
documents whose vectors were never transferred.
