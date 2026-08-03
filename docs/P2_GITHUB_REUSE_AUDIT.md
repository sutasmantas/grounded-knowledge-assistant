# P2 GitHub reuse audit

Date: 2026-08-03

This audit is the code-start gate for Atlas P2. It compares repository and
component boundaries before implementation. The decision labels are:

- `adopt`: use the maintained component through its public API;
- `refit`: adapt an existing Atlas seam around the maintained component;
- `custom`: keep only product-specific policy in Atlas;
- `reject`: do not add the dependency or framework.

## Measured generation

| Candidate | Pinned revision | Component inspected | Decision | Reason |
| --- | --- | --- | --- | --- |
| EleutherAI LM Evaluation Harness | `f4d4b3de3ee6741a7151a9fe74945ee515262f4c` | API/local OpenAI-compatible model adapters, task registry, sample logging | `reject` | Its LM/task abstractions would duplicate Atlas's existing retrieval, source, frozen-case, and semantic-judge contracts. It is suited to general LM tasks, not an in-product RAG comparison with Atlas lifecycle state. |
| Promptfoo | `26b725bd9496351ef269380c9fd83b9c2c338a0e` | provider/assertion matrix and custom evaluator hooks | `reject` | It adds a Node evaluation runtime and a second provider/assertion configuration surface while Atlas already has typed Python cases and per-case exports. |
| llama.cpp | `f2b52a87e82fa461191565a19d4ef9fd8b8fbd87` | `llama-server` OpenAI-compatible chat endpoint, health endpoint, CPU Docker path, direct GGUF loading | `adopt` | It supplies the missing real local model runner without changing Atlas's generator interface and runs on the available CPU-only Docker environment. |
| Atlas `app.generation` + frozen evaluators | Atlas baseline `e8d9cf5` | `AnswerGenerator`, `OpenAICompatibleGenerator`, `EvaluationCase`, HHEM/citation checks | `refit` | Extend the existing held-out runner with provider comparison, abstention, latency, provider usage/cost, resource capture, and per-category failures. Do not create a second benchmark framework. |

Implementation boundary: the runner may orchestrate any OpenAI-compatible
endpoint, but Atlas owns its RAG case loading and citation/abstention policy.
The extractive path remains the no-key control. A local model is measured, not
automatically promoted.

## Qdrant deployment boundary

| Candidate | Pinned revision | Component inspected | Decision | Reason |
| --- | --- | --- | --- | --- |
| Qdrant Python client | `200d865d0d50da767180d270c0dc4a003c116b3c` | one `QdrantClient` API for `path=` local mode and `url=`/`api_key=` server mode; `create_payload_index` | `adopt` | Atlas already uses this client. The maintained constructor is the correct local/server seam; a new storage abstraction would add no capability. |
| Qdrant server | `db8fa43fcb6aedec1e739487e17a99731b74590a` | container deployment, persistence, readiness, collection and payload-index APIs | `adopt` | Use a pinned server container in Compose and the official readiness endpoint. |
| Atlas `KnowledgeStore` construction | Atlas baseline `e8d9cf5` | embedded client creation and collection initialization | `refit` | Inject a configured official client, create filter indexes immediately after collection creation, and retain embedded mode. |
| Atlas payload policy | Atlas baseline `e8d9cf5` | tenant, document lifecycle, collection, principal/group, and latest-version filters | `custom` | Index only fields used by Atlas filters. Mark `tenant_id` as the Qdrant tenant keyword index; keep ACL and lifecycle semantics in Atlas tests. |

Implementation boundary: do not fork Qdrant behavior or build a storage proxy.
Server failure must surface as readiness/query failure; it must never silently
fall back to an empty embedded index.

## OIDC/JWT validation

| Candidate | Pinned revision | Component inspected | Decision | Reason |
| --- | --- | --- | --- | --- |
| PyJWT | `7144e4534c34810f4525dc4578a32addd8212cff` | `PyJWKClient`, JWKS refresh/cache, algorithm restriction, `decode` issuer/audience/expiry checks | `adopt` | This is the smallest maintained component that covers signature and standard-claim validation plus unknown-`kid` refresh for rotation. |
| Authlib | `f43fcf9a449e08f8971ff78756e3718a985eb5bf` | JOSE/JWT plus OAuth/OIDC client and server stacks | `reject` | Atlas is only a resource server. Adding OAuth clients, authorization-server primitives, and session flows would broaden the product beyond the required bearer-token edge. |
| Atlas authentication edge | Atlas baseline `e8d9cf5` | current trusted headers and `AccessContext` dependency | `refit` | Add an explicit `headers` demo mode and `oidc` production mode. OIDC mode accepts bearer tokens only and removes trust in caller-supplied identity headers. |
| Atlas claim mapping | Atlas baseline `e8d9cf5` | tenant, subject, group and role policy | `custom` | Claim names are deployment policy. Validate bounded string/list values, combine configured group/role claims, and map only verified claims into the existing `AccessContext`. |

Implementation boundary: do not add login UI, token issuance, refresh tokens,
user storage, or authorization-server behavior. Reject missing/malformed bearer
tokens and every validation failure with a uniform 401 response.

## Gate result

`PASS` — all three P2 slices have repository- and component-level decisions.
Implementation may proceed in the isolated `agent/atlas-p2-production`
worktree. Each slice remains independently gated and committed.
