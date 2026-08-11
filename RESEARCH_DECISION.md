# Atlas research decision

Date: 2026-08-04

## Decision

The systematic dossier is `PASS`; Atlas's technique-ceiling implementation and
experiment gate remains `PARTIAL`. No candidate was implemented.

Keep Atlas's measured text-first profile as the universal control. Admit four
bounded questions to the future experiment queue in this order:

1. answerability/evidence-coverage policy;
2. contextual retrieval versus late chunking with a DOS long-context control;
3. parsed-text versus ColPali-family visual page retrieval;
4. flat/DOS versus hierarchy/GraphRAG on predeclared global and multi-hop
   questions only.

Query rewriting/decomposition, multi-query/HyDE, adaptive routing, table-
specific indexes, compression, and iterative feedback stay in the taxonomy but
do not receive separate first experiments. They activate only when the frozen
cases expose their matching failure or when an already-admitted experiment
needs that composition.

## Retained families

| Family | Status | Role |
| --- | --- | --- |
| fixed+sparse and BGE-small hybrid | `established` | mandatory fast controls; sparse remains bundled default |
| routed pypdf/Docling parsing | `established` | text/structure control and shared seam for Ledger Lens findings |
| BGE-M3/current multilingual challenger | `provisional` | English/Lithuanian or long-text candidate, not default |
| contextual retrieval | `provisional` | long/ambiguous chunk profile pending controlled comparison |
| late chunking | `provisional` | context-preserving profile inside encoder limits |
| DOS/source-order long context | `established control` | mandatory simple control for long/hierarchical methods |
| visual late-interaction retrieval | `established family`, `provisional fit` | layout/figure/scan profile pending resource and Atlas-case evidence |
| RAPTOR/hierarchy | `contested` | long/global or multi-hop experiment only |
| Microsoft GraphRAG | `established niche` | corpus-global/entity/community experiment only |
| query rewrite/decomposition | `provisional` | later conversational/multi-hop composition |
| answerability policy | `established need`, `unknown winner` | first experiment because current refusal fails |

## Rejected or bounded choices

- Reject GraphRAG, RAPTOR, visual retrieval, contextual retrieval, and a learned
  reranker as universal defaults.
- Reject whole-framework adoption of LightRAG or another RAG application. It
  would duplicate Atlas's API, lifecycle, storage, authorization, evaluation,
  and UI instead of removing one complete responsibility.
- Reject a new Atlas-owned document parser stack. Ledger Lens leads the shared
  OCR/layout/VLM comparison and Atlas consumes its winning adapter.
- Reject leaderboard-only promotion and cross-paper headline comparisons.
- Reject an LLM judge as the only truth source and a faithfulness score as a
  substitute for answerability.
- Exclude document-packet splitting, autonomous browsing, generic agentic deep
  search, and model training from the present bought outcome. Their papers are
  adjacent evidence, not Atlas scope.

## Exact first experiment

Run A0 from `BENCHMARK_DESIGN.md`: freeze the six UAEval4RAG-style
unanswerable categories beside matched answerable controls, then compare the
current gate with bounded deterministic evidence-coverage features. Add one
pinned lightweight scorer only if deterministic features cannot meet the
pre-registered false-refusal and unanswerable-F1 gates. Do not start A1–A3 in
the same slice.

## External answers and unresolved questions

| Question | Evidence disposition | Result |
| --- | --- | --- |
| Is visual retrieval technically distinct? | triangulated external | closed `yes`; Atlas cost/routing unresolved |
| Should GraphRAG serve local facts? | external plus contrary evidence | closed `no` by default |
| Does complexity universally beat simple source-preserving retrieval? | contrary controlled evidence | closed `no`; retain DOS/BM25 controls |
| Which context-preserving method fits Atlas? | conflicting/constraint-sensitive evidence | unresolved; A1 |
| Which visual retriever fits Atlas and the CPU/GPU budget? | external benchmark not deployment-aligned | unresolved; A2 |
| Which global/multi-hop topology fits the actual corpus? | workload-specific and author-owned evidence | unresolved; A3 |
| Which refusal policy preserves answerable recall? | known need, no transferable threshold | unresolved; A0 |

## Systematic evidence gate

| Gate | Evidence | Status |
| --- | --- | --- |
| Problem decomposition | thirteen independent layers in `TECHNIQUE_TAXONOMY.md` | PASS |
| Search protocol | date, sites, window, rules, and eight query iterations recorded | PASS |
| Survey coverage | 2025–2026 RAG, multimodal-RAG, test-time feedback, reasoning-retrieval, and document surveys | PASS |
| Benchmark coverage | text, multilingual, visual, table, long, graph, grounding, refusal and local acceptance map | PASS |
| Existing-answer search | every major question has an evidence-reuse disposition above and in the matrix | PASS |
| Technique-family saturation | iterations 6 and 7 added no new decision-relevant family | PASS |
| Candidate comparison | `EVIDENCE_MATRIX.csv` covers quality, resources, integration, health and failures | PASS |
| Contrary evidence | DOS-versus-complex, graph scaling/detail, evaluator failure, leaderboard transfer and query-expansion losses recorded | PASS |
| Implementation evidence | `GITHUB_IMPLEMENTATION_AUDIT.md` pins maintained repos, runnable surfaces, defects and seams | PASS |
| Portfolio fit | retained families have distinct operating regions; duplicates/whole frameworks are excluded | PASS |
| Review status | every conclusion is labelled; only established/provisional candidates with explicit designs enter the queue | PASS |

## Expertise extraction

- Canonical notes: `docs/EXPERTISE_NOTES.md`.
- Central card added: **Match retrieval topology to the question scope**.
- Existing cards retained: **Choose retrieval from client cases, not from
  technique popularity**, **Parsing failures cannot be repaired by retrieval
  tuning**, and **Treat abstention as its own acceptance criterion**.
- Notes that restate those existing cards carry an explicit duplicate
  disposition rather than adding noise to the central index.

## Boundary and next authorization

This commit may authorize a later isolated A0 research/implementation branch
only after the portfolio checkpoint accepts this dossier and ProofGrid's shared
measurement work is reconciled. It does not authorize A0 automatically, visual
polish, Atlas Phase C/D product work, a central portfolio site, or another
project.

