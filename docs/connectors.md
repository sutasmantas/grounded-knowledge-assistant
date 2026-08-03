# Parsers, connectors and synchronization

## Parser registry

`app/parsers.py` holds one routing table from document format to parser. Each
entry is replaceable through `ParserRegistry.register(format, parser)`, so a
client deployment can swap a single format without touching ingestion,
chunking or retrieval.

| Format | Route | Reason |
| --- | --- | --- |
| PDF with a text layer | `pypdf` | Phase A1 measured it as the fast ordinary-text path |
| PDF without a usable text layer | Docling | The only candidate that recovered every anchor on the pinned scanned fixture |
| DOCX | Docling when installed, otherwise a bounded standard-library reader | Docling preserved the pinned table structure that Unstructured flattened |
| HTML | Docling when installed, otherwise a bounded standard-library reader | Same measurement as DOCX |
| URL content | Routed by the server's declared content type | The response, not the URL text, states what was actually returned |
| Markdown, plain text | Deterministic reader | No measured benefit from a heavier parser |
| CSV | Deterministic reader rendering a Markdown table | Keeps rows and columns addressable for retrieval |

Docling ships in the optional `parsing-benchmark` extra because it pulls a
large model stack. Two rules keep that optionality honest:

- the DOCX and HTML fallbacks set `degraded=True` and carry a note, so a
  fallback result is never presented as the measured quality route;
- the scanned-PDF escalation has **no** fallback. It raises an actionable
  error instead of indexing an empty document.

### Measured fallback behaviour

`docs/parser-registry-v1.json` records the shipped registry against the same
pinned fixtures used in Phase A1:

```powershell
python -m app.parsing_benchmark --providers atlas-registry `
  --output docs/parser-registry-v1.json `
  --artifacts-dir docs/parser-registry-artifacts-v1
```

| Fixture | Result with core dependencies only |
| --- | --- |
| `multi_page` (long-form PDF) | pypdf, anchor recall 1.0 |
| `normal_4pages` (multilingual PDF) | pypdf, anchor recall 1.0 |
| `code_and_formula` | pypdf, anchor recall 0.75 |
| `table_mislabeled_as_picture` | pypdf, anchor recall 0.75 |
| `ocr_test` (scanned PDF) | explicit failure, no silent empty document |
| `word_tables` (DOCX) | fallback, anchor recall 1.0, 30 of 34 reference table rows |
| `html_rich_table_cells` | fallback, anchor recall 1.0, 21 of 22 reference table rows |

Docling's 7/7 result on the same fixtures is recorded in
`docs/parsing-benchmark-v2.json`. The fallbacks lose merged-cell rows, which is
exactly why Docling remains the route whenever it is installed.

### The quality route is executed, not just described

Installing the extra changes what the registry does, so the shipped Docling
adapter must not be unexecuted code. `tests/test_parser_registry.py` contains
cases that run only when Docling imports: they assert that a scanned PDF is
recovered, that DOCX and structured HTML keep the reference table rows the
fallbacks lose, and that an ordinary text PDF still stays on the fast pypdf
path rather than being silently taken over. The `quality-parser` workflow
installs the extra and runs them on demand, on a weekly schedule, and whenever
the parser code or its pinned fixtures change, keeping the main push suite fast.
Cases that pin the core-install contract use a registry fixture with Docling
forced unavailable, so their meaning does not depend on which extras happen to
be installed.

`docs/parser-registry-docling-v1.json` records the same benchmark with the
quality route present:

| Fixture | Route | Result |
| --- | --- | --- |
| `ocr_test` scanned PDF | escalated to Docling | anchor recall 1.0, versus an explicit failure without the extra |
| `word_tables` DOCX | Docling | 34 of 34 reference table rows, versus 30 |
| `html_rich_table_cells` | Docling | 22 of 22 reference table rows, versus 21 |
| the four text PDFs | pypdf | unchanged from the core-install run |

Installing the extra therefore improves only the routes Docling owns. It does
not take over the fast PDF path.

Two failure modes are distinguished on purpose. A document the quality parser
cannot read is `UnsupportedDocumentError` — a caller error, HTTP 422, permanent
for a job. A missing native dependency is `ParserUnavailableError` — an operator
error, HTTP 503, retryable — because telling a user their file is unsupported
when the server's OpenCV libraries are missing would send them to fix the wrong
thing.

## Connector contract

A connector is deliberately small:

```python
class Connector(Protocol):
    name: str
    instance_id: str
    def discover(self) -> Iterator[DiscoveredItem]: ...
    def fetch(self, item: DiscoveredItem) -> FetchedItem: ...
    def describe(self) -> dict[str, str]: ...
    def close(self) -> None: ...
```

Checksums, versioning, deletion policy, retries and ACLs belong to
`app/sync.py`, so a new connector cannot reimplement or weaken the lifecycle
rules. `describe()` is the only thing surfaced through the API and it is
redacted: root names, counts and flags, never absolute paths or URLs.

### Local-folder connector

Requests never contain a filesystem path. An operator configures named roots:

```
ATLAS_CONNECTOR_LOCAL_ROOTS={"handbook": "/srv/atlas/handbook"}
```

A request selects a root by name plus an optional relative subpath. Every
candidate path is resolved against the real root during discovery and resolved
again immediately before reading, which closes the gap between the two.
Symbolic links are never followed, non-regular files are refused, hidden and
VCS directories are skipped, and the per-document byte limit is enforced from
the stat size and again while reading.

Stable identity: `sha256("local-folder" || instance || relative path)`.
Canonical URI: `local://<root name>/<relative path>`.

### URL connector

The controls follow the OWASP SSRF Prevention Cheat Sheet for the
"arbitrary external host" case:

- `http` and `https` only;
- embedded credentials rejected rather than forwarded;
- every resolved A/AAAA record checked against loopback, private, link-local,
  reserved, multicast, unspecified and site-local ranges;
- cloud metadata addresses and hostnames blocked unconditionally
  (`169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`, `192.0.0.192`,
  `metadata.google.internal`, `instance-data`, …);
- the HTTP client's own redirect support disabled, with each hop revalidated
  as if it were the original user-supplied URL;
- the connected peer address verified against the pre-validated set, which is
  the DNS-rebinding case;
- bounded redirects, response size (declared and streamed), timeouts;
- the response content type must be one the parser registry supports.

`ATLAS_CONNECTOR_URL_ALLOW_PRIVATE_NETWORKS=true` is the explicit operator
decision needed to index an internal wiki. Metadata targets stay blocked in
that mode too, because no knowledge-base use case requires them.

Stable identity: `sha256("url" || instance || canonical URL)`. The canonical
URL lowercases the scheme and host, drops the default port and the fragment.

An unsafe URL fails the whole run before any item is indexed, and an unsafe
request is rejected before a job row is written.

## Synchronization

| Behaviour | Rule |
| --- | --- |
| Identity | The connector supplies a stable source ID; Atlas never invents a second identity for the same upstream item |
| Unchanged | A SHA-256 checksum of the fetched bytes decides; an unchanged item performs no parse, embed or vector write |
| Changed | A new immutable version is created and the previous version's vectors are removed |
| Reappearing | An archived source continues its version sequence instead of restarting at version 1 |
| Duplicate content | Content already indexed under a different source is reported as `skipped_duplicate`, matching upload behaviour |
| Disappeared | The configured deletion policy applies |
| Ownership | A source is owned by the principal who first synchronized it; another principal's run fails that item and skips it during reconciliation |
| Partial failure | A failed item is recorded and the run continues; the already indexed documents are untouched |
| Discovery failure | Aborts the run **before** the deletion sweep, so an unreachable source can never mass-archive a healthy index |

### Deletion policy

`ATLAS_CONNECTOR_DELETION_POLICY` selects what happens when an item that was
previously synchronized is no longer discovered:

- `archive` (default) sets the document status to `archived` and removes every
  retrieval representation of every version. The metadata rows remain as an
  audit trail of what the connector once published. An archived document
  cannot be listed, retrieved or cited.
- `delete` removes the vectors and the version history.

A failed *fetch* is not a disappearance. A URL that returns 404 is recorded as
a failed item and its indexed document is preserved.

### URL instance identity caveat

When `instance_id` is omitted, the URL connector derives it from the sorted URL
set. Changing the URL list therefore changes the instance, and documents from
the previous list are no longer reconciled. Pass an explicit `instance_id`
whenever the URL list is expected to change and dropped URLs should be retired.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/connectors` | Catalogue with configured root names and supported formats |
| `POST /api/connectors/local-folder/sync` | Queue a folder synchronization job |
| `POST /api/connectors/url/sync` | Queue a URL synchronization job |
| `GET /api/ingestion-jobs/{id}` | Status, progress, attempts and the persisted sync report |
| `POST /api/ingestion-jobs/{id}/retry` \| `/replay` \| `/cancel` | The existing durable-job controls |

Connector runs reuse the existing ingestion job store rather than adding a
second execution system. The job row carries a kind, the connector identity,
the validated request and the resulting `SyncReport`, so durable progress,
attempt budgets, retry, replay, cancellation, dead-lettering and restart
recovery are inherited rather than reimplemented.

Both endpoints accept `Idempotency-Key`, scoped by tenant and principal like
upload jobs.
