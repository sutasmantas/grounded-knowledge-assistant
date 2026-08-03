# Observability and security operations

Atlas emits one correlated path from the HTTP request through retrieval,
optional reranking, generation, and asynchronous ingestion. OpenTelemetry is
disabled until an OTLP endpoint is configured; structured JSON request logs and
`X-Request-ID` response headers are enabled by default.

## Local Phoenix trace viewer

Run Atlas with the pinned Phoenix sidecar:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.observability.yml \
  up --build
```

Open Atlas at <http://localhost:8000> and Phoenix at
<http://localhost:6006>. Ask a question or index a document, then inspect the
`atlas.rag.query`, `atlas.rag.retrieve`, `atlas.rag.generate`, and ingestion
spans in the `atlas-knowledge` project.

## Span inventory

| Span | Emitted for | Key attributes |
| --- | --- | --- |
| `atlas.rag.query` | Every query | `atlas.retrieval.profile`, `atlas.query.duration_ms`, `atlas.query.source_count`, `gen_ai.usage.total_tokens` |
| `atlas.rag.retrieve` | Retrieval and optional rerank | `atlas.retrieval.candidates`, `atlas.retrieval.source_count`, `atlas.retrieval.duration_ms` |
| `atlas.rag.generate` | Answer generation | `gen_ai.operation.name`, `gen_ai.provider.name`, `atlas.context.source_count`, `atlas.context.characters`, `atlas.generation.duration_ms`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens` |
| `atlas.ingestion.extract` | Parsing, for uploads **and** connector items | `atlas.parser.name`, `atlas.parser.format`, `atlas.parser.degraded`, `atlas.document.mime_type`, `atlas.document.size_bytes`, `atlas.document.page_count` |
| `atlas.ingestion.chunk` | Chunking, both paths | `atlas.chunking.profile`, `atlas.chunk.count` |
| `atlas.ingestion.index` | Vector write, both paths | `atlas.tenant_hash`, `atlas.chunk.count`, `atlas.document.id`, `atlas.document.version` |
| `atlas.ingestion.job` | Every background job attempt | `atlas.job.id`, `atlas.job.attempt`, `atlas.job.outcome`, recorded exception on failure |
| `atlas.connector.sync` | Every connector run | `atlas.connector.name`, `atlas.connector.discovered/created/updated/unchanged/removed/failed` |

## Token use and generation cost

`atlas.rag.generate` and the `POST /api/query` response both carry a generation
trace:

```json
"generation": {
  "provider": "openai-compatible",
  "context_sources": 5,
  "context_characters": 4193,
  "prompt_tokens": 1204,
  "completion_tokens": 86,
  "total_tokens": 1290,
  "generation_ms": 812
}
```

Token counts come from the provider's own `usage` block and are **never
estimated**. When a provider omits usage, or when the local extractive mode
answers without calling a model, the counts are `null` and the corresponding
`gen_ai.usage.*` span attributes are absent rather than zero. A fabricated zero
would silently corrupt a cost budget, which is the reason the field exists.

`context_sources` and `context_characters` are always populated, so the size of
what was sent to generation stays measurable in no-key mode too.

### Verifying token use without a paid provider

The counts come from the provider, so seeing them end to end needs an
OpenAI-compatible endpoint rather than a credential. Point Atlas at any stub
that returns a `usage` block:

```dotenv
ATLAS_GENERATION_PROVIDER=openai-compatible
ATLAS_LLM_BASE_URL=http://your-stub:9000/v1
ATLAS_LLM_MODEL=stub-model
ATLAS_OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:6006/v1/traces
```

Ask a question, then read the span back from Phoenix:

```bash
curl -s 'http://localhost:6006/v1/projects/default/spans?limit=100' \
  | jq '.data[] | select(.name=="atlas.rag.generate") | .attributes'
```

A verified run returned:

```json
{
  "gen_ai.provider.name": "openai-compatible",
  "gen_ai.usage.input_tokens": 1204,
  "gen_ai.usage.output_tokens": 86,
  "gen_ai.usage.total_tokens": 1290,
  "atlas.context.source_count": 5,
  "atlas.context.characters": 4575,
  "atlas.generation.duration_ms": 28,
  "llm.token_count.prompt": 1204,
  "llm.token_count.completion": 86,
  "llm.token_count.total": 1290
}
```

The `llm.token_count.*` keys are added by Phoenix itself: it recognizes the
standard `gen_ai.usage.*` attributes and maps them into its own convention, so
its token and cost views work without Atlas emitting anything vendor-specific.

The structured `rag.query.completed` log event carries the retrieval profile,
source count, duration, generation provider, and total tokens — never the
question, the answer, or any passage.

## Connector synchronization

Each connector item emits the same `atlas.ingestion.extract`,
`atlas.ingestion.chunk` and `atlas.ingestion.index` spans as an upload, so one
trace shape covers both ingestion paths and the chosen parser is visible per
item. Around them, connector runs emit `atlas.connector.sync` with per-outcome counters, a
`connector.sync.completed` log event carrying the connector name, discovered
and failed counts, and duration, and a `connector.item.failed` warning per
failed item carrying only the connector name, action, and error type. Item
paths, URLs, and document text are never logged. Each run is also a durable
ingestion job, so its progress, attempts, error type, and persisted
`sync_report` are readable from `GET /api/ingestion-jobs/{id}` without a
collector.

The overlay is for local single-user debugging. Phoenix is deliberately not
exposed as an authenticated production service here. Put it behind your
deployment identity boundary and use PostgreSQL for a multi-user or durable
installation.

The overlay runs the pinned non-root Phoenix image. A short-lived Alpine
initializer assigns the named volume to Phoenix's documented runtime user,
then exits before either application starts. Atlas uses its deterministic
no-key providers in this overlay so the trace demo does not download a model or
require an external API key.

## Existing collector

Set:

```dotenv
ATLAS_OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example/v1/traces
ATLAS_OTEL_SERVICE_NAME=atlas-knowledge
```

The exporter uses OTLP over HTTP with batch delivery. It works with Phoenix or
another OTLP-compatible collector.

## Data minimization

Spans record pipeline structure, provider/profile names, counts, token use,
safe resource IDs, and stage latency. They do not record questions, answers,
retrieved passages, filenames, connector paths or URLs, tenant names, principal
names, credentials, or request bodies. Structured logs use short one-way hashes
for tenant and principal correlation and never log query text.

The request boundary also:

- replaces malformed correlation IDs instead of reflecting them;
- returns `413` for declared request bodies above the configured limit;
- adds no-store, framing, MIME-sniffing, referrer, permission, and frontend CSP
  headers;
- exposes separate liveness and dependency-aware readiness routes.

## Prompt-injection boundary

Every source remains untrusted. High-confidence instruction override,
secret-extraction, and remote-resource patterns are stored as source security
flags. Matching source sentences are removed from model context but remain
visible in evidence for review. The model receives structured JSON records and
explicit instructions not to execute source text. Direct override/extraction
questions are rejected before retrieval, and generated remote image markup is
rejected before rendering.

These are bounded deterministic controls, not a proof of general prompt
injection resistance. The CI suite covers known direct and indirect cases. A
provider-backed release should additionally run the documented bounded garak
profile and review failures against the client threat model.

### Bounded provider release scan

Start Atlas with the client/provider configuration, install the isolated
scanner extra, and run only the injection-focused probes with one generation:

```bash
python -m pip install -e ".[security-scan]"
python -m garak \
  --target_type rest \
  --generator_option_file security/garak-atlas-rest.json \
  --probes promptinject,encoding \
  --generations 1
```

The REST profile extracts the API's `answer` field. High-confidence direct
attacks rejected with HTTP 422 are configured as skipped generations; review
both skips and detector failures rather than treating one aggregate pass rate
as proof of safety. Increase generations and add threat-model-specific probes
for an actual release candidate.

## Primary references

- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
- [OpenTelemetry OTLP exporters](https://opentelemetry.io/docs/languages/python/exporters/)
- [Phoenix tracing architecture](https://arize.com/docs/phoenix/tracing/concepts-tracing/how-does-tracing-work)
- [Phoenix Docker deployment](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [NVIDIA garak](https://github.com/NVIDIA/garak)
