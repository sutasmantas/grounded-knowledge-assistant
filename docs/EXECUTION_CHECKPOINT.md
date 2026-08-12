# Atlas Execution Checkpoint

Last updated: 2026-08-03

This is the canonical restart checkpoint for Atlas. Read it before acting on
“continue with the plan.” The detailed scope remains in
`PORTFOLIO_PRODUCTIZATION_PLAN_2026-07-30.md`, but this file determines the
current phase, the next action, and whether a transition is allowed.

## Current decision

UI2 and P2 production adaptation are complete. P2 was merged locally to
`main` at `ee8b420`; Atlas Phase C remains paused. The public-facing workspace
refresh is also complete at local `main` commit `a33e3e8`: Atlas now has a
credential-free GitHub Pages interface, current answer/library screenshots,
and client-facing README copy. Public `main` is the separate root snapshot
`d642119`; Pages run `30843739208`, CI run `30843662278`, the local frontend
build, and deployed desktop/mobile browser checks all passed. No further Atlas
phase is authorized by this checkpoint.

The pre-code GitHub comparison gate is `PASS`; see
`docs/P2_GITHUB_REUSE_AUDIT.md`. The pinned decisions are: refit Atlas's frozen
evaluation around a local llama.cpp OpenAI-compatible server; adopt the
official Qdrant client's local/remote and payload-index APIs; adopt PyJWT's
JWKS validator and keep only verified-claim-to-`AccessContext` mapping custom.
The measured-generation slice is `PASS`: a cold-cache 20-case comparison
completed and rejected the local candidate, so extractive remains the default.
The external-Qdrant slice is also `PASS`: both storage modes use the official
client, all filter indexes exist on the real server, lifecycle/ACL/reopen tests
pass, and live restart/failure/clean-Compose behavior is recorded. The OIDC/JWT
slice is `PASS`: data APIs validate bearer signatures and standard claims
through PyJWT/JWKS, unknown key IDs refresh the key set, verified tenant and
ACL claims map into `AccessContext`, and caller-supplied identity headers are
ignored in OIDC mode. P2 is complete; no frontend polish was started.

| P2 slice | Status | Evidence | Next action |
| --- | --- | --- | --- |
| GitHub reuse audit | PASS | `docs/P2_GITHUB_REUSE_AUDIT.md`; pinned repository revisions and adopt/refit/custom decisions | — |
| Measured generation | PASS | `app/generation_evaluation.py`; 20 baseline + 20 candidate rows; `docs/atlas-p2-generation-comparison.json`; Ruff clean; 193 core tests passed + 5 expected skips; 21 affected tests passed; clean image built and live no-key container became healthy | — |
| External Qdrant | PASS | `docker-compose.qdrant.yml`; `tests/test_qdrant_server.py`; eight live payload indexes; lifecycle/ACL/reopen/delete passed; Qdrant restart retained six documents; outage returned readiness/query 503; clean Compose healthy; Ruff clean; 199 passed + 5 expected skips | — |
| OIDC/JWT edge | PASS | `d047670`; `app/auth.py`; `tests/test_oidc_auth.py`; real RSA/JWKS rotation, invalid-token and cross-tenant/role ACL tests; full clean gate 205 passed + 5 expected skips; fresh production image built and ran ready | — |

## Repository restart point

- Phase A working directory:
  `C:\Users\masuta\Desktop\Coding\cv\portfolio_demos\worktrees\atlas_phase_a`
- Phase A branch: `agent/atlas-phase-a-closure`
- Phase B working directory:
  `C:\Users\masuta\Desktop\Coding\cv\portfolio_demos\worktrees\atlas_phase_b`
- Phase B branch: `agent/atlas-phase-b-closure`
- Main verification/publishing worktree:
  `C:\Users\masuta\Desktop\Coding\cv\portfolio_demos\worktrees\atlas_main`
- P2 production-adaptation worktree:
  `C:\Users\masuta\Desktop\Coding\cv\portfolio_demos\worktrees\atlas_p2`
- P2 branch: `agent/atlas-p2-production`
- Remote: `https://github.com/sutasmantas/grounded-knowledge-assistant.git`
- Application baseline commit: `fa7381fbb8491e11575b302b7da02388d49d5b77`
- Baseline commit content: tenant-scoped ACLs, document lifecycle, durable
  ingestion jobs, verified observability, and deterministic prompt-injection
  controls
- Phase A0 candidate commit: `fd05097` — standalone sparse retrieval,
  frozen-corpus artifacts, explicit cost record, and evidence-based default
- Phase B evidence commit: `2057019` — parser registry, connector contract,
  local-folder and URL connectors, synchronization engine, generation token-use
  accounting, connector ingestion spans, the Phase B test suite, and the
  connector and observability reference documentation
- Expected `main` state: clean and containing application checkpoint `a7e721a`,
  P2 merge `ee8b420`, no-login workspace publication commit `a33e3e8`, and
  this checkpoint update.
  Public
  `origin/main` is intentionally a separate root
  publication snapshot at `d642119`. The histories diverge by design; never
  merge, rebase, or directly push local `main` into the public snapshot.

Run before resuming:

```powershell
git -C portfolio_demos\worktrees\atlas_main status -sb
git -C portfolio_demos\worktrees\atlas_main rev-parse HEAD
git -C portfolio_demos\worktrees\atlas_main rev-parse origin/main
```

Do not start if the main worktree is dirty or differs from the recorded local
P2 state without first explaining and preserving the unexpected state. The
Phase A, Phase B, UI2, and P2 closure worktrees are finished; their branches
must not receive new work.

## Concurrent-work protection

Several Codex application sessions were found using the same checkout. Git
worktrees now isolate branch state:

| Purpose | Directory | Branch | State |
| --- | --- | --- | --- |
| Phase A closure | `portfolio_demos/worktrees/atlas_phase_a` | `agent/atlas-phase-a-closure` | merged, closed |
| Phase B closure | `portfolio_demos/worktrees/atlas_phase_b` | `agent/atlas-phase-b-closure` | merged, closed |
| clean main/publishing | `portfolio_demos/worktrees/atlas_main` | `main` | active |
| reserved feature work | `portfolio_demos/knowledge_assistant` | `agent/atlas-frontend-media` | reserved |
| Phase UI2 | `portfolio_demos/worktrees/atlas_ui2` | `agent/atlas-ui2-foundation` | merged to `main` at `4b4288f`; closed |
| P2 production adaptation | `portfolio_demos/worktrees/atlas_p2` | `agent/atlas-p2-production` | merged to `main` at `ee8b420`; closed |

Never switch branches inside these worktrees. Never perform Phase A work in the
original `knowledge_assistant` directory. A new concurrent task must receive a
new named branch and a separate worktree. If any worktree is unexpectedly dirty,
stop and preserve the owner’s changes instead of cleaning or moving them.

## Reconciled Phase B work

The formerly paused observability and prompt-injection slice was reviewed,
squashed, live-tested, and merged to `main` as `fa7381f`:

- correlated structured logs and OpenTelemetry spans;
- pinned non-root Phoenix Compose sidecar with a verified OTLP round-trip;
- readiness and liveness checks, request/body guardrails, and security headers;
- deterministic direct/indirect prompt-injection controls and source flags;
- bounded garak REST profile and documented limitations.

Evidence at merge: 48 tests, 89% coverage, clean lint, Docker build, healthy
Atlas/Phoenix containers, successful query, and Phoenix API inspection of the
query/retrieve/generate span tree.

The remaining parser/connector registry and connector synchronization path was
closed on `agent/atlas-phase-b-closure`. See the Phase B ledger and the
`B to UI2/C` transition record below.

## Phase-gate ledger

Allowed statuses are `PASS`, `PARTIAL`, `FAIL`, and `UNVERIFIED`. Only all
`PASS` permits a phase transition.

### Phase A0 — research and baseline gate: PASS

| Requirement | Status | Existing evidence | Missing evidence |
| --- | --- | --- | --- |
| 40–60 reviewed cases and held-out split | PASS | `evals/golden.jsonl`, `evals/experiment-manifest.json` | — |
| Exact, paraphrase, table, multi-document, stale, unanswerable coverage | PASS | evaluation corpus and report | — |
| Prompt-injection and tenant-isolation disposition | PASS | explicit non-ranking dispositions in `evals/golden.jsonl`; deterministic injection and tenant adversarial suites on `main` | — |
| Dense baseline | PASS | committed evaluation JSON/report | — |
| Sparse baseline | PASS | selectable standalone `sparse` profile and v3 semantic/deterministic artifacts | — |
| Hybrid and reranked baselines | PASS | committed deterministic and semantic reports | — |
| Quality, latency, memory, and index-time records | PASS | evaluation reports and raw case exports | — |
| Cost baseline | PASS | v3 run metadata records estimated provider cost USD 0.00 and scope of the assumption | — |
| Reuse registry | PASS | `THIRD_PARTY_REUSE.md` and benchmark manifests | verify additions remain current |
| Clean-checkout reproduction | PASS | detached clean worktree at `fd05097`; 48 tests, fresh Docker build, healthy no-key container, default sparse query with five sources | — |

Phase A0 transition passed. The signed transition record is below.

### Phase A1 — parsing, chunking, and retrieval bake-offs: PASS

| Requirement | Status | Existing evidence | Missing evidence |
| --- | --- | --- | --- |
| Current parser vs Docling vs Unstructured | PASS | seven pinned fixtures and `docs/parsing-benchmark-v2.json`; pypdf, Docling, forced RapidOCR, Unstructured-fast/OCR profiles | — |
| Text and table-heavy parsing | PASS | committed fixtures and comparison report | — |
| Scanned-document parsing | PASS | pinned scanned PDF; Docling default and forced RapidOCR both recover every anchor; pypdf/Unstructured failures recorded | — |
| Office-document parsing | PASS | pinned rich-table DOCX; Docling preserves 34 Markdown table rows; Unstructured flattening recorded | — |
| HTML parsing | PASS | pinned rich-table HTML; Docling preserves 22 Markdown table rows; Unstructured flattening recorded | — |
| Fixed vs heading-aware vs parent-child chunking | PASS | chunking benchmark/report | — |
| Additional research-informed hierarchical method | PASS | Docling `HybridChunker`, frozen sparse/hybrid v2 artifacts, and `docs/chunking-bakeoff.md` | — |
| Current embedding vs BGE-M3 | PASS | same-corpus dense/hybrid comparison, aggregate and 200 per-case records, cost/resource metrics | — |
| Benchmark-shortlisted API embedding | PASS | tested OpenAI-compatible adapter; `text-embedding-3-large` 1,024d manifest; explicit credential gate and command | — |
| No reranker vs BGE cross-encoder vs ColBERT | PASS | reranker benchmark and keep/reject report | — |
| Per-category failure analysis and final winner table | PASS | `docs/phase-a1-decision-matrix.md` consolidates parser, chunker, embedding, retrieval, and reranker decisions | — |

Phase A1 transition passed. The signed transition record is below.

### Phase A2 — retrieval and evaluation core: PASS

| Requirement | Status | Existing evidence | Missing evidence |
| --- | --- | --- | --- |
| Replaceable embedding/reranker/retrieval interfaces | PASS | `app/embeddings.py`, `app/retrieval.py`, service/storage seams | — |
| Integrate only measured winners | PASS | A1 decision matrix and bundled defaults: pypdf for ordinary text PDF, fixed chunking, BGE-small local embedding, sparse retrieval, no learned interactive reranker | — |
| Deterministic retrieval metrics | PASS | evaluation runner and raw exports | — |
| Selective semantic answer/citation evaluation | PASS | `app/semantic_evaluation.py`, pinned HHEM revision, 20-case manifest, aggregate JSON and per-case JSONL, positive/negative controls | — |
| Request retrieval trace | PASS | API response trace and tests | — |
| Side-by-side comparison API | PASS | typed `POST /api/evaluations/compare` endpoint and API tests | — |
| No-key mode | PASS | hash embeddings and extractive generator | — |
| Profile winner by test category | PASS | `docs/profile-winner-matrix.md` consolidates winners, ties, no-winner categories, and promotion rules | — |

Phase A2 transition passed. The signed transition record is below.

### Phase B — ingestion, trust, workspace boundary: PASS

The plan defines Phase B as six bullets. The first table covers the bullets
closed before this branch; the second covers the parser/connector/synchronization
bullet closed on `agent/atlas-phase-b-closure`. Both are part of the same gate.

#### Phase B scope closed earlier and re-verified on this branch

| Requirement | Status | Evidence |
| --- | --- | --- |
| Document checksum, source URI, immutable versions, re-index | PASS | `DocumentRecord.sha256/source_uri/version/supersedes_document_id`; `KnowledgeStore.replace_document`; `PUT /api/documents/{id}`; `tests/test_api.py::test_reindex_creates_version_history_and_hides_stale_vectors`; live re-index produced v2 with v1 `superseded` |
| Complete deletion with no orphaned vectors | PASS | `KnowledgeStore.delete_document` tombstones every version before removing points and restores state on vector-store failure; `tests/test_document_lifecycle.py::test_failed_vector_delete_restores_document_state`; offline audit reported `orphaned_document_ids: []` |
| Asynchronous job states | PASS | `app/jobs.py` queued/running/succeeded/failed/cancelled/dead_letter with attempt budget, cooperative cancellation, replay, and startup recovery; `tests/test_ingestion_jobs.py` |
| Tenant/collection/ACL metadata and isolation tests | PASS | `app/access.py`; SQLite and Qdrant filters applied before ranking; `tests/test_tenant_acl.py` adversarial suite; live tenant `globex` saw 0 documents, 0 sources, HTTP 404 on another tenant's job |
| OpenTelemetry/Phoenix tracing for ingestion, retrieval and generation | PASS | span inventory table in `docs/observability.md`; `atlas.rag.query`, `atlas.rag.retrieve`, `atlas.rag.generate`, `atlas.ingestion.*`, `atlas.connector.sync`; pinned Phoenix Compose overlay with a verified OTLP round-trip |
| Tracing covers latency | PASS | `atlas.query.duration_ms`, `atlas.retrieval.duration_ms`, `atlas.generation.duration_ms`; `RetrievalTrace.retrieval_ms/rerank_ms` and `GenerationTrace.generation_ms` in the API response |
| Tracing covers token use | PASS | `GenerationResult`/`GenerationTrace` carry provider-reported `prompt_tokens`, `completion_tokens`, `total_tokens` plus `context_sources`/`context_characters`; emitted as `gen_ai.usage.input_tokens`/`output_tokens`/`total_tokens`; `tests/test_generation_accounting.py` proves counts are `null` and attributes absent rather than zero when a provider omits usage |
| Tracing covers failures | PASS | `atlas.ingestion.job` records the exception and `atlas.job.outcome`; `http.request.failed` and `connector.item.failed` structured events; `tests/test_observability_security.py` |
| Deterministic injection tests on every CI run | PASS | `.github/workflows/ci.yml` runs `ruff check .` and the full `pytest` suite, which includes the direct and indirect injection cases in `tests/test_observability_security.py`; `app/security.py` flags and quarantines source instructions; `tests/test_connector_url.py::test_prompt_injection_in_fetched_content_is_flagged` extends the control to fetched connector content |
| Bounded garak release profile | PASS | `security/garak-atlas-rest.json` and the documented bounded command in `docs/observability.md`, with the explicit statement that it is not proof of general injection resistance |

#### Phase B parser, connector and synchronization scope

| Requirement | Status | Evidence |
| --- | --- | --- |
| Replaceable parser registry for PDF, Markdown, TXT, DOCX, HTML, URL content, CSV | PASS | `app/parsers.py`; `ParserRegistry.register` seam and replacement test in `tests/test_parser_registry.py`; `GET /api/connectors` reports the six routed formats |
| Measured parser decisions applied, no unmeasured universal default | PASS | `docs/parser-registry-v1.json` + `docs/parser-registry-artifacts-v1`; pypdf keeps ordinary text PDFs, empty text layer escalates to Docling, DOCX/HTML prefer Docling when installed; fallbacks report `degraded=true` |
| Metadata, source URI, version and structure preserved | PASS | `SyncItemResult.parser`, `ParsedDocument.structure`, `DocumentRecord.connector_name/connector_instance`, citation `source_uri`/`document_version`/`document_sha256` |
| Connector interface with local-folder and URL implementations | PASS | `app/connectors/base.py`, `local_folder.py`, `web.py`; no Google Drive OAuth added |
| Stable source IDs and canonical source URIs | PASS | `stable_source_id`; `local://<root>/<path>` and canonical http/https URLs; version-continuity test |
| Discover/fetch/delete lifecycle | PASS | `app/sync.py`; live demo sections 1, 4 and 5 below |
| Checksum-based unchanged-file skipping | PASS | `test_unchanged_content_is_skipped_without_creating_versions`; live unchanged sync reported `unchanged=3, created=0` |
| Immutable version creation when content changes | PASS | `test_changed_content_creates_a_new_version_and_retires_stale_vectors`; live re-index produced v2 with `supersedes_document_id` and v1 `superseded` |
| Removal of vectors belonging to stale versions | PASS | offline index audit reported `orphaned_document_ids: []` and 0 vector points on `superseded`/`archived` rows |
| Explicit behaviour when an upstream item disappears | PASS | `ATLAS_CONNECTOR_DELETION_POLICY` (`archive` default, `delete` selectable) documented in `docs/connectors.md`; both policies tested; live archive demonstrated |
| Idempotent repeated synchronization | PASS | `test_repeated_sync_is_idempotent`; `Idempotency-Key` job test; live repeat run performed no writes |
| Durable job progress, failures, retries, cancellation | PASS | `tests/test_connector_sync_jobs.py`; job rows carry kind, connector identity, config and the persisted `SyncReport` |
| Partial failure does not corrupt indexed content | PASS | `test_partial_failure_does_not_corrupt_already_indexed_content`, `test_one_failing_item_leaves_the_other_documents_indexed`, `test_cancelling_a_running_sync_keeps_already_indexed_documents` |
| Tenant, collection and ACL boundaries enforced | PASS | `test_another_tenant_cannot_see_or_replace_synchronized_documents`, `test_restricted_visibility_is_applied_to_synchronized_documents`, `test_another_tenant_cannot_read_or_control_a_sync_job`; live tenant `globex` saw 0 documents, 0 sources, HTTP 404 on the other tenant's job |
| Local paths stay inside configured roots; traversal and symlink escapes rejected | PASS | `test_path_traversal_is_rejected`, `test_symlinked_subpath_outside_the_root_is_rejected`, `test_symlinked_file_inside_the_root_is_never_followed`, `test_item_fetch_refuses_a_path_that_leaves_the_root`; symlink cases executed on Linux in the clean-container run |
| URL connector accepts only HTTP/HTTPS and rejects embedded credentials | PASS | `test_only_http_and_https_are_accepted`, `test_embedded_credentials_are_rejected`; live rejections in section 7 |
| Loopback, private, link-local, reserved and metadata targets blocked | PASS | `test_internal_targets_are_blocked_by_default`, `test_metadata_addresses_are_blocked_even_when_private_networks_are_allowed`, `test_metadata_hostnames_are_blocked` |
| Redirect targets and resolved addresses revalidated | PASS | `test_redirect_to_an_internal_address_is_rejected`, `test_redirect_to_a_forbidden_scheme_is_rejected`, `test_a_peer_outside_the_validated_set_is_rejected`, `test_a_peer_inside_a_blocked_range_is_rejected` |
| Redirects, response size and timeouts bounded | PASS | `test_redirect_chains_are_bounded`, `test_declared_oversized_response_is_rejected_before_download`, `test_streamed_oversized_response_is_aborted`; `ATLAS_CONNECTOR_URL_TIMEOUT_SECONDS` |
| Supported content types validated | PASS | `test_unsupported_content_type_is_rejected`; live demo showed `application/octet-stream` refused by design |
| Existing prompt-injection controls preserved | PASS | `test_prompt_injection_in_fetched_content_is_flagged`; connector chunks pass through the same `security_flags` path |
| Connector secrets never exposed | PASS | `describe()` returns root names and counts only; `test_connector_description_never_exposes_the_absolute_root`, `test_connector_description_hides_the_configured_urls`, `test_connector_catalogue_lists_roots_without_absolute_paths` |
| Reuse and design influences recorded | PASS | `THIRD_PARTY_REUSE.md` "Parser and connector design references" |
| Complete lint suite | PASS | `ruff check .` clean on Windows and in the clean Linux container |
| Complete test suite with coverage | PASS | clean container, core install: 178 passed, 85% coverage, 5 skipped — exactly the Docling-gated cases, which run in the `quality-parser` workflow instead |
| Fresh Docker image and live no-key container | PASS | `atlas-phase-b-gate:2057019`; readiness `ready`, Docker health `healthy`, full connector lifecycle demonstrated |

Phase B exit gate from the plan — "connector sync, re-index, delete, failure,
and cross-tenant tests pass" — is satisfied by
`tests/test_connector_local_folder.py`, `tests/test_connector_url.py`,
`tests/test_connector_sync_jobs.py`, `tests/test_api.py`,
`tests/test_document_lifecycle.py`, `tests/test_ingestion_jobs.py`, and
`tests/test_tenant_acl.py`.

Phase B transition passed. The signed transition record is below.

### Frontend and publishing: NOT STARTED OR INCOMPLETE

Phase C is defined as completing views *inside* the UI2 foundation, so the
frontend work starts at UI2, not at C.

| Phase | Status | Open items |
| --- | --- | --- |
| UI0 visual architecture and reuse decision | PASS | complete per `PORTFOLIO_UI_DESIGN_RESEARCH_2026-07-30.md` |
| UI1 five product-shell specifications | PARTIAL | Atlas is closed by `docs/ui2-atlas-shell.md`: collapse rules, token set, component inventory and seeded-data spec. The other four products' collapse rules and annotations remain open, and they are not needed before Atlas UI2 |
| UI2 Atlas frontend foundation | PASS — merge pending | Vite/React/TypeScript shell, real API client, Sources and connector flows, accessible trace dialog, opt-in answer streaming with retraction, production FastAPI/Docker serving, 63 Playwright tests across 1440/1024/390, zero candidate axe violations, console guard, measured legacy comparison, and human visual review all pass. assistant-ui is rejected until multi-turn exists; no important unreachable state justified Storybook. |
| C Atlas frontend completion | NOT STARTED | ingestion, streaming, evidence, trace, evaluation views plus every state introduced by phases A and B, including the connector surface which is API-only today |
| D publish and use Atlas as the pattern | NOT STARTED | release, refreshed media, README animation, captioned video, client adaptation guide |

The Atlas direction UI2 must implement is already specific in the design
research: no permanent left navigation in the primary research view, a compact
global header carrying workspace/scope/index health, a collapsible query rail, a
dominant answer canvas, an evidence pane bound to citation markers, an on-demand
trace rail, and an evaluation comparison table rather than KPI cards. Visual
character is a quiet editorial research tool on a warm light neutral with ink
violet accent.

The 2026-08-01 cross-portfolio plan supersedes the former requirement to keep
Atlas active through Phase D. After UI2 merges, pause Atlas and start
ContextSidecar C0. Phase C remains planned but is not the next workstream.

## Exact next action

Phase B is closed at `59647e4`; UI2 is closed and merged at `4b4288f`. Atlas is
paused. Read the cross-portfolio plan and
`portfolio_demos/REALTIME_CONTEXT_COPILOT_PLAN_2026-08-01.md`, then create the
ContextSidecar repository, isolated `context_sidecar_c0` worktree,
`agent/context-sidecar-c0` branch, and C0 checkpoint. Begin with the frozen
evaluation corpus and the system-audio, ephemeral-credential transcription,
and screenshot-confirmation spikes.

Closed UI2 decisions:

1. **assistant-ui is not justified, and streaming did not change that.**
   Streaming now exists (`POST /api/query/stream`), which removes the first
   objection. The remaining one is larger: Atlas is single-turn. There is no
   conversation history, no thread, and no follow-up question that resolves
   against a previous answer. assistant-ui exists to manage threads, message
   lists and multi-turn interaction state, so adopting it now would import a
   runtime whose main surface is unused. The plan does list "conversation memory
   separated from the authoritative knowledge index" as a target; that is the
   work that would justify the library. Sequence: multi-turn conversation, then
   assistant-ui — or drop assistant-ui if Atlas stays single-turn, which is a
   defensible product choice for a research workbench.
2. The paired legacy/candidate screenshots passed human review at 1440, 1024,
   and 390 px. The candidate has a clearer question-answer-evidence hierarchy,
   responsive collapse without clipping, readable typography, and an
   intentional rather than broken pre-query empty state.
3. Storybook is not added. All important product states are reachable through
   the real API and covered at every target width. No important unreachable
   state remained to justify a second, weaker fixture pipeline.

Control adoption is deliberately partial and should stay that way unless a
specific control proves inadequate: Radix Dialog supplies the focus trap, focus
restore and escape handling the hand-rolled drawer lacked, while native
`select`, `input` and `textarea` are kept because a native select is more
accessible than a custom one — especially on touch — and shadcn would require
Tailwind, which fights the product-local token system.

The served frontend transition is complete. FastAPI serves `frontend/dist`
when built; the Docker image builds it in a pinned Node 22 stage. The released
static shell remains only as a backend-only no-build fallback and at
`/legacy-ui2-comparison` so the comparison remains honest after `/` changes.

## UI2 verification so far

- `npm run build` in `frontend/` runs `tsc --noEmit` then a production build;
  both pass.
- `npx playwright test` starts the real API and the dev server and runs 63
  tests across 1440 px, 1024 px and 390 px: live index health, prepared case to
  cited answer, citation-to-evidence binding, the trace drawer including the
  "not reported" token contract, abstention, no horizontal page scroll,
  keyboard reachability, the connector surface, and an SSRF rejection carrying
  the API's own reason. Every test fails on any console error, and one asserts
  an empty axe result set at WCAG 2.2 AA.
- Streaming: `POST /api/query/stream` emits `sources`, then `delta`, then
  `trace`, with retrieval finished before any answer text. It is **opt-in** and
  `POST /api/query` remains the default, because the buffered path refuses an
  uncited answer before the caller sees it while streaming can only retract one
  afterwards. A `retracted` event carries that failure and the shell marks the
  answer as disowned rather than keeping it silently. Remote-resource markup
  aborts the stream mid-flight. Both paths share one request builder and one
  citation check so the contracts cannot drift, and `stream_options.include_usage`
  keeps token accounting alive under streaming. The extractive provider reports
  `streams: false` rather than faking deltas.
- State coverage is driven through the real API rather than fixtures: upload
  success and complete deletion, unsupported format refused with the server's
  own 422 reason and explicitly not shown as a server fault, empty document
  refused, duplicate content refused as a conflict, re-index producing version 2
  with version 1 `superseded` in the history table, an embedded-instruction
  source flagged in the evidence pane, an unsupported asynchronous upload
  reaching `dead_letter` with `error_type: UnsupportedDocumentError`, and
  another tenant seeing no documents and no query sources.
- `.github/workflows/frontend.yml` runs the same checks on changes to
  `frontend/**` or `app/**`.
- Measured comparison against the released static frontend, both audited with
  the same axe configuration at the same widths:

  | Shell | 1440 px | 1024 px | 390 px |
  | --- | --- | --- | --- |
  | released static frontend | 19 violating nodes | 19 | 18 |
  | UI2 candidate | 0 | 0 | 0 |

  Every legacy violation is `color-contrast`, rated serious. **The released
  Atlas interface therefore ships with serious contrast failures**, which is a
  finding about the current product and not only about its replacement. If UI2
  is abandoned or delayed, the legacy palette still needs fixing.

- Human comparison of the paired screenshots passed at 1440, 1024, and 390 px.
  The candidate improves scan order and information hierarchy, preserves a
  dedicated evidence surface, collapses navigation deliberately, and shows no
  clipping, misalignment, or accidental horizontal overflow. The pre-query
  whitespace is intentional focus, not missing layout.
- Storybook disposition: not adopted. The 63 real-API browser tests cover every
  important reachable success, refusal, failure, tenant, connector, streaming,
  evidence, trace, and responsive state. No remaining important state is only
  producible by a fixture.
- Final 2026-08-01 verification on application commit `986e793` plus this
  checkpoint change:
  - `.venv\Scripts\python.exe -m ruff check .` — pass;
  - `.venv\Scripts\python.exe -m pytest` — 186 passed, 7 skipped, one
    upstream Starlette deprecation warning;
  - `npm run build` — TypeScript and Vite production build pass;
  - `npx playwright test` — 63 passed across all three widths; candidate zero
    axe violations versus legacy 19/19/18 violating nodes;
  - `docker build --tag atlas-ui2-gate:ac8feb9 .` — pass with the Node build
    stage and Python runtime image;
  - live container in hash/extractive mode — readiness `ready`, `/` HTTP 200
    with the UI2 title, built JavaScript asset HTTP 200, `/api/health` reports
    six documents. The temporary verification container was then removed.

## UI2 pre-merge gate ledger

| Requirement | Status | Evidence |
| --- | --- | --- |
| Human legacy/candidate visual comparison | PASS | paired Playwright screenshots reviewed at 1440/1024/390; findings above |
| Composition, typography, hierarchy, and responsive behavior | PASS | human review plus no-horizontal-scroll checks at every width |
| Important reachable product states | PASS | 63 browser tests drive the real API |
| Important unreachable states / Storybook disposition | PASS | none remain; Storybook rejected as duplicate weaker proof |
| Accessibility and keyboard behavior | PASS | zero candidate axe violations; keyboard workflow test at every width |
| Frontend build | PASS | `npm run build` |
| Backend regression | PASS | Ruff clean; 186 passed, 7 skipped |
| Production served frontend | PASS | multistage Docker build and live root/asset/API verification |
| Honest legacy comparison after root transition | PASS | dedicated comparison route restores 19/19/18 vs 0/0/0 measurement |
| assistant-ui decision | PASS | deferred until real multi-turn/thread state exists |
| Branch hygiene | PASS | application candidate committed at `986e793`; no unrelated scope |
| Merge and synchronized main | PASS | branch merged at `4b4288f`; push verified `main == origin/main` at `4b4288f` on 2026-08-01 |

## Phase transition record — UI2 to ContextSidecar pause

- Exit gate: UI2 `PASS`; every row in the UI2 ledger has command, artifact,
  commit, or recorded human-review evidence.
- Candidate branch and commits: `agent/atlas-ui2-foundation`; application
  candidate `986e793`; pre-merge checkpoint `6864f1f`.
- Merged commit: `4b4288f29cf63924a2f8dcfb951cac614408b1ce`.
- Remote verification: `main` and `origin/main` both resolved to `4b4288f` after
  push on 2026-08-01.
- Scope delivered: React/TypeScript research shell, real API integration,
  source/connector management, evidence and trace surfaces, opt-in streaming
  with explicit retraction, responsive/accessibility coverage, and production
  FastAPI/Docker serving.
- Verification: Ruff pass; 186 backend tests passed with 7 expected skips;
  production frontend build pass; 63 Playwright tests passed at 1440/1024/390;
  candidate axe results 0/0/0 versus legacy 19/19/18; Docker build and live
  root/asset/readiness checks passed.
- Human review: composition, typography, information hierarchy, collapse, and
  responsive behavior passed at all three captured widths.
- Reuse decisions: Radix Dialog retained; assistant-ui deferred until actual
  multi-turn state exists; Storybook rejected because no important state
  remained outside the stronger real-API test matrix.
- Known residual risks: the backend-only no-build path deliberately falls back
  to the previous shell; a production build or Docker image serves UI2. The
  legacy comparison route remains to preserve the measured baseline.
- Next phase: Atlas Phase C is intentionally paused. Exact first action is
  ContextSidecar C0 in a new repository/worktree under the authoritative
  cross-portfolio and realtime-copilot plans.

- Eight defects were found by running the shell rather than by reading it. Two
  came from the streaming work: an answer could be displayed and then only
  implicitly disowned, and the first implementation held
  `start_as_current_span` across the generator's yields, so OpenTelemetry logged
  "Failed to detach context" on every streamed request — found by reading the
  test log, not by any assertion. The other six: two
  contrast failures in the token set — the second visible only on the violet
  active-card wash, a background the first check omitted — a header that
  overflowed 390 px, a "deliberately unanswerable" prepared case that was not
  unanswerable, a trace panel that claimed `aria-modal="false"` with no focus
  management, and a provider label that the responsive rules deleted instead of
  relocating.

## Mandatory phase-transition record

Before moving from any phase, add a record here containing:

- phase and exit-gate status: all `PASS`;
- evidence artifacts and commands;
- test/build/container results;
- branch and merged commit;
- known residual risks;
- exact next phase and first action.

If that record is absent, the next phase is not authorized by the plan.

## Phase transition record — A0 to A1

- Exit gate: Phase A0 `PASS`; every ledger row above has concrete evidence.
- Candidate branch and commit: `agent/atlas-phase-a-closure` at `fd05097`.
- Frozen evidence:
  `docs/evaluation-semantic-baseline-v3.json`,
  `docs/evaluation-semantic-baseline-v3-cases.jsonl`,
  `docs/evaluation-deterministic-baseline-v3.json`, and
  `docs/evaluation-deterministic-baseline-v3-cases.jsonl`.
- Quality decision: sparse wins the bundled held-out corpus; hybrid remains
  selectable and must re-earn promotion on representative client questions.
- Verification: lint clean; 48 tests passed; 89% coverage; JSON artifacts
  parsed; detached clean-checkout tests passed; fresh Docker build passed;
  live readiness and default sparse query returned five cited sources.
- Known residual risks: the six-document corpus retains lexical signal even in
  paraphrase cases; latency is a single-machine snapshot; no retrieval profile
  solves held-out abstention.
- Next phase: A1. First action is the scanned/DOCX/HTML parser-fixture expansion
  and controlled parser comparison.

## Completed Phase A1 slice — parser routing

- Evidence: `docs/parsing-benchmark-v2.json`,
  `docs/parsing-artifacts-v2`, and seven pinned fixtures in `evals/parsing`.
- Result: Docling passed all seven fixtures with full anchor recall and retained
  the tested PDF/DOCX/HTML structure. The lightweight parser remains the fast
  ordinary-text PDF path. Default Docling OCR beat forced full-page RapidOCR on
  the scanned case. Unstructured-fast flattened the structured tables, and
  Unstructured OCR-only failed explicitly without the external Tesseract
  executable.
- Verification: empty output is treated as a failed parse; focused lint and
  three parser benchmark tests pass; machine-readable output parses as JSON.
- Residual risk: references are Docling-generated and representation-biased, so
  adoption uses anchors, structure, failures, and latency rather than token F1
  alone.
- Next action: additional hierarchical retrieval method on frozen cases.

## Completed Phase A1 slice — chunking

- Evidence: `docs/chunking-semantic-sparse-v2.json`,
  `docs/chunking-semantic-hybrid-v2.json`, their per-case JSONL exports, and
  `docs/chunking-bakeoff.md`.
- Method: fixed, heading-aware, parent-child, and Docling `HybridChunker` ran
  against the same 50 cases under separate sparse and hybrid retrieval
  profiles. Docling used the BGE-small tokenizer limit, hierarchy context, and
  peer merging.
- Result: fixed remains the default. It alone retained complete held-out source
  recall in both retrieval runs, used 19 rather than 51 records, and avoided
  Docling's roughly 17.5-second local index build. The advanced method is kept
  selectable but was not promoted without a measured win.
- Verification: all aggregate and per-case artifacts parse, and the controlled
  manifest records the adoption gate and both retrieval profiles.
- Residual risk: the six-document fixture cannot represent every long-document
  structure; the bake-off must be rerun on client files before selecting a
  production chunker.
- Next action: current embedding versus BGE-M3 on the unchanged frozen cases.

## Phase transition record — A1 to A2

- Exit gate: Phase A1 `PASS`; every ledger row has controlled evidence,
  per-category failures, and an explicit keep/reject decision.
- Candidate branch and evidence commit:
  `agent/atlas-phase-a-closure` at `f3692a2`.
- Evidence:
  `docs/parsing-benchmark-v2.json`,
  `docs/chunking-semantic-sparse-v2.json`,
  `docs/chunking-semantic-hybrid-v2.json`,
  `docs/embedding-benchmark-v1.json`,
  `docs/embedding-benchmark-v1-cases.jsonl`,
  `docs/reranker-semantic.json`, and
  `docs/phase-a1-decision-matrix.md`.
- Quality decisions: route ordinary text PDFs through pypdf and structured or
  scanned formats through Docling; keep fixed chunking, BGE small, sparse
  retrieval, and no learned interactive reranker as the bundled deployment
  profile. BGE-M3 wins aggregate dense/hybrid ranking but loses
  multi-document category ranking and is retained for client-specific
  multilingual/long-context measurements.
- Hosted embedding disposition: `text-embedding-3-large` at 1,024 dimensions
  has a tested provider adapter, pinned manifest inputs, a required credential
  variable, token-cost accounting, and an exact command. With no key present,
  the artifact records `credential_required` and null results.
- Verification: lint clean; 54 tests passed; embedding aggregate JSON parsed;
  200 local per-case rows recorded; missing hosted credentials never produce
  substituted or fabricated metrics.
- Known residual risks: parser references are representation-biased; six
  documents cannot cover all hierarchy or multilingual cases; BGE-M3 resident
  memory is a sequential-process snapshot; hosted quality and cost remain
  unmeasured until a credentialed run.
- Next phase: A2. First action is selective semantic answer/faithfulness and
  citation-correctness evaluation on frozen cases.

## Phase transition record — A2 to B

- Exit gate: Phase A2 `PASS`; every ledger row has executable code, a typed
  interface, or a committed evidence artifact.
- Candidate branch and code/evidence commit:
  `agent/atlas-phase-a-closure` at
  `d65bb8d83448f4b6708fa4059e7b01ff8703405f`.
- Evidence:
  `docs/semantic-evaluation-v1.json`,
  `docs/semantic-evaluation-v1-cases.jsonl`,
  `docs/semantic-evaluation.md`,
  `docs/profile-winner-matrix.md`, and
  `evals/semantic-evaluation-manifest.json`.
- Semantic result: 20 enabled frozen cases, 52 valid citation links, 1.0
  citation validity/completeness/exact support, 0.973520 mean HHEM semantic
  citation and answer support, 0.939087 supported control, and 0.007601
  unsupported control. The HHEM model revision is pinned. The run records zero
  provider cost and does not require an API key.
- Retrieval decision: sparse remains the bundled default. Dense or hybrid wins
  only the boundary category; table is a three-way tie; unanswerable and
  collection-filter categories have no winner. The side-by-side endpoint makes
  profiles directly comparable without promoting an unmeasured choice.
- Verification: lint clean; 59 tests passed; 82% total coverage; JSON artifacts
  parsed; Docker image `atlas-a2-gate:d65bb8d` built from the clean candidate;
  live no-key readiness returned `ready`; a sparse query returned five cited
  sources; sparse/hybrid comparison returned two source-backed results.
- Known residual risks: HHEM is a reproducible judge rather than ground truth;
  the two unanswerable/filter cases both failed abstention, so semantic
  faithfulness does not establish question relevance; the frozen six-document
  corpus is small; a Starlette deprecation warning remains; hosted embedding
  quality remains credential-gated.
- Next phase: B. First action is the parser registry and connector contract,
  followed by local-folder and URL synchronization with lifecycle and security
  tests. Use only the dedicated Phase B worktree and branch named above.

## Phase transition record — B to UI2/C

- Exit gate: Phase B `PASS`. Every row in the Phase B ledger above has
  executable code, a committed artifact, or a recorded command result. No row
  is `PARTIAL`, `FAIL`, or `UNVERIFIED`.
- Candidate branch and verified evidence commit:
  `agent/atlas-phase-b-closure` at `2057019`. This checkpoint update is the
  documentation-only commit that follows it.
- Scope delivered: replaceable parser registry for PDF, Markdown, plain text,
  DOCX, HTML, URL content and CSV; connector contract with local-folder and
  URL implementations; a synchronization engine owning identity, checksums,
  immutable versions, deletion policy, ownership and partial-failure
  isolation; connector runs carried by the existing durable job store;
  generation token-use, context-size and stage-latency accounting; and
  ingestion spans on the connector path.
- Correction made during closure: the first pass at this gate recorded only the
  parser/connector/synchronization bullet and left the other five Phase B
  bullets without ledger rows. Re-reading the plan against the implementation
  also showed that the "token use" half of the tracing bullet had never been
  implemented — the OpenAI-compatible generator discarded the provider usage
  block — and that connector items emitted no ingestion spans. Both were
  implemented and tested rather than documented away.
- Evidence artifacts: `docs/parser-registry-v1.json`,
  `docs/parser-registry-artifacts-v1/`, `docs/connectors.md`,
  `docs/observability.md`, `THIRD_PARTY_REUSE.md`, `app/parsers.py`,
  `app/connectors/`, `app/sync.py`, and `tests/test_parser_registry.py`,
  `tests/test_connector_local_folder.py`, `tests/test_connector_url.py`,
  `tests/test_connector_sync_jobs.py`,
  `tests/test_generation_accounting.py`.
- Commands:
  - `python -m app.parsing_benchmark --providers atlas-registry --output docs/parser-registry-v1.json --artifacts-dir docs/parser-registry-artifacts-v1`
  - `ruff check .`
  - `pytest -q --cov=app --cov-report=term-missing`
  - `docker build -t atlas-phase-b-gate:2057019 .`
  - clean-tree container run:
    `git archive HEAD | tar -x -C <clean>` then
    `docker run --rm -v <clean>:/src -w /src python:3.11-slim bash -lc "pip install -e '.[dev]' && ruff check . && pytest -o addopts= -q --cov=app --cov-report=term"`
- Test and build results: lint clean; in the clean Linux container on the core
  dependency set, 178 tests passed with 85% total coverage and 5 skipped. The
  skips are exactly the Docling-gated cases, which the `quality-parser`
  workflow runs with the extra installed. The symlink-escape cases executed
  rather than being skipped as they are on Windows. Fresh Docker image built;
  live no-key container reported
  `{"status":"ready","checks":{"metadata":"ok","ingestion_jobs":"ok"}}` and
  Docker health `healthy`.
- Token-use evidence: an in-memory OpenTelemetry exporter asserts that
  `atlas.rag.generate` carries `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens` and `gen_ai.usage.total_tokens` when a provider
  reports usage, that the parent query span carries the total, that those
  attributes are **absent** rather than zero in no-key mode, and that no
  question, answer, or passage text reaches any span. The live container
  returned
  `{"provider":"extractive","context_sources":1,"context_characters":52,"prompt_tokens":null,"completion_tokens":null,"total_tokens":null,"generation_ms":0}`,
  which is the correct no-key shape.
- Parser-routing result with core dependencies only: pypdf handled every
  ordinary text PDF fixture; the scanned fixture failed explicitly with the
  Docling instruction instead of indexing an empty document; the DOCX and HTML
  fallbacks recovered every anchor and 30 of 34 and 21 of 22 reference table
  rows respectively, which is why Docling remains the route whenever installed.
- Live local-folder lifecycle (tenant `acme`, three files):
  initial sync `discovered=3, created=3`; query cited
  `local://handbook/routing.md` v1; unchanged sync `unchanged=3, created=0`;
  changed content `updated=1, unchanged=2` producing v2 with
  `supersedes_document_id` set and v1 `superseded`; upstream deletion
  `discovered=2, removed=1` archiving `local://handbook/retention.md`, after
  which its content was no longer retrievable.
- Live URL lifecycle (validated http against a sidecar server with the explicit
  private-network opt-in): initial sync `created=1` parsed by the HTML route;
  query cited the fetched URL; unchanged sync `unchanged=1`; changed content
  `updated=1` producing v2; removing the URL from the instance archived the
  document and left 0 retrievable sources.
- Orphaned-vector audit: an offline pass over both persisted indexes reported
  `orphaned_document_ids: []` and `indexed_without_vectors: []`, with every
  `superseded` and `archived` row holding 0 vector points.
- Tenant isolation in the live container: tenant `globex` saw 0 documents and
  0 query sources for tenant `acme` content, and received HTTP 404 reading the
  other tenant's synchronization job.
- Live security rejections: cloud metadata address, `file://` scheme, embedded
  credentials, and a `../..` subpath were each rejected with HTTP 422 before
  any job row was written.
- Known residual risks:
  - token use is only as good as the provider's `usage` block; a provider that
    omits it leaves the counts null, and Atlas will not estimate them;
  - the DOCX and HTML fallbacks lose merged table rows; a client deployment
    that depends on complex tables must install the Docling extra, and Atlas
    reports those results as `degraded` rather than as the measured route;
  - **closed below** — Docling was not exercised in CI;
  - **closed below** — token-use span attributes were only unit-verified;
  - peer-address verification depends on the HTTP transport exposing the
    connected address; when it does not, the pre-flight DNS validation is the
    only rebinding control;
  - the URL connector derives its instance identity from the URL set unless an
    explicit `instance_id` is supplied, so a changing URL list without one will
    not retire dropped documents;
  - `ATLAS_CONNECTOR_URL_ALLOW_PRIVATE_NETWORKS` is a real operator escape
    hatch; only metadata targets stay blocked in that mode;
  - connector synchronization runs on the same single local worker as uploads,
    which remains a public-demo profile rather than distributed execution;
  - the Starlette test-client deprecation warning remains.
- Next phase: UI2, then C. First action is scaffolding the Vite/React/
  TypeScript foundation beside the preserved static frontend in a new
  `atlas_ui2` worktree on `agent/atlas-ui2-foundation`. No frontend work
  belongs in the Phase B worktree.

## Phase B residual-risk closure

Two risks recorded in the transition record above were closed rather than
carried into UI2. The rest of the risk list stands.

### Closed — token-use span attributes were only unit-verified

The concern was that `gen_ai.usage.*` had never been observed arriving in a
collector, because the no-key profile has no tokens to report and no credential
was available.

Closed without a credential by pointing Atlas at a deterministic
OpenAI-compatible stub that returns a `usage` block, running it against the
pinned Phoenix overlay, and reading the span back through the Phoenix API.
Reproduction is documented in `docs/observability.md` under
"Verifying token use without a paid provider".

Result read from `GET /v1/projects/default/spans` on `atlas.rag.generate`:

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

`atlas.rag.query` carried `gen_ai.usage.total_tokens: 1290`, and the query
response body carried the matching typed generation trace. Phoenix mapped the
standard `gen_ai.usage.*` attributes into its own `llm.token_count.*`
convention on its own, so its token and cost views work without Atlas emitting
anything vendor-specific. The full span set recorded in Phoenix was
`atlas.rag.query`, `atlas.rag.retrieve`, `atlas.rag.generate`,
`atlas.ingestion.extract`, `atlas.ingestion.chunk`, `atlas.ingestion.index`,
and the FastAPI server spans.

### Closed — the Docling quality route was unexecuted code

The recorded risk was that Docling is not exercised in CI. Investigating it
found something worse: the shipped adapter in `app/parsers.py` had never run at
all. Phase A1 measured Docling through `app/parsing_benchmark.py`, which calls
the path-based `convert(path)`; the registry adapter calls the stream-based
`convert(DocumentStream)`. Different code, no coverage.

Closed by installing the extra and running it. Evidence
`docs/parser-registry-docling-v1.json`, produced on Linux because torch's
nested license paths exceed the Windows path limit:

| Fixture | Route taken | Result |
| --- | --- | --- |
| `ocr_test` scanned PDF | escalated to Docling | anchor recall 1.0 — an explicit failure on the core install |
| `word_tables` DOCX | Docling | 34 of 34 reference table rows — the fallback reaches 30 |
| `html_rich_table_cells` | Docling | 22 of 22 reference table rows — the fallback reaches 21 |
| `multi_page`, `normal_4pages`, `code_and_formula`, `table_mislabeled_as_picture` | pypdf | byte-identical to the core-install run |

The last row is the important one: installing the quality extra improves only
the routes Docling owns and does not take over the fast PDF path, which is the
measured Phase A1 decision holding under test rather than by assertion.

Verification with the extra installed, on the merge candidate: 24 of 24
parser-registry tests and 183 of 183 total tests passed, with 0 failed fixtures
in the benchmark. 183 is exactly the 178 that pass on the core install plus the
5 Docling-gated cases it skips. `.github/workflows/quality-parser.yml`
installs the extra plus a CPU-only torch build and the OpenCV system libraries,
and runs on demand, weekly, and on parser or fixture changes, so the adapter
stays executed without slowing the push suite.

Three defects were found only by running it, each now fixed and tested:

1. a malformed DOCX raised a raw Docling exception instead of
   `UnsupportedDocumentError`, so a bad upload would have returned an unhandled
   500 rather than a 422 with a usable message;
2. `docling-ibm-models` loads TableFormer through OpenCV, whose missing system
   libraries surfaced mid-parse as `ImportError: libxcb.so.1` and would have
   been reported to the caller as an unsupported document. Native-dependency
   failures are now `ParserUnavailableError`: an operator fault, retryable, and
   HTTP 503 on the synchronous upload paths;
3. the default `docling[rapidocr]` install pulls roughly 4 GB of unused CUDA
   wheels, so the workflow pins the CPU torch build first.

### Closed — an indexed document could be silently unsearchable

Found while reviewing `replace_document` during this closure, then reproduced.
Re-indexing flips the outgoing version's `is_latest` payload inside the SQLite
transaction, but Qdrant payloads are not part of that transaction. A crash
between the payload write and the commit left the document `indexed` in SQLite
with every vector filtered out of retrieval: listed, cited nowhere, findable by
nothing. `GAP CONFIRMED` — one source before, zero after, status still
`indexed`.

`KnowledgeStore.reconcile_latest_flags()` now runs on every store open and
repairs payload markers that disagree with document status, in the same spirit
as the ingestion worker's interrupted-job recovery. It reports the repair count
as a warning event rather than fixing it silently.
`tests/test_document_lifecycle.py` reproduces the crash window, proves retrieval
recovers after restart, and proves reconciliation leaves genuinely retired
versions hidden.

## P2 production-adaptation closure

- Exit gate: P2 `PASS`. GitHub reuse audit, measured generation, external
  Qdrant, and OIDC/JWT are all `PASS`; no row remains `PARTIAL`, `FAIL`, or
  `UNVERIFIED`.
- Branch: `agent/atlas-p2-production`, based on clean `main` commit `e8d9cf5`.
- Slice commits:
  - `c3c4ce7` — pinned GitHub component comparisons and adopt/refit/custom
    decisions;
  - `23f8dfe` — measured local generation candidate and retained extractive
    default;
  - `fa5e9e4` — explicit external-Qdrant mode, filter indexes, Compose profile,
    failure mapping, and real-server tests;
  - `d047670` — PyJWT/JWKS bearer edge, verified claim mapping, configuration,
    documentation, and adversarial tests.
- Final clean Linux gate, with the pinned real Qdrant server enabled:
  `ruff check .` passed; `pytest -o addopts='' -q` reported 205 passed and 5
  expected Docling-extra skips. The only warning is the existing Starlette
  `httpx` test-client deprecation.
- Deployment gate: `docker build -t atlas-p2-oidc-gate:local .` passed,
  including the production frontend build and PyJWT crypto dependency. A live
  hash/extractive no-key container reported readiness `ready` and returned five
  source records for a query.
- Generation decision: the cold 20-case Gemma 3 1B candidate completed every
  case but would have been production-rejected on 19 of 20, with zero citation
  and semantic-support scores, lower abstention, and p95 latency above the
  15-second gate. Extractive remains the production default; the failed
  candidate is retained as evidence, not shipped as a hidden fallback.
- Deliberate limitations:
  - Atlas does not migrate vectors between embedded and server backends;
    changing mode requires a fresh data directory followed by re-ingest or
    connector resynchronization.
  - OIDC mode is a resource-server boundary. It does not implement browser
    login, token issuance, refresh, logout, provider discovery, or sessions.
  - The OIDC regression uses a real local JWKS server and RSA keys, not a live
    third-party identity tenant; deployment-specific claim mappings still need
    representative provider-token validation.
  - The five Docling routes remain covered by their separate quality-parser
    workflow rather than the core dependency gate.
  - The Starlette test-client deprecation remains.
- No Phase C depth, frontend polish, or new-project work was started in P2.
- Merge result: the completed branch was merged locally to Atlas `main` at
  `ee8b420` without conflicts. It has not been pushed.
- Exact next cross-portfolio action: begin P3 Relay MCP server exposure in
  Relay's own isolated worktree. ContextSidecar is complete elsewhere and must
  not be reopened.

## Technique-ceiling dossier closure — 2026-08-04

- Research exit gate: `PASS`; Atlas technique experiments remain `PARTIAL`.
- Isolated worktree: `portfolio_demos/worktrees/atlas_technique_dossier`.
- Branch: `agent/atlas-technique-dossier`, based on clean Atlas `main` commit
  `da3dbd18ebc1ef6750c7d1ce9dc817296dab59b3`.
- Dossier commit: `1246c34a8c2bc48df48b03f1fe4fb92dc4969b95`.
- Required artifacts: `TECHNIQUE_TAXONOMY.md`, `EVIDENCE_MATRIX.csv`,
  `GITHUB_IMPLEMENTATION_AUDIT.md`, `BENCHMARK_DESIGN.md`,
  `RESEARCH_DECISION.md`, and `docs/EXPERTISE_NOTES.md`.
- Expertise disposition: central card **Match retrieval topology to the
  question scope** was added to `UPWORK_EXPERTISE_INDEX.md`; visual-parsing and
  refusal notes explicitly reuse the existing parsing and abstention cards.
- Verification: all six artifacts exist; the CSV imports as 22 candidates with
  all required columns and no blank candidate/status/disposition; all eleven
  systematic evidence rows are `PASS`; `git diff --check` passes. Local
  evidence references in the dossier resolve. Application tests were not
  rerun because this slice changes research/checkpoint Markdown and CSV only.
- Decision: retain fixed sparse/hybrid and routed parsing controls. Admit A0
  answerability/evidence coverage first; A1 contextual versus late/DOS, A2
  text versus visual retrieval, and A3 flat/DOS versus hierarchy/graph remain
  separately gated.
- Scope stopped before: candidate implementation, benchmark execution, Phase
  C/D, UI/visual polish, central portfolio site, merge, push, or deployment.
- Exact next cross-portfolio action: complete the ProofGrid systematic dossier
  in its own isolated worktree. Do not start Atlas A0 from this checkpoint.
  ContextSidecar is complete elsewhere and is outside this stream.

## Public dependency-maintenance closure — 2026-08-12

- Scope: standalone maintenance slice only; no Atlas experiment phase or local
  integration branch was advanced.
- Worktree: detached `portfolio_demos/worktrees/atlas_dependabot`, created from
  public `origin/main` at `d222cf1810581d77e0ff9b3f8a0ca8ebe3ff2698`.
- Dependabot: public `2cf06be75d9afcf2b487c5c5e797976f238577af`
  adds grouped, rate-limited updates for the repository's GitHub Actions, pip,
  and Docker inputs. GitHub accepted the file and opened update PRs #1-#4;
  none was merged by this slice.
- Regression exposed: the push repeated CI failure `31576368109` from the
  prior public head. Structure preservation allowed Markdown headings into the
  extractive answer, and semantic evaluation counted `## Refund routing` as an
  uncited factual claim (`citation_completeness=0.75`).
- Fix: public `fea155490d4915d46dd186d22904e2444ed4f78a` excludes
  formatting-only Markdown headings from the claim set. The existing
  completeness assertion now becomes load-bearing and an explicit assertion
  prevents headings from re-entering scored statements.
- Verification: focused Ruff and all 4 semantic-evaluation tests pass locally;
  hosted CI `31611939352`, Frontend `31611939317`, and browser-workspace deploy
  `31611939402` all pass at `fea1554`.
- Exact next action: keep the four updater PRs open for separate dependency
  review. Do not merge them as part of this maintenance checkpoint. Continue
  the central toolbox Track I equation run.
