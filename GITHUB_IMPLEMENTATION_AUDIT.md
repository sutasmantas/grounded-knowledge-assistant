# Atlas GitHub implementation audit

Date: 2026-08-04

This is a research and reuse gate, not permission to integrate code. Repository
health was read from GitHub's repository, commit, release, and current-issue
APIs on the date above; runnable surfaces were checked in the pinned README or
official documentation.

## Atlas seams that must be reused

| Responsibility | Existing seam | Rule for a candidate |
| --- | --- | --- |
| parsing | `app/parsers.py` registry and `ParsedDocument` contract | adapter must preserve page/source structure and explicit empty/failure behavior |
| chunk construction | `app/ingestion.py` plus chunk-profile benchmark | candidate supplies chunks/context; it must not own document lifecycle |
| text embeddings | `app/embeddings.py` | candidate implements the existing batch/query boundary and records model revision |
| storage/filtering | `app/storage.py` Qdrant named vectors and payload filters | no candidate may bypass tenant, ACL, collection, or latest-version filters |
| retrieval/fusion | `app/retrieval.py` | additional retriever returns traceable candidates behind registration/configuration |
| reranking | existing `Reranker` interface and benchmark | no second orchestration framework |
| generation | `app/generation.py` | bounded provider call; citations and source IDs remain Atlas-owned |
| evaluation | `app/evaluation.py`, `app/semantic_evaluation.py`, frozen JSONL cases | external datasets adapt into the existing case/result contract |

## Maintained implementation snapshot

| Candidate | Pin/release inspected | Runnable surface and dependencies | Health/known defect evidence | Reuse decision |
| --- | --- | --- | --- | --- |
| Docling | `docling-project/docling@9b454c9e88454d95fd04d538c552a3c07bc3c04d`; `v2.118.0` | `pip install docling`; `DocumentConverter`; optional OCR/models; CLI and API server | pushed 2026-08-03; 951 open issues/PR count; current issue #3936 reports v2.118 hyphenated-label crash | **adopt existing pinned `<2.118` parser route**; assess upgrade separately; do not replace Atlas lifecycle |
| PaddleOCR | `PaddlePaddle/PaddleOCR@2661c7c0ef5c613e8f93c6e93b2e052399f0f854`; `v3.7.0` | modular OCR, PP-Structure, KIE and VLM pipelines; CPU/GPU/accelerator backends; Paddle/PaddleX stack | pushed 2026-07-22; active 2026 release; current ROCm startup, Torch compatibility and ONNX-operator issues (#18300, #18208, #18190) | **experimental parser adapter**, led by Ledger Lens; do not install the whole stack in Atlas until it wins a shared case |
| ColPali engine | `illuin-tech/colpali@c23838d920a7c426ee297034211cff2f55da65dc`; `v0.3.17` | `pip install colpali-engine`; processor/model APIs; CUDA/MPS quickstart; ViDoRe benchmark package; optional late-interaction kernels | pushed 2026-08-03; 14 open issues; maintained release 2026-06-08 | **adopt API for a visual retrieval experiment**; wrap output as Atlas candidates and use a separate Qdrant multivector collection/profile |
| Jina late chunking reference | `jina-ai/late-chunking@1d3bb02bf091becd0771455e4e7959463935e26c` | install repository and run MTEB-derived tasks; long-context transformer forward pass plus token-span pooling | last code push 2024-12-23; no release; issue #2 asks how to exceed 8192 tokens | **refit the bounded pooling mechanism**, not the repository as a runtime framework; pin encoder and maximum document tokens |
| FlagEmbedding/BGE-M3 | `FlagOpen/FlagEmbedding@7ed43d67ec03fbe5c31c0992dbfa941fb1860549`; `v1.4.0` | maintained BGE model/reranker APIs; dense, sparse, and multivector capabilities | pushed/released 2026-04-22; broad issue surface (908) | **retain current dense adapter candidate**; do not add its sparse/multivector modes unless they replace a complete Atlas responsibility and win |
| Microsoft GraphRAG | `microsoft/graphrag@14a00ad88fc33cf2b52f4f113f25807556f8e25e`; `v3.1.1` | CLI/package for indexing, local/global/DRIFT query modes and graph/community artifacts | pushed 2026-08-04; active release 2026-07-18; 61 open issues | **experimental adapter, not foundation**; import/export a bounded corpus and map cited source IDs back to Atlas; only global/entity workloads qualify |
| RAPTOR | `parthsarthi03/raptor@7da1d48a7e1d7dec61a63c9d9aae84e2dfaa5767` | Python requirements, OpenAI-key-based tree construction and query examples | last push 2024-09-03; no release; #83 says incremental addition is not implemented; #81 recursion failure | **reference/refit only**; copy no engine wholesale; any experiment owns a frozen disposable index and must include rebuild cost |
| LightRAG | `HKUDS/LightRAG@910686747db3e21f8c8abc825744c9f932a1b23c`; `v1.5.5` | Python API and `lightrag-server`; provider/storage matrix; incremental graph/vector updates | pushed/released through 2026-08-04/2026-07-31; 216 open issues; current workspace/multi-tenant RFCs | **reject whole-framework adoption** because it duplicates Atlas API, storage, auth and lifecycle; inspect only graph update/query contracts if GraphRAG experiment proceeds |
| MTEB | `embeddings-benchmark/mteb` release `2.18.6` (`fa36ee7`) | pip/uv package, task registry, result schema and leaderboard data | released 2026-07-22; active task/model corrections demonstrate version sensitivity | **adopt task/result formats selectively** for multilingual shortlist; client/Atlas cases remain the deployment gate |

## Component-level decisions before any code

| Proposed subsystem | At least two candidates inspected | Decision | Exact reusable responsibility | Integration-cost judgment |
| --- | --- | --- | --- | --- |
| contextual chunk generation | Anthropic documented method; Atlas `AnswerGenerator`; independent contextual-vs-late comparison | `custom bounded adapter over existing generator` | generate and cache one bounded context string with source/version/model provenance | no maintained component removes the Atlas-specific source/cost policy; the adapter is smaller than a new framework |
| late chunk pooling | Jina late-chunking; FlagEmbedding/Transformers token outputs | `refit` | long-document token embeddings and span pooling only | use a pinned model API; do not adopt a dormant repository's benchmark/application shell |
| visual page retrieval | ColPali engine; PaddleOCR-VL/MinerU visual parsing; Docling text path | `adopt ColPali API for experiment` | page/query processors and MaxSim scoring; Atlas owns filters, storage registration and trace | ColPali removes the hard visual embedding/scoring responsibility; parser VLMs solve conversion, not the same retrieval contract |
| multilingual text retrieval | BGE-M3/FlagEmbedding; current MTEB candidate through SentenceTransformers/FastEmbed | `refit existing embedding seam` | model loading and dense vectors behind `app/embeddings.py` | a second vector database or RAG framework adds no value |
| global graph retrieval | Microsoft GraphRAG; LightRAG; RAPTOR hierarchy | `experimental adapter` | index/query a frozen authorized corpus and return source-mapped evidence | GraphRAG is maintained and matches global questions; LightRAG duplicates the app; RAPTOR is stale and non-incremental |
| query rewriting/decomposition | Atlas generator contract; UniRAG/question-decomposition research code; multi-query RRF patterns | `custom later, bounded` | produce versioned query variants/subquestions and feed existing retrieval | orchestration is small but must wait for a measured failure; importing an agent/RAG framework would create integration hell |
| benchmark ingestion | Atlas case/result models; MTEB/ViDoRe packages; BenchmarkQED concepts | `refit` | adapters into frozen Atlas JSONL and result schema | preserve one measurement spine; do not add a second dashboard/evaluator runtime |
| refusal/answerability | UAEval4RAG synthesis/evaluation; Atlas deterministic/HHEM checks; ProofGrid scorer concepts | `refit existing evaluation` | case categories, answerability score, threshold and explicit refusal outcome | the unresolved work is policy calibration on Atlas evidence, not a missing general framework |

## Installation and integration checks still required

No new candidate is adopted in this research slice. A later experiment cannot
be marked complete until its pinned environment proves:

1. installation on the declared CPU/GPU profile;
2. one successful representative case;
3. one relevant failure case;
4. the existing Atlas interface and trace contract;
5. tenant/ACL/version filtering before candidate scoring;
6. clean disable/uninstall without changing the default profile;
7. composition with the shared Ledger Lens document adapter where applicable.

## Audit result

`PASS` for research admission. Strong maintained implementations exist for the
serious operating regions, the pins and defects are explicit, and no
substantial custom subsystem is authorized before reuse is rechecked. This
does not make any integration `PASS`.

