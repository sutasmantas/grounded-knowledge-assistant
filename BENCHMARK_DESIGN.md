# Atlas benchmark design

Date: 2026-08-04

Status: design only. The systematic dossier must be committed and reviewed
before any runner, adapter, dataset download, model install, or benchmark run.

## Questions closed without a new local head-to-head

| Question | Evidence-reuse level | Closure |
| --- | --- | --- |
| Should sparse/dense/hybrid and no-reranker remain controls? | portfolio comparison | Yes. Atlas's frozen runs already establish the current-corpus control. |
| Is visual page retrieval a distinct capability from parsed-text retrieval? | triangulated external answer | Yes. ColPali/ViDoRe and newer multimodal retrieval work establish a distinct visual/layout operating region. Atlas fit and resource cost remain unresolved. |
| Should GraphRAG replace ordinary fact retrieval? | triangulated external plus contrary evidence | No. GraphRAG evidence targets global/entity workloads; simple/vector/BM25 controls remain stronger or cheaper in other regions. |
| Can one retrieval metric stand in for grounded refusal? | external benchmark plus portfolio comparison | No. GaRAGe/GroUSE/UAEval and Atlas's own faithful-but-irrelevant answers establish separate gates. |
| Does a public leaderboard choose the Lithuanian/client profile? | established evaluation limitation | No. Public results shortlist candidates; representative local/client cases decide routing. |

## Shared controls

- Host envelope: Intel Core Ultra 7 155U, 12 cores/14 logical processors,
  approximately 32 GB RAM, no NVIDIA GPU visible on 2026-08-04.
- CPU experiments run on that host with process RSS, index bytes, build time,
  query p50/p95, tokens, and provider cost captured.
- A visual/VLM candidate that cannot run there may use one declared rented GPU
  profile, capped at 24 GB VRAM, six GPU-hours, and USD 25 total. All candidates
  in that comparison use the same GPU type and precision.
- Every stochastic generator setting runs at least three seeds. Deterministic
  retrievers run once after a warm-up and report per-case output; latency gets
  at least 30 timed queries per profile.
- Development labels may tune prompts/thresholds. The held-out split is run
  once for the promotion decision. Public benchmark test labels are never used
  for tuning.
- Tenant/ACL/version canary tests, source-ID completeness, and explicit empty
  output are invariant correctness gates. A candidate failing one is rejected
  regardless of average quality.

## A0 — answerability and evidence-coverage policy

Why first: this is Atlas's only demonstrated user-visible correctness failure.
More retrieval complexity cannot safely ship while faithfully cited irrelevant
answers are accepted.

| Field | Frozen design |
| --- | --- |
| Hypothesis | A separate answerability/evidence-coverage policy can improve refusal on unsupported and scope-excluded questions without reducing held-out answerable recall below the current profile. |
| Baseline | current fixed+sparse profile with existing content/evidence gate and extractive generation |
| Candidates | calibrated retrieval/evidence score; deterministic query-evidence coverage features; one pinned lightweight NLI/answerability scorer only if deterministic features are insufficient |
| Data | current 50 Atlas cases plus UAEval4RAG-style categories generated only from the six controlled sources; minimum 12 cases per unanswerable category and matching answerable controls; frozen 60/40 development/held-out split by source and category |
| Perturbations | excluding collection filter; entity replacement; missing premise; false presupposition; temporal mismatch; out-of-domain request; adversarial near-match |
| Metrics | answerable Recall@5/nDCG@5; unanswerable precision/recall/F1; selective risk/coverage; false-refusal rate; p95 latency; minimum category result |
| Promotion | unanswerable held-out F1 at least 0.85, false-refusal at most 5%, no required-source recall loss, and all ACL/citation gates pass |
| Routing | low coverage refuses or asks for clarification; borderline cases expose the evidence gap rather than generating; high coverage continues to the selected retrieval/generation profile |
| Budget | 4 CPU-hours, 2 GB new artifacts, USD 0 by default; one credentialed judge is diagnostic only and capped at USD 5 |
| Confounders | synthetic negatives can be too easy; NLI score can correlate with lexical overlap; threshold tuning can leak held-out categories |

## A1 — fixed context versus contextual retrieval versus late chunking

| Field | Frozen design |
| --- | --- |
| Hypothesis | Context-preserving representations improve long/cross-section retrieval, but neither should become the default unless it preserves source recall and fits the CPU/storage budget. |
| Baseline | fixed 950-character windows with sparse and current BGE-small hybrid retrieval |
| Candidates | contextual chunks using one pinned generator; Jina-style late pooling using one pinned long-context multilingual encoder; DOS RAG source-order control when the selected document fits the generator window |
| Data | current Atlas sources plus at least 12 public annual-report/manual/policy documents across 10–100 pages; English and Lithuanian document/question slice; minimum 120 questions across exact, paraphrase, boundary, cross-section, multi-document, table-reference and unanswerable categories |
| Split | documents, not questions, separated into development and held-out sets; no paraphrase of a held-out fact in development |
| Metrics | required-source Recall@5; nDCG@5; MRR; passage/section support; answerability; index time/bytes; generator context tokens; query p50/p95; RSS; cost |
| Promotion | a specialized profile needs at least +5 percentage points in its predeclared category or recovery of two or more important baseline failures, with no ACL failure, no more than 2-point required-source recall loss, and resource cost inside its declared route |
| Routing | fixed+sparse remains fast default; contextual or late route only for document lengths/ambiguity patterns that win; DOS route only when the authorized source set fits the context budget |
| Budget | 12 CPU-hours; 10 GB artifacts/models beyond existing cache; contextual generation capped at USD 10 or a pinned local model; three seeds for generated contexts |
| Confounders | generator-written context may leak labels or hallucinate; long encoder truncation; Lithuanian translation artifacts; document length and method may be correlated |

## A2 — parsed-text retrieval versus visual page retrieval

| Field | Frozen design |
| --- | --- |
| Hypothesis | ColPali-family retrieval earns a visual profile on layout-dependent cases, but parsed text remains better for exact text and the CPU/default route. |
| Baseline | routed pypdf/Docling parsing, fixed chunks, sparse and hybrid retrieval |
| Candidate | pinned ColPali/ColQwen model through `colpali-engine==0.3.17`, page-level multivectors and MaxSim; one text+visual fusion only after independent paths are reported |
| Data | a pinned ViDoRe v2 subset plus shared Ledger Lens/Atlas pages containing tables, figures, scans and multilingual text; at least 25 cases per visual-dependent and text-sufficient stratum |
| Split | preserve official benchmark split; portfolio pages split by document, with no same-template page in both sets |
| Metrics | page Recall@1/5; nDCG@5; required visual-element recall; answer/citation support; index bytes/page; build time/page; query p50/p95; peak RAM/VRAM; cost/page |
| Promotion | visual profile must improve visual-dependent nDCG@5 by at least 0.05 or recover at least five baseline failures, while returning source/page provenance and meeting the 24 GB VRAM cap; it need not beat text on text-sufficient cases |
| Routing | visual profile for scans, figures, charts, spatial/table questions or parser-loss signals; text profile for ordinary searchable prose; fusion only when each path contributes unique held-out evidence |
| Budget | six matched GPU-hours, 24 GB VRAM, USD 25, 20 GB model/index disk; stop early if installation or one success/one failure integration checks fail |
| Confounders | ViDoRe model training overlap; page retrieval versus answer correctness; OCR text hidden inside model pretraining; image resolution and batch-size effects |

## A3 — flat/DOS versus hierarchy/graph on predeclared complex questions

| Field | Frozen design |
| --- | --- |
| Hypothesis | Hierarchical or graph indexes help only global/entity/community and some multi-hop questions; they are dominated for local facts after indexing cost is counted. |
| Baselines | Atlas flat sparse/hybrid; DOS source-order long context; optional query decomposition over the same flat index |
| Candidates | RAPTOR mechanism with disposable frozen index; Microsoft GraphRAG 3.1.1 global/local or DRIFT mode; LightRAG is not separately run unless it supplies a missing incremental-update comparison |
| Data | minimum 20 local fact, 20 cross-document multi-hop, and 20 corpus-global questions over a public multi-document corpus; WildGraphBench or BenchmarkQED-style labels may seed cases but final questions receive blinded human source annotation |
| Control | same authorized sources, generator, maximum answer/context tokens, and question set; report construction separately from query cost |
| Metrics | evidence Recall@k; subquestion/source coverage; answer support and completeness; fine-detail retention; build tokens/time/cost; incremental update correctness; query p50/p95/tokens/cost |
| Promotion | graph/hierarchy can survive only in a category with a statistically and practically meaningful quality gain, complete source mapping, and a documented cost envelope; local-fact regression does not matter if routing excludes that category |
| Routing | `global-summary` to winning graph/global profile; `cross-document` to winning hierarchy/decomposition profile; `local-fact` never routes to GraphRAG by default |
| Budget | USD 30 provider cost, 12 wall-clock hours, 20 GB artifacts; three generator seeds; stop if graph build cannot cover the full frozen corpus |
| Confounders | author-owned graph benchmarks; LLM-judge preference for verbosity; generated graph omissions; summary leakage; cost differences from cached indexes |

## Execution order and stop rules

1. A0 answerability first.
2. A1 context construction and A2 visual retrieval may follow independently
   after ProofGrid's measurement dossier defines the shared uncertainty/judge
   contract.
3. A3 runs only if the frozen workload contains enough truly global/multi-hop
   questions to satisfy its strata.
4. Stop a candidate after failed installation, contract, provenance, ACL, or
   one-success/one-failure checks; do not spend the full budget to rescue it.
5. Do not build a production router until at least two profiles win distinct
   operating regions. Until then selection is explicit benchmark configuration.

