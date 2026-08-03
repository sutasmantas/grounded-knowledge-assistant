# Reranker bake-off

## Decision

Keep semantic hybrid retrieval without a learned reranker as the interactive
default. Retain the BGE cross-encoder adapter as an explicit experiment, but do
not promote it for this corpus. Reject MiniLM and ColBERT as quality profiles
for the current cases.

## Candidate selection

The comparison follows the repository's E05 research gate:

- no reranker is the production baseline;
- `Xenova/ms-marco-MiniLM-L-6-v2` is the 80 MB low-cost cross-encoder control;
- `BAAI/bge-reranker-base` is the research-shortlisted BGE cross-encoder;
- `answerdotai/answerai-colbert-small-v1` is the existing late-interaction
  candidate.

All three learned models are supported by FastEmbed's maintained ONNX model
registry. Atlas uses its public scoring APIs behind one local `Reranker`
interface; no vendor example application or source code is copied.

Primary references:

- FastEmbed supported models:
  https://qdrant.github.io/fastembed/examples/Supported_Models/
- FlagEmbedding model and reranker documentation:
  https://github.com/FlagOpen/FlagEmbedding
- reranking quality/latency study:
  https://aclanthology.org/2024.emnlp-main.981/
- ColBERTv2:
  https://arxiv.org/abs/2112.01488

## Experimental control

Every candidate uses the same:

- six controlled documents and 50 runnable questions;
- frozen 30-case development and 20-case held-out split;
- fixed chunking with 19 indexed chunks;
- `BAAI/bge-small-en-v1.5` dense embeddings;
- hybrid dense/sparse candidate retrieval with `candidate_k=24`;
- `top_k=5` and extractive generation.

Each learned model receives one warm-up query before evaluation. Warm-up time
is reported separately. Latency values below are steady-state local CPU
measurements from the same run. Model artifact size comes from FastEmbed's
registry. Python allocation peaks exclude ONNX Runtime native memory.

## Result

| Candidate | Artifact | Overall MRR@5 | Overall nDCG@5 | Held-out MRR@5 | Held-out nDCG@5 | Held-out Recall@5 | Held-out p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| None | 0 MB | 0.9674 | 0.9698 | 0.9444 | 0.9522 | 1.0000 | 72 ms |
| MiniLM cross-encoder | 80 MB | 0.9674 | 0.9698 | 0.9444 | 0.9501 | 1.0000 | 1,344 ms |
| BGE cross-encoder | 1,040 MB | 0.9783 | 0.9813 | 0.9444 | 0.9590 | 1.0000 | 4,304 ms |
| ColBERT | 130 MB | 0.9583 | 0.9626 | 0.9352 | 0.9473 | 1.0000 | 1,603 ms |

BGE improves held-out nDCG by 0.0068 without changing held-out MRR or recall,
but its held-out p95 is about 60 times the baseline. The gain is too small for
the interactive profile. It remains selectable for offline or client-specific
experiments where ranking value and hardware justify a new measurement.

MiniLM does not improve overall quality, slightly lowers held-out nDCG, and is
about 19 times slower at held-out p95. ColBERT lowers both held-out MRR and
nDCG while adding roughly 1.6 seconds p95. Neither passes the adoption gate.

Per-case results matter: BGE improves some contract and multi-document
rankings, but moves the correct source down for other held-out contract cases.
The aggregate gain is not uniform evidence of a safer quality mode.

## Reproduce

```bash
python -m app.reranker_benchmark \
  --output artifacts/reranker-semantic.json \
  --raw-output artifacts/reranker-semantic-cases.jsonl
```

Committed artifacts:

- [`reranker-semantic.json`](reranker-semantic.json)
- [`reranker-semantic-cases.jsonl`](reranker-semantic-cases.jsonl)
- [`../evals/reranker-manifest.json`](../evals/reranker-manifest.json)
