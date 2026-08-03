# Retrieval profile winner matrix

## Decision

Keep sparse retrieval as the bundled default. It wins exact, paraphrase, and
multi-document categories on the frozen corpus, ties on table questions, and
has the best aggregate quality/resource tradeoff. Dense and hybrid remain
selectable because a client corpus with weaker lexical signal may reverse the
result.

No profile wins the unanswerable or collection-filter abstention categories.
That is recorded as a shared failure, not assigned to an arbitrary winner.

## Controlled result by category

Values are from `docs/evaluation-semantic-baseline-v3.json`. The winner rule is:
preserve required-source recall first, then compare nDCG, MRR, latency, and
complexity. Categories with identical task metrics remain explicit ties.

| Category | Dense | Sparse | Hybrid | Winner | Reason |
| --- | --- | --- | --- | --- | --- |
| Exact | R 0.9118 / nDCG 0.9184 | **R 1.0000 / nDCG 1.0000** | R 1.0000 / nDCG 0.9736 | Sparse | Complete recall and perfect ranking |
| Paraphrase | R 0.9286 / nDCG 0.8929 | **R 1.0000 / nDCG 1.0000** | R 1.0000 / nDCG 0.9473 | Sparse | Frozen paraphrases retain enough lexical signal for the sparse profile |
| Multi-document | R 0.7500 / nDCG 0.7558 | **R 1.0000 / nDCG 0.9598** | R 1.0000 / nDCG 0.9492 | Sparse | Complete source coverage and best ordering |
| Boundary | **R 1.0000 / nDCG 1.0000** | R 1.0000 / nDCG 0.9590 | **R 1.0000 / nDCG 1.0000** | Dense–hybrid tie | Both rank the correct boundary source perfectly |
| Table | **R 1.0000 / nDCG 1.0000** | **R 1.0000 / nDCG 1.0000** | **R 1.0000 / nDCG 1.0000** | Three-way tie | Retrieval profile does not distinguish these two parsed-table cases |
| Unanswerable | no-answer 0.5000 | no-answer 0.5000 | no-answer 0.5000 | No winner | Every profile answers one of two cases that should abstain |
| Collection filter | no-answer 0.0000 | no-answer 0.0000 | no-answer 0.0000 | No winner | The retrieval threshold admits evidence despite an intentionally excluding filter |

`R` is required-document recall at five. MRR is omitted from the compact table
when recall and nDCG already determine the decision; the source artifact
retains it.

## Operational comparison

The Phase A0 v3 run records:

| Profile | Overall MRR@5 | Overall Recall@5 | Overall nDCG@5 | Fusion | Provider cost |
| --- | ---: | ---: | ---: | --- | ---: |
| Dense | 0.9420 | 0.9239 | 0.9160 | None | $0.00 local |
| Sparse | **0.9891** | **1.0000** | **0.9885** | None | $0.00 local |
| Hybrid | 0.9674 | **1.0000** | 0.9698 | RRF | $0.00 local |

Sparse also avoids dense-query inference and fusion in the default request
path. Hybrid is therefore not promoted merely because it combines more
techniques.

## Cross-experiment checks

- BGE-M3 improves aggregate dense and hybrid ordering but lowers the
  multi-document category ranking and adds substantial CPU/memory cost. It does
  not displace the sparse bundled default.
- Heading-aware, parent-child, and Docling hybrid chunking each lose held-out
  required-source recall relative to fixed windows.
- Learned rerankers do not change required-source recall. The BGE
  cross-encoder's small nDCG gain costs roughly 60 times the held-out p95
  latency, so no learned reranker is used interactively.
- Parser routing remains format-specific: pypdf for ordinary text PDFs and
  Docling for the structured/scanned quality path. Retrieval cannot recover
  structure that parsing has already flattened.

## Client adaptation rule

Replace or extend the frozen questions with representative client cases and
retain a held-out split. Promote another profile only if it improves the
client's important categories without weakening required-source recall or
violating its latency/cost budget. Published model benchmarks shortlist a
candidate; this corpus-level matrix decides deployment.
