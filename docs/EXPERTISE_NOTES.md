# Atlas technique decisions

**Verification:** [claim-to-artifact map and rerun commands](https://sutasmantas.github.io/evidence/#atlas) · [machine-readable receipt](https://sutasmantas.github.io/evidence/receipt.json)

Date: 2026-08-04

## Match retrieval topology to the question scope

### Client trigger

- Job wording or deliverable: choose or improve RAG for local facts,
  cross-document reasoning, or corpus-wide summaries.
- Measured demand: Atlas is the existing reusable knowledge-assistant project;
  the historical corpus supports RAG work but does not prove one technique's
  prevalence or conversion effect.
- Existing reusable project: Atlas parsing, Qdrant filtering, sparse/dense
  retrieval, RRF, reranking, citations, ACLs, and evaluation harness.

### Failure symptom or unanswered choice

Technique labels hide different tasks. A graph/community index designed for
"what are the themes across this corpus?" can add large construction cost and
lose fine details when the client actually needs an invoice number or policy
clause. A flat retriever can be excellent for local facts while missing global
or scattered evidence.

### Competing options

| Option | Why it is plausible | Main cost or failure risk |
| --- | --- | --- |
| sparse/hybrid flat retrieval | strongest Atlas control for local facts and identifiers | fragmented evidence on global or multi-hop questions |
| source-order/DOS or RAPTOR hierarchy | preserves or summarizes long-document context | context limits or generated-summary/rebuild cost |
| Microsoft GraphRAG | purpose-built global/entity/community retrieval | expensive graph construction; detail loss; wrong task for local lookup |

### Controlled comparison

- Evidence-reuse level: triangulated external answer plus existing portfolio
  comparison.
- External sources/applicability: Microsoft defines GraphRAG around global
  corpus sensemaking; RAPTOR targets long/multi-step context; the EMNLP 2025
  DOS study supplies a matched simple control; WildGraphBench and a 2026
  scaling study supply contrary graph evidence.
- Contrary evidence: DOS RAG matched or beat more intricate long-context
  methods on multiple tasks; WildGraphBench reports category tradeoffs; the
  scaling study reports graph construction limits and BM25 wins at shared
  tiers.
- Representative cases: Atlas local facts remain measured; global/multi-hop
  cases are not yet broad enough for a local winner.
- Metrics/thresholds: future A3 freezes source coverage, support, fine-detail
  retention, construction/query cost and category-specific promotion.
- Runtime/date: evidence audited 2026-08-04; GraphRAG 3.1.1 and exact repository
  pins are in `GITHUB_IMPLEMENTATION_AUDIT.md`.
- Outside comparison: autonomous deep research, web search, and general agent
  planning.

### Result

The external answer closes the architecture default: graph or hierarchy does
not replace flat retrieval. It remains eligible only for a predeclared question
scope where it can win against flat and source-order controls. The actual Atlas
global-profile winner remains unresolved until A3.

### Decision rule

Use flat sparse/hybrid retrieval for local facts. Test source-order or
hierarchical retrieval for long/cross-section questions. Test GraphRAG only for
corpus-global, entity/community, or deliberately multi-source questions. A
client's question distribution, update rate, source authority, context budget,
and need for fine details can reverse the specialized choice.

### Delivery control

Label acceptance questions by scope before choosing a topology. Require local,
multi-hop, and global category results plus index-build cost; never report one
aggregate answer score as permission to route every query to the most complex
profile.

### Reuse boundary

- Reusable without client data: Atlas interfaces, flat controls, question-scope
  labels, matched-cost benchmark design, and source/ACL invariants.
- Requires client data/criteria: question distribution, global-vs-local value,
  update frequency, source mappings, model/provider and cost envelope.
- Unsupported claim: GraphRAG is universally more accurate, Atlas has already
  deployed a graph profile, or a public benchmark predicts client results.

### Proposal-safe insight

I separate local fact lookup from cross-document and corpus-wide questions
before choosing a RAG architecture. That keeps a fast source-preserving control
for ordinary questions and limits graph or hierarchical indexing to cases where
its extra construction cost fixes a measured coverage failure.

### Evidence

- Code: `app/retrieval.py`, `app/storage.py`, `app/evaluation.py`.
- Tests/artifacts: `docs/profile-winner-matrix.md`,
  `docs/evaluation-semantic-baseline-v3.json`.
- Research: `TECHNIQUE_TAXONOMY.md`, `EVIDENCE_MATRIX.csv`,
  `BENCHMARK_DESIGN.md`, `GITHUB_IMPLEMENTATION_AUDIT.md`.
- Reproduction: existing Atlas evaluation commands in the repository README;
  A3 is design-only and has no result command yet.

### Interview follow-up

- Likely question: Why not use GraphRAG for everything?
- Short answer: its strongest evidence is for global/entity questions, while
  local/vector and source-order controls can be better and dramatically cheaper
  elsewhere. Routing by question scope is more defensible than one universal
  graph index.
- Deeper evidence: open the A3 design and the GraphRAG/RAPTOR implementation
  rows in the GitHub audit.

### Central index disposition

- Added card in `UPWORK_EXPERTISE_INDEX.md`: yes.
- Card heading: **Match retrieval topology to the question scope**.

## Use visual retrieval only when the answer depends on the page

### Client trigger

- Job wording or deliverable: RAG over scanned PDFs, charts, figures, tables,
  manuals, or visually rich reports.
- Existing reusable project: Atlas's routed pypdf/Docling parser and Ledger
  Lens's OCR/provenance path.

### Failure symptom or unanswered choice

Text parsing can discard layout and visual evidence, but indexing every page as
multi-vector images adds model, GPU, storage, and query cost even for ordinary
searchable prose.

### Competing options

| Option | Why it is plausible | Main cost or failure risk |
| --- | --- | --- |
| parsed text retrieval | cheap, filterable, citeable, strong on exact prose | loses figures/layout and inherits OCR/parser errors |
| ColPali-family page retrieval | retains page appearance and fine visual cues | GPU and multi-vector cost; retrieves pages rather than fields/answers |
| text+visual fusion | can recover evidence unique to either representation | duplicates index/query work and can add noisy candidates |

### Controlled comparison

- Evidence-reuse level: triangulated external answer; portfolio fit unresolved.
- Sources: ColPali and ViDoRe v2 establish the family; newer multimodal surveys
  and layered retrieval work confirm page/layout/element operating regions.
- Contrary evidence/limits: ViDoRe v1 approached saturation; page nDCG is not
  answer correctness; external runs do not use Atlas ACLs or the current CPU-
  only host.
- Representative cases/metrics/budget: frozen in A2 of
  `BENCHMARK_DESIGN.md`; visual and text-sufficient strata are separate.
- Runtime/date: ColPali engine 0.3.17 inspected 2026-08-04; normal quickstart
  targets CUDA/MPS.
- Outside comparison: field extraction and arbitrary VLM reasoning.

### Result

External evidence closes that visual retrieval is a real distinct tool. It does
not close its Atlas routing threshold, hardware cost, or whether text+visual
fusion contributes unique held-out evidence.

### Decision rule

Keep text for ordinary searchable prose. Test visual retrieval for scans,
figures, charts, spatial/table questions, or explicit parser-loss signals. Keep
fusion only when both paths contribute unique held-out evidence within the
latency/storage budget.

### Delivery control

Stratify acceptance cases by whether the answer is actually visible-only, and
require page/source provenance plus the same pre-retrieval ACL filter. A visual
score cannot silently bypass authorization or become an extraction confidence.

### Reuse boundary

- Reusable: ColPali API candidate, Atlas candidate/trace contract, ViDoRe
  adapter design, parser-loss signals.
- Requires client facts: document appearance, question mix, hardware, page
  volume, latency and storage budget.
- Unsupported claim: Atlas currently supports visual retrieval or that ViDoRe
  scores establish client answer accuracy.

### Proposal-safe insight

For visually rich documents I test whether the required evidence survives text
extraction before paying for page-image retrieval. The visual path is routed to
layout-dependent questions, while searchable prose keeps the faster cited text
path.

### Evidence

- Research: A2 in `BENCHMARK_DESIGN.md`, ColPali row in
  `GITHUB_IMPLEMENTATION_AUDIT.md`, and the visual family in
  `EVIDENCE_MATRIX.csv`.
- Reproduction: no local result exists; the future A2 command must be added by
  its implementation slice.

### Interview follow-up

- Likely question: Why not OCR everything and use text embeddings?
- Short answer: OCR cannot preserve every figure, layout, or spatial cue.
  Visual retrieval covers that operating region, but its page-level quality and
  GPU/index cost must be measured separately.
- Deeper evidence: ViDoRe v2 limits and A2 routing/promotion thresholds.

### Central index disposition

- Not indexed.
- Reason: the existing central card **Parsing failures cannot be repaired by
  retrieval tuning** already provides the buyer retrieval path; this note is
  the narrower implementation/routing evidence behind it.

## Refusal is a separate model-selection gate

### Client trigger

- Job wording or deliverable: a grounded assistant must say when its private
  knowledge base does not support the request.
- Existing reusable project: Atlas citations, HHEM support checks, no-answer
  labels, and retrieval traces.

### Failure symptom or unanswered choice

Atlas's held-out extractive answers were strongly supported by their citations
while both expected no-answer cases failed. A faithful statement copied from an
irrelevant passage is still a wrong answer.

### Competing options

| Option | Why it is plausible | Main cost or failure risk |
| --- | --- | --- |
| retrieval threshold only | cheap and deterministic | score distributions shift; lexical near-matches can pass |
| evidence-coverage features | exposes missing entities/premises and scope | task-specific feature design |
| NLI/LLM answerability scorer | semantic signal | calibration, latency and judge blind spots |

### Controlled comparison

- Evidence-reuse level: portfolio comparison plus triangulated external answer.
- External sources: UAEval4RAG defines six unanswerable categories; GaRAGe
  reports weak deflection; GroUSE documents evaluator blind spots.
- Contrary evidence: no single retrieval configuration consistently optimizes
  answerable and unanswerable behavior across knowledge bases.
- Representative cases, thresholds and budget: frozen in A0 of
  `BENCHMARK_DESIGN.md`.
- Outside comparison: safety refusal unrelated to evidence coverage.

### Result

The need for a separate refusal gate is established. The winning Atlas policy
and threshold remain unknown, so A0 is the first admitted experiment.

### Decision rule

Measure answerable recall and unanswerable precision/recall separately. Refuse
or clarify when evidence coverage is insufficient; do not promote a retriever
or judge that improves one metric by hiding valid answers or accepting faithful
irrelevance.

### Delivery control

Freeze unsupported categories and matched answerable controls before tuning.
Keep deterministic citation/source checks even if a semantic scorer is added,
and review threshold-near cases.

### Reuse boundary

- Reusable: category schema, case generator constraints, separate metrics and
  explicit refusal response.
- Requires client facts: acceptable false-refusal rate, authoritative source
  scope, escalation/clarification behavior.
- Unsupported claim: the present Atlas build has solved abstention.

### Proposal-safe insight

I test grounded refusal separately from citation faithfulness, because an
answer can accurately quote an irrelevant passage. Acceptance includes both
unsupported-question handling and a false-refusal limit on valid questions.

### Evidence

- Existing result: `docs/semantic-evaluation.md` and
  `docs/semantic-evaluation-v1.json`.
- Future design: A0 in `BENCHMARK_DESIGN.md`.

### Interview follow-up

- Likely question: Isn't a similarity threshold enough?
- Short answer: not reliably. Near-match passages and scope filters can produce
  high enough scores while missing the premise, so the gate needs category-
  level coverage and false-refusal measurement.
- Deeper evidence: the two Atlas held-out failures and UAEval4RAG taxonomy.

### Central index disposition

- Not indexed.
- Reason: duplicate of the existing central card **Treat abstention as its own
  acceptance criterion**; this note updates the research basis and exact next
  experiment without creating a redundant retrieval path.

