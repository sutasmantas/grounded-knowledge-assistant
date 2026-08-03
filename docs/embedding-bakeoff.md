# Embedding bake-off

## Decision

Keep `BAAI/bge-small-en-v1.5` as the local semantic default. BGE-M3 is a
selectable quality candidate for multilingual or longer-document work, but it
does not earn promotion on this small English corpus. Its ranking gains are
real, yet uneven, and come with a much larger model and materially slower CPU
retrieval.

`text-embedding-3-large` at 1,024 dimensions is the hosted candidate. It is
implemented behind the same embedding interface and has a reproducible,
credential-gated run, but no quality or cost result is claimed without an API
key.

## Why these candidates

- BGE small is the current 384-dimension local baseline.
- BGE-M3 is the required local challenger. Its official model card describes a
  1,024-dimension, multilingual model with up to 8,192 input tokens and dense,
  sparse, and multi-vector capabilities. This experiment isolates dense
  embeddings so the existing sparse representation remains controlled.
- OpenAI documents `text-embedding-3-large` as its most capable embedding model
  for English and non-English tasks. The API supports shortening it from 3,072
  dimensions; 1,024 dimensions provides a like-sized hosted comparison to
  BGE-M3.

## Experimental control

Every completed candidate uses:

- the same six documents and 50 frozen cases;
- the same 30 development and 20 held-out split;
- fixed chunking with 19 indexed records;
- separate dense and dense+sparse hybrid retrieval;
- `top_k=5`, `candidate_k=24`, lexical reranking, and extractive generation.

The report captures per-category and per-case quality, model-load and index
times, retrieval latency, index bytes, Python allocation peak, resident-memory
snapshots, token usage, and provider cost.

## Quality result

| Candidate | Profile | Overall MRR@5 | Overall Recall@5 | Overall nDCG@5 | Held-out MRR@5 | Held-out Recall@5 | Held-out nDCG@5 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BGE small | Dense | 0.9420 | 0.9239 | 0.9160 | 0.9074 | 0.9167 | 0.8883 |
| BGE-M3 | Dense | **0.9638** | **0.9565** | **0.9394** | **0.9352** | **0.9444** | **0.9087** |
| BGE small | Hybrid | 0.9674 | **1.0000** | 0.9698 | 0.9444 | **1.0000** | 0.9522 |
| BGE-M3 | Hybrid | **0.9891** | **1.0000** | **0.9826** | **0.9722** | **1.0000** | **0.9682** |

BGE-M3 is the quality winner in aggregate. Under hybrid retrieval it improves
held-out nDCG by 0.0160 and MRR by 0.0278 without losing held-out recall.
That does not make it the automatic production winner because the gains are
not uniform and the operational difference is large.

## Category and operational tradeoffs

- Dense exact-question nDCG rises from 0.9184 to 0.9555, and paraphrase nDCG
  rises from 0.8929 to 0.9379.
- Dense multi-document nDCG falls from 0.7558 to 0.7098, with recall falling
  from 0.7500 to 0.6250.
- Hybrid exact and paraphrase nDCG improve by 0.0217 and 0.0263 respectively,
  but multi-document nDCG falls by 0.0374. Hybrid required-source recall stays
  complete.

| Candidate | Warm-cache load | Index build | Index bytes | RSS after evaluation | Dense p95 | Hybrid p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BGE small | 611 ms | 2,482 ms | 205,381 | 305 MB | 51 ms | 89 ms |
| BGE-M3 | 67,095 ms | 35,439 ms | 303,686 | 2,262 MB | 591 ms | 1,199 ms |

The resident-set values are snapshots from a sequential single-process run and
include the Python runtime and shared native allocations, so they are
directional rather than isolated model maxima. The BGE-M3 cache itself occupied
2,293,331,703 bytes on the measured Windows host.

For this demo, BGE small plus sparse-default retrieval is the better deployable
choice. BGE-M3 should be re-tested when the client corpus is multilingual,
contains longer semantic units, or values the measured ranking gain enough to
provide suitable inference hardware.

## Hosted candidate disposition

The hosted candidate is intentionally not marked complete. Without
`ATLAS_EMBEDDING_API_KEY`, the runner emits:

- `status: credential_required`;
- the exact candidate, model, dimensions, base URL, and credential variable;
- a reproducible command;
- `null` quality and provider-cost results.

When a credential is available, the same runner counts provider-reported input
tokens and applies the dated price stored in the manifest. It never substitutes
a local model or invents a hosted result.

## Reproduce

```bash
pip install -e ".[embedding-benchmark]"
python -m app.embedding_benchmark \
  --output artifacts/embedding.json \
  --raw-output artifacts/embedding-cases.jsonl
```

To execute only the hosted candidate after setting the credential in the
process environment:

```bash
python -m app.embedding_benchmark --candidates openai-large-1024
```

Committed evidence:

- [`embedding-benchmark-v1.json`](embedding-benchmark-v1.json)
- [`embedding-benchmark-v1-cases.jsonl`](embedding-benchmark-v1-cases.jsonl)
- [`../evals/embedding-manifest.json`](../evals/embedding-manifest.json)

Primary references:

- [BGE-M3 official model card](https://huggingface.co/BAAI/bge-m3)
- [FlagEmbedding repository](https://github.com/FlagOpen/FlagEmbedding)
- [OpenAI `text-embedding-3-large` model page](https://developers.openai.com/api/docs/models/text-embedding-3-large)
- [OpenAI embedding dimension-shortening announcement](https://openai.com/index/new-embedding-models-and-api-updates/)
