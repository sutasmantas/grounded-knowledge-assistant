# Chunking bake-off

## Decision

Keep fixed overlapping windows as the default for the bundled corpus. Retain
heading-aware, parent-child, and Docling hybrid chunking as selectable
experiments, but do not promote them without a client-corpus win.

The result is deliberately conservative: the hierarchy-aware methods improve
some rankings, but each loses required-source recall and expands the index.
Docling's tokenizer-aware method also makes indexing much slower.

## Methods under test

| Profile | What is indexed | What is returned |
| --- | --- | --- |
| Fixed | Overlapping character windows | The matched window |
| Heading-aware | Section windows with the heading repeated | The matched section window |
| Parent-child | Smaller child windows | Their larger containing section |
| Docling hybrid | Document hierarchy split to the BGE tokenizer limit, with peer merging | The contextualized Docling chunk |

Docling hybrid is the additional research-informed method. It uses Docling's
native document model, `HybridChunker`, a Hugging Face tokenizer for the same
`BAAI/bge-small-en-v1.5` embedding model, heading contextualization, and peer
merging. This tests an maintained implementation of structure-aware,
tokenizer-aware chunking rather than an Atlas-specific approximation.

## Experimental control

The original sample documents were shorter than the 950-character target, so
the controlled documents were expanded with multiple sections, realistic
distractors, Markdown tables, and multi-document questions. Every profile used:

- the same six documents and 50 frozen cases;
- the same 30 development and 20 held-out cases;
- `top_k=5`, `candidate_k=24`, and extractive generation;
- 950-character target windows and 140-character overlap where applicable;
- FastEmbed `BAAI/bge-small-en-v1.5` dense vectors;
- separate sparse-only and dense+sparse hybrid runs.

The adoption gate was fixed before running the experiment: promote a method
only when it improves held-out retrieval for a relevant category without an
unacceptable index, latency, or implementation penalty.

## Results

### Sparse retrieval

| Profile | Records | Index bytes | Build ms | MRR@5 | Recall@5 | nDCG@5 | Held-out MRR@5 | Held-out Recall@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed | 19 | 205,381 | 1,282 | 0.9891 | **1.0000** | **0.9885** | 0.9722 | **1.0000** |
| Heading-aware | 51 | 328,261 | 1,392 | **1.0000** | 0.9891 | 0.9833 | **1.0000** | 0.9722 |
| Parent-child | 51 | 328,261 | 1,635 | **1.0000** | 0.9891 | 0.9833 | **1.0000** | 0.9722 |
| Docling hybrid | 51 | 328,261 | 17,884 | **1.0000** | 0.9783 | 0.9773 | **1.0000** | 0.9722 |

### Hybrid retrieval

| Profile | Records | Index bytes | Build ms | MRR@5 | Recall@5 | nDCG@5 | Held-out MRR@5 | Held-out Recall@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed | 19 | 205,381 | 1,908 | 0.9674 | **1.0000** | **0.9698** | **0.9444** | **1.0000** |
| Heading-aware | 51 | 328,261 | 1,942 | **0.9783** | 0.9891 | 0.9688 | **0.9444** | 0.9722 |
| Parent-child | 51 | 328,261 | 1,705 | **0.9783** | 0.9891 | 0.9688 | **0.9444** | 0.9722 |
| Docling hybrid | 51 | 328,261 | 17,447 | 0.9674 | 0.9674 | 0.9489 | 0.9167 | 0.9444 |

The figures are single-machine observations, so the quality and resource
direction matters more than small timing differences between the first three
profiles.

## Failure analysis

- Heading-aware and parent-child each miss one required source in the held-out
  `multi-refund-close-flow` case. Their MRR movement therefore does not justify
  the loss in multi-document coverage.
- Docling hybrid loses another required source under hybrid retrieval. It has
  the weakest hybrid nDCG and held-out recall in the comparison.
- All three hierarchy-aware profiles produce 2.68 times as many index records
  and use about 60% more index storage than fixed windows.
- Docling hybrid spends roughly 17.5 seconds building this small index, versus
  1.3–1.9 seconds for the other profiles. Model/tokenizer initialization
  dominates this local run.
- Parent-child matches heading-aware here because the controlled sections are
  usually shorter than its child window. The return-parent seam works, but the
  corpus supplies no measured reason to pay for it.

Two correctness faults found during the experiment were fixed before these
artifacts were generated. Parent context IDs are now document-scoped, avoiding
cross-document collisions during deduplication. nDCG also credits each expected
document once, preventing repeated chunks from inflating the score above 1.0.

## Adoption rule

Use fixed windows for this demo. Re-run the four-way bake-off on representative
client files before changing the default. A hierarchy-aware method should be
promoted only when it improves held-out required-source recall or an important
long-document category without an unacceptable index or latency increase.

## Reproduce

Install the optional parser benchmark dependencies for Docling, then run both
retrieval profiles:

```bash
pip install -e ".[dev,parsing-benchmark]"

python -m app.chunking_benchmark \
  --embedding-provider fastembed \
  --retrieval-profile sparse \
  --output artifacts/chunking-sparse.json \
  --raw-output artifacts/chunking-sparse-cases.jsonl

python -m app.chunking_benchmark \
  --embedding-provider fastembed \
  --retrieval-profile hybrid \
  --output artifacts/chunking-hybrid.json \
  --raw-output artifacts/chunking-hybrid-cases.jsonl
```

Committed evidence:

- [`chunking-semantic-sparse-v2.json`](chunking-semantic-sparse-v2.json)
- [`chunking-semantic-sparse-v2-cases.jsonl`](chunking-semantic-sparse-v2-cases.jsonl)
- [`chunking-semantic-hybrid-v2.json`](chunking-semantic-hybrid-v2.json)
- [`chunking-semantic-hybrid-v2-cases.jsonl`](chunking-semantic-hybrid-v2-cases.jsonl)
