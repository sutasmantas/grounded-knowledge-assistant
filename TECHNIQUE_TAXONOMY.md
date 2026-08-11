# Atlas technique taxonomy

Date: 2026-08-04

Status: systematic research dossier; no implementation is authorized by this
file. Conclusions use `established`, `provisional`, `contested`, or `unknown`.

## Decision boundary

Atlas is a grounded company-knowledge assistant. The paid outcome is a
source-cited answer over private documents while preserving tenant, collection,
ACL, version, latency, and abstention behavior. A technique belongs here only
when it improves that outcome or defines a useful routing boundary. General web
search agents, autonomous browsing, model training, and a second RAG framework
are outside this dossier.

The current measured baseline is not a generic "vanilla RAG" straw man. It
already includes format-aware parsing, fixed/heading/parent-child/Docling
chunking, sparse and dense Qdrant vectors, reciprocal-rank fusion, optional
cross-encoder or ColBERT reranking, source/version/ACL filters, extractive and
OpenAI-compatible generation, citations, HHEM-based support checks, and a
50-case frozen retrieval set. Its known evidence gap is breadth: six source
documents do not cover long, visual, multilingual, table-heavy, global, or
reasoning-intensive workloads.

## Problem decomposition

| Layer | Independent decision | Serious method families | Current Atlas boundary |
| --- | --- | --- | --- |
| Intake and lifecycle | acquire, identify, version, authorize, and delete sources | upload; local/URL connector; incremental sync; packet splitting as an adjacent client-specific task | durable versioned lifecycle and ACL filtering are already implemented |
| Parsing and layout | recover text, tables, figures, reading order, and provenance | pypdf fast path; Docling structured path; OCR; layout/VLM parser; direct visual page representation | pypdf + routed Docling; visual structure is not retained as a retrieval representation |
| Representation | choose evidence units and modalities | lexical text; dense text; sparse learned text; text late interaction; visual multi-vector; table/element nodes; entity/relationship graph | deterministic sparse plus BGE dense named vectors |
| Context construction | decide boundaries before indexing | fixed windows; headings; parent-child; semantic/adaptive split; contextual retrieval; late chunking; proposition units; document-original-structure/no-chunk control | fixed wins the small frozen corpus; three structural alternatives remain selectable |
| Indexing | persist and filter each representation | Qdrant dense/sparse/multivector; page/section hierarchy; graph/community index; table index | Qdrant server/embedded modes with payload indexes and tenant/ACL filters |
| Query understanding | make the request standalone and classify its scope | unchanged query; conversational rewrite; multi-query/HyDE; decomposition; factual/reasoning/global/visual router | direct single query only |
| Candidate generation | retrieve broad evidence | BM25-style sparse; dense bi-encoder; learned sparse; visual late interaction; table retrieval; hierarchy/graph traversal | sparse, dense, or both |
| Fusion and selection | combine heterogeneous candidate pools | RRF; weighted fusion; query-routed mixture; deduplication/MMR; coarse-to-fine selection | RRF and document-scoped deduplication |
| Reranking | improve ordering after recall | no reranker; cross-encoder; text late interaction; visual late interaction; LLM reranker | no reranker is interactive default; BGE is an explicit high-latency experiment |
| Context assembly | preserve source structure inside the token budget | rank order; source order/DOS RAG; parent expansion; table/figure attachment; compression; subgraph/evidence packing | ranked text passages with citations |
| Generation and reasoning | produce a bounded cited answer | extractive; single-pass grounded generation; decomposition/iterative retrieval; global synthesis | extractive default and one OpenAI-compatible contract |
| Verification and refusal | decide whether evidence supports an answer | deterministic citation checks; NLI/faithfulness judge; answerability classifier; claim-level verification; explicit deflection | citation/support gates pass; held-out abstention is a known failure |
| Evaluation | measure components and end-to-end behavior | retrieval ranking; source recall; grounding; answerability; global coverage; visual retrieval; multilingual; security/leakage; latency/cost/resource | strong local component harness, narrow corpus |

## Technique families and operating regions

### Text-first controls — `established`

- Keep fixed windows, sparse retrieval, BGE-small dense retrieval, RRF, and no
  learned reranker as mandatory controls. Atlas measured them on identical
  inputs, and sparse retained complete required-source recall on the bundled
  corpus.
- Add a document-original-structure/long-context control to future long-document
  work. A 2025 controlled comparison found a simple source-preserving DOS RAG
  baseline matched or beat RAPTOR and ReadAgent on several long-context QA
  tasks under matched token budgets.
- Published leaderboards shortlist embeddings and rerankers; they do not
  replace the corpus-specific held-out comparison. This remains especially
  important for Lithuanian, for which this search found no dedicated retrieval
  benchmark matching Atlas documents and questions.

### Context-preserving chunk representations — `provisional`

- Contextual retrieval prepends generated document context to chunks before
  indexing. Anthropic reports strong retrieval-failure reductions when it is
  combined with BM25 and reranking, but the evidence is vendor-authored and the
  context-generation cost and corpus fit differ from Atlas.
- Late chunking embeds the long document before pooling chunk vectors. The
  official Jina paper and code make the mechanism reproducible, while a 2025
  comparison reports a quality/efficiency tradeoff rather than universal
  dominance. The reference repository has not changed since 2024.
- Semantic/adaptive chunking, propositions, and learned query-time granularity
  are variants of the same boundary/representation decision. They do not earn
  separate portfolio profiles without a distinct operating-region win.

### Query rewriting, decomposition, and adaptive routing — `provisional`

- Conversational rewriting, multi-query fusion, HyDE, and question
  decomposition can recover evidence for non-standalone or multi-hop queries.
  Current 2025–2026 shared-task evidence also shows that more complex expansion
  sometimes loses to a single explicit rewrite.
- A query router is therefore a policy to be learned from workload labels, not
  a rule that every question needs more retrieval. Candidate route labels are
  `local-fact`, `cross-document`, `global-summary`, `visual-layout`, and
  `unanswerable/clarify`.
- Iterative retrieval and test-time corpus feedback remain an advanced
  composition for explicitly complex questions. They are not a new default
  profile and would require bounded step, token, and source-authority controls.

### Visual and layout-aware retrieval — `established family`, `provisional fit`

- ColPali established page-image multi-vector retrieval as a distinct family,
  and ViDoRe v2 specifically targets blind, long, and cross-document queries
  after v1 approached saturation.
- Newer layered/hierarchical multimodal methods combine known ingredients:
  coarse-to-fine document routing, layout graphs, and late-interaction evidence
  ranking. They strengthen the case for a visual/layout profile but do not
  prove that Atlas should index every page visually.
- Visual retrieval is eligible only for questions whose answer depends on
  layout, figures, scans, or tables lost by the text representation. ColPali's
  maintained implementation expects GPU/MPS for its normal path; the current
  32 GB CPU-only host makes resource measurement part of the admission gate.

### Hierarchical and graph retrieval — `established niche`, `contested default`

- RAPTOR targets holistic and multi-step questions through recursively
  clustered summaries. Microsoft GraphRAG targets corpus-level/global
  sensemaking through entity graphs and community reports. LightRAG is a more
  operational graph/vector implementation with incremental update support.
- These are not interchangeable with fact retrieval. Microsoft explicitly
  distinguishes local from global questions; WildGraphBench reports gains for
  some multi-fact aggregation but weaker fine detail/summarization behavior;
  a 2026 scaling study reports graph construction limits and BM25 wins at
  shared scale tiers.
- GraphRAG is therefore excluded from ordinary lookup. It may enter a matched
  comparison only for predeclared corpus-global/entity/community questions.
  RAPTOR may enter only for long-document/global and multi-hop categories, with
  DOS RAG as the required simple control.

### Structured table retrieval — `provisional`

- Table-aware parsing is already an ingestion requirement. A separate table
  representation becomes useful only when questions require row/column,
  numerical, cross-table, or structural reasoning that flattened Markdown
  cannot preserve.
- This family composes with Ledger Lens parsing work and should reuse its
  document adapter rather than introduce an Atlas-only parser stack.

### Verification, answerability, and security — `established need`, `unknown winner`

- GaRAGe and UAEval4RAG show that grounding and deflection remain separate and
  workload-dependent. GroUSE shows that automated RAG evaluators can miss
  important grounded-QA failure modes.
- Atlas's own held-out result agrees: cited statements can be faithful to
  irrelevant passages while no-answer accuracy fails. Retrieval-family work
  cannot close this decision.
- ACL leakage and existing tenant/ACL tests make pre-retrieval authorization
  and leakage tests invariant across every candidate. A quality gain that
  weakens those gates is dominated.

## Benchmark and dataset map

| Workload | Useful public evidence | Limitation to record |
| --- | --- | --- |
| general text retrieval | BEIR, MTEB/MMTEB, BRIGHT | public retrieval rankings do not reproduce client corpus, ACL, or end-to-end generation |
| multilingual retrieval | MMTEB/MIRACL | broad multilingual coverage does not supply a representative Lithuanian company-document task |
| visual page retrieval | ViDoRe v2 | page retrieval is not field extraction or answer correctness; v1 was approaching saturation |
| text and tables | T2-RAGBench and table-RAG work | domain, numerical reasoning, and parser quality remain confounded |
| long/multi-page documents | LongDocURL, MMLongBench-Doc, Deep Search | model/token budgets and generated questions vary; source access may be restricted |
| reasoning-intensive retrieval | BRIGHT, MultiHop-RAG, HotpotQA | benchmark reasoning differs from private-policy lookup; training contamination must be checked |
| global/graph retrieval | WildGraphBench, BenchmarkQED-style query classes | several results are author-owned and LLM-judge dependent; fine-grained details can regress |
| RAG component evaluation | MIRAGE, RAGChecker | component metrics do not establish correct refusal or human usefulness |
| grounding and refusal | GaRAGe, UAEval4RAG, GroUSE | automatic judges require human-calibrated controls |
| realistic local acceptance | Atlas frozen cases plus expanded public documents | small but directly reproducible; must not become the only evidence |

Benchmark leakage/saturation controls: record model training-data declarations
where available; use held-out/private benchmark splits when offered; never tune
on leaderboard test labels; report per-category results; preserve a no-RAG and
simple sparse/DOS control; and do not compare external headline numbers with
local measurements.

## Search protocol

- Search date: 2026-08-04.
- Sources: ACL Anthology, arXiv, official research/project pages, official
  benchmark repositories/leaderboards, GitHub repositories and release/issue
  metadata.
- Main time window: 2024–2026. Older work was retained only for a family origin,
  benchmark definition, or still-used implementation (for example ColBERT,
  Donut, LayoutLMv3, and Table Transformer).
- Included: systematic surveys, controlled comparisons, benchmark papers,
  contrary/negative results, official documentation, and maintained runnable
  implementations.
- Excluded: marketing roundups, popularity-only rankings, unreleased code as an
  adoption candidate, unrelated autonomous browsing, and any license research
  or ranking.

### Reproducible query iterations

| Iteration | Query families | New decision-relevant families |
| ---: | --- | --- |
| 0 | `RAG systematic survey 2025 taxonomy chunking graph multimodal evaluation`; `document AI survey OCR layout VLM benchmarks` | established the lifecycle decomposition and text/layout/visual/graph families |
| 1 | `contextual retrieval late chunking comparative`; `GraphRAG RAPTOR benchmark`; `ColPali ViDoRe`; `multilingual retrieval` | contextual, late-chunk, visual late interaction, hierarchical/global graph, multilingual routing |
| 2 | `document OCR benchmark OmniDocBench OCRBench`; `invoice KIE DocILE SROIE`; `OCR-free layout-aware extraction` | OCR/layout encoder/OCR-free VLM and confidence routing shared with Ledger Lens |
| 3 | official GitHub searches for Docling, PaddleOCR, ColPali, late chunking, GraphRAG, RAPTOR, LightRAG, FlagEmbedding | no method family; separated maintained from stale implementation choices |
| 4 | `RAG query routing adaptive corrective decomposition`; `proposition retrieval semantic chunking`; `document calibration selective prediction` | query rewriting/decomposition/adaptive retrieval and calibrated review |
| 5 | `HyDE multi-query fusion`; `context compression lost in middle`; `schema KIE routing` | multi-query/HyDE and context assembly/compression; no new storage family |
| 6 | 2026 surveys plus `multimodal RAG document graph late interaction routing`; `OCR layout table KIE confidence review` | no new family; results composed known routing, hierarchy, graph, and late-interaction methods |
| 7 | benchmark criticism/failure searches for RAG leakage, graph incompleteness, OCR transfer, VLM multilingual/layout failures | no new family; added contrary evidence and benchmark limits only |

Iterations 6 and 7 are the required consecutive expansions with no new
decision-relevant family. Taxonomy saturation is therefore `PASS` for this
dated scope; it is not a claim that research after 2026-08-04 cannot change the
decision.

## Primary survey and benchmark anchors

- [Scaling Beyond Context (ACL 2026)](https://aclanthology.org/2026.acl-long.204/)
- [Ask in Any Modality (ACL 2025)](https://aclanthology.org/2025.findings-acl.861/)
- [RAG evaluation survey](https://arxiv.org/abs/2504.14891)
- [Test-time Corpus Feedback survey](https://aclanthology.org/2026.findings-eacl.298/)
- [Reasoning-Intensive Retrieval survey](https://aclanthology.org/2026.acl-long.1949/)
- [ViDoRe v2](https://arxiv.org/abs/2505.17166)
- [Stronger long-context baselines](https://aclanthology.org/2025.emnlp-main.1656/)
- [GaRAGe](https://aclanthology.org/2025.findings-acl.875/)
- [UAEval4RAG](https://aclanthology.org/2025.acl-long.415/)
- [WildGraphBench](https://aclanthology.org/2026.findings-acl.679/)
- [Which RAG Paradigm Wins at Scale?](https://arxiv.org/abs/2607.26497)

