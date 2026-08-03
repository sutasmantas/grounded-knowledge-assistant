# Architecture

```text
                                ┌──────────────────┐
file ─> extraction ─> chunks ─> │ dense embeddings │ ─┐
                                └──────────────────┘  │
                                ┌──────────────────┐  ├─> named Qdrant vectors
                                │ lexical vectors  │ ─┘
                                └──────────────────┘

question ─┬─> dense candidates ───┐
          └─> lexical candidates ─┴─> RRF ─> optional learned rerank
                                                 │
                                  evidence + execution trace
                                                 │
                              extractive or model-generated answer
```

Asynchronous uploads add a durable control path before extraction:

```text
multipart upload -> SQLite job + retained input -> worker claim
                                                -> progress stages
                                                -> document transaction
                                                -> success / failed / cancelled
                                                           |
                                                     dead-letter + replay
```

Connector synchronization reuses the same durable control path:

```text
validated connector request -> SQLite job (kind=connector-sync) -> worker claim
                                                -> discover
                                                -> per-item fetch/parse/index
                                                -> deletion reconciliation
                                                -> persisted sync report
```

## Parsers and connectors

`app/parsers.py` routes PDF, Markdown, plain text, DOCX, HTML, URL content and
CSV through a replaceable per-format table, and `app/connectors` implements the
local-folder and URL sources behind a four-method contract. Lifecycle rules —
stable identity, checksums, immutable versions, deletion policy, ownership and
partial-failure isolation — live in `app/sync.py` so a new connector cannot
weaken them. See the [connector reference](connectors.md) for the routing
table, the measured fallback behaviour, the SSRF controls and the deletion
policy.

## Why profiles are explicit

Retrieval techniques are not universally additive. Dense retrieval helps with
paraphrases; lexical retrieval protects identifiers and exact policy language;
late-interaction reranking can improve ordering but adds model weight and
latency. Atlas keeps these as three request-level profiles and evaluates them
against the same cases rather than enabling every technique unconditionally.

The hybrid path uses Qdrant named vectors:

- `dense`: the configured FastEmbed or deterministic hash representation
- `sparse`: deterministic token vectors with collection-level IDF
- fusion: reciprocal-rank fusion over independent candidate lists

`hybrid-reranked` retrieves a wider candidate set, then applies the configured
reranker. FastEmbed adapters support cross-encoder scoring and ColBERT MaxSim.
The lexical reranker keeps tests and constrained environments deterministic.
The [retrieval baseline](evaluation-report.md) selects standalone sparse
retrieval for the bundled policy corpus because it wins the frozen held-out
comparison. Hybrid remains selectable for client corpora where a controlled
comparison shows that semantic candidates justify the added work. The
[reranker bake-off](reranker-bakeoff.md) retains the BGE cross-encoder only as
an explicit high-latency experiment rather than a claimed quality upgrade.

## Chunking profiles

Ingestion exposes three settings behind the same extraction and indexing
contract:

- `fixed` uses overlapping word-boundary windows and remains the default.
- `heading-aware` keeps Markdown sections intact and repeats a heading when a
  long section splits.
- `parent-child` indexes smaller child text but returns the containing section;
  returned contexts are deduplicated with document-scoped IDs.

The alternatives are experiments, not automatically additive features. The
[chunking bake-off](chunking-bakeoff.md) measures all three against identical
cases and records the decision to keep fixed windows for this corpus.

## Evaluation boundary

`evals/golden.jsonl` defines a frozen development or held-out split, scenario
category, question, allowed collections, expected source titles, and whether
the system should answer. `python -m app.evaluation` reports MRR@5, Recall@5,
nDCG@5, no-answer accuracy, p50/p95 retrieval and total latency, index time,
and traced Python peak memory. A JSONL export preserves every retrieved title,
rank, trace field, and case score for failure analysis. Ranking metrics credit
each expected document only once even when several chunks from it are returned.

Cases for source-version conflicts, prompt injection, and tenant isolation are
present but capability-gated. The runner reports them as skipped with a reason;
it does not award quality credit for controls the application does not yet
implement.

The bundled corpus is deliberately controlled and small. Its result is a
regression gate for repository changes, not evidence that a profile will
generalize to a client's documents. Tune only on the development split, run
the held-out split for the final comparison, and version client-specific cases
before changing chunking, models, or retrieval profiles.

## Data boundaries

- SQLite stores immutable document-version metadata, connector ownership, and
  lifecycle status. Content uniqueness is scoped to the live revision, so
  version history and archived connector sources may repeat a checksum; an
  upstream revert requires that.
- Qdrant stores chunk vectors plus the stable source ID, source URI, document
  version, checksum, and latest-version marker used by retrieval.
- Uploaded files are processed from a temporary directory and are not retained.
- Sample documents contain fictional policy content written for this repository.
- No API keys or client data belong in the repository.
- A legacy single-vector collection is copied into the named-vector index on
  first v2 startup so local users are not silently stranded.

## Document lifecycle

The first upload creates a stable `source_id` and version 1. Re-indexing writes
the replacement vectors as non-current, retires the previous vector payloads,
then promotes the replacement and commits its metadata. A failed promotion
restores the prior version and deletes the replacement points. After a
successful commit, the old points are deleted while their metadata row remains
as immutable version history.

Every search rejects payloads explicitly marked `is_latest=false` before dense
or sparse ranking. Legacy payloads without the marker remain readable. Citation
objects carry `source_uri`, `document_version`, and `document_sha256`, so an
answer can be tied to the exact indexed revision rather than only a title.
Complete deletion first tombstones every version in SQLite, removes all matching
Qdrant points, and then removes the version history. A vector-store failure
restores the previous metadata states instead of reporting a successful delete.

## Ingestion jobs

The asynchronous API persists the job before returning HTTP 202. A separate
SQLite database uses a transactional `BEGIN IMMEDIATE` claim so one local worker
owns a queued job. Each record retains progress, stage, attempt budget, error
type/message, cancellation intent, timestamps, and the resulting document ID.
An optional idempotency key returns the existing job instead of storing or
indexing the same request again. The key is namespaced by tenant and owning
principal; job list, read, cancellation, retry, and replay operations use the
same ownership boundary.

Cancellation is checked between reading, duplicate detection, extraction,
chunking, and indexing. Once the atomic document-index write begins, success
wins over a late cancellation so the API cannot report `cancelled` after making
the document searchable. Successful and cancelled jobs remove their retained
input. A cleanup failure remains visible on the terminal job instead of being
silently discarded. Failed and dead-letter jobs keep the input for retry or
explicit replay.

On startup, interrupted running jobs are re-queued when attempts remain,
cancelled when cancellation was already requested, or dead-lettered when the
budget is exhausted. This local runner keeps the public demo self-contained.
It does not claim distributed execution: a client deployment that needs several
workers or servers should replace the runner behind the same persisted job/API
contract with RQ, Celery, or Temporal.

## Provider modes

The `fastembed` provider uses `BAAI/bge-small-en-v1.5` locally. The `hash`
provider is deterministic and dependency-light; because it is lexical, Atlas
also applies a content-token evidence gate to avoid returning hash-collision
matches for out-of-domain questions.

Answer generation defaults to a local extractive mode that can run without an
API key. `openai-compatible` mode sends only the retrieved passages and question
to a configured chat-completions endpoint and rejects uncited output.

## Tenant and document authorization

`AccessContext` carries the tenant, principal, and group memberships established
by an upstream identity boundary. The HTTP header adapter defaults to the
fictional demo tenant, but the authorization code is independent of how an
authenticated deployment constructs that context.

SQLite queries include the tenant before applying document visibility:
`tenant` documents are readable within that tenant, while `restricted`
documents require ownership, a named principal, or an allowed group. Qdrant
receives the equivalent tenant and ACL filter before dense/sparse candidate
generation. Disallowed passages therefore cannot reach fusion, reranking,
generation, or citations. Re-indexing and deletion require the owner, and new
versions inherit the source ACL.

Adversarial API tests create canary content under two tenants, replay direct
resource IDs, and verify that unauthorized users receive 404 and cannot discover
the canary through lists, versions, retrieval, citations, deletion, or
ingestion-job controls.

The design follows the threat and test patterns in the
[OWASP Multi-Tenant Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html),
[OWASP Authorization Regression Testing Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Regression_Testing_Cheat_Sheet.html),
and [OWASP RAG Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html).
The vector layout uses Qdrant's documented
[payload filtering](https://qdrant.tech/documentation/search/filtering/) and
[single-collection multitenancy](https://qdrant.tech/documentation/tutorials/multiple-partitions/)
pattern.

## Runtime observability

The request boundary assigns or validates an `X-Request-ID`, returns it to the
caller, and emits one structured completion/failure event without bodies or
query text. Tenant and principal values are represented only by short one-way
hashes in logs.

When an OTLP endpoint is configured, FastAPI server spans parent manual
`atlas.rag.query`, retrieval, generation, extraction, chunking, indexing, and
background-job spans. Span attributes carry provider/profile names, counts,
stage latency, and safe IDs—not questions, answers, passages, filenames, or
identity values. The optional Phoenix Compose overlay is a viewer/collector,
not a dependency of the no-key local mode.

## Production extension points

The repository now has the retrieval/evaluation seam needed for the next
client-specific layers:

- OIDC/JWT or gateway-signed authentication for `AccessContext`
- ACL administration and audit-event export
- retained source objects for connector replay
- Drive, SharePoint, and database connectors behind the shipped connector
  contract; local-folder and URL are implemented
- distributed ingestion workers and OCR
- production alert rules, SLOs, and deployment-specific log/trace retention
- larger corpus-specific evaluation sets and cost budgets

These are extension points, not claims that the current repository already
implements enterprise authentication or connector behavior.
