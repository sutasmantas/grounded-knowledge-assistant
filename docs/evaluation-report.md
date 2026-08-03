# Retrieval baseline decision

## Decision

Use standalone sparse retrieval as the default for the bundled six-document
policy corpus. It produced the best held-out ranking and the lowest retrieval
latency in the controlled semantic run. Keep dense, hybrid, and reranked
profiles selectable, but do not describe hybrid as universally superior when
this benchmark does not support that claim.

This is a corpus-specific decision, not a rule for client deployments. The
client adoption gate remains: freeze representative documents and questions,
run the same comparison, and select the simplest profile that wins the held-out
quality and operating constraints.

## Controlled semantic result

The runner compared dense, sparse, and hybrid retrieval over the same 56
reviewed cases, six indexed documents, BGE-small dense embeddings, hashed
lexical vectors, `top_k=5`, and extractive generation. Fifty cases are ranking
tests; six security, tenancy, and lifecycle cases are deliberately evaluated
in adversarial regression suites instead.

| Profile | MRR@5 | Recall@5 | nDCG@5 | Held-out MRR@5 | Held-out Recall@5 | Retrieval p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense | 0.9420 | 0.9239 | 0.9160 | 0.9074 | 0.9167 | 57 ms |
| Sparse | **0.9891** | **1.0000** | **0.9885** | **0.9722** | **1.0000** | **13 ms** |
| Hybrid | 0.9674 | **1.0000** | 0.9698 | 0.9444 | **1.0000** | 99 ms |

Sparse improved held-out MRR by 0.0278 over hybrid and reduced measured p95
retrieval latency by 86 ms. Hybrid recovered all expected documents but ranked
them less effectively. Dense missed relevant sources, especially on
multi-document cases.

The run recorded a 2,269 ms index build, 1.72 MB traced Python allocator peak,
and an estimated hosted-provider cost of USD 0.00. Native model/runtime memory
is excluded from that allocator figure. These runtime measurements are
machine-specific and should only be compared within a controlled run.

## Deterministic regression result

The no-model hash run exists for CI and fast regression checks. It is not a
semantic production recommendation.

| Profile | MRR@5 | Recall@5 | nDCG@5 | Retrieval p95 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 0.8370 | 0.8152 | 0.8034 | 14 ms |
| Sparse | **0.9891** | **1.0000** | **0.9885** | **9 ms** |
| Hybrid | 0.9348 | **1.0000** | 0.9430 | 41 ms |
| Hybrid + lexical rerank | 0.9674 | **1.0000** | 0.9733 | 40 ms |

## Important limitation

The corpus is small and policy-oriented. Sparse retrieval scoring 1.0 on the
current paraphrase category indicates that those questions retain enough
lexical signal to be solved without semantic retrieval. The benchmark
therefore cannot justify disabling dense or hybrid retrieval for a new client
corpus. It can justify the narrower decision that hybrid adds cost without a
quality gain on this seeded corpus.

No profile solves the abstention problem. Overall no-answer accuracy is 0.25,
and held-out no-answer accuracy is 0.0 for all three semantic profiles. The
next quality work should improve evidence calibration rather than add another
ranking layer.

## Capability dispositions

- Latest-version filtering and superseded-vector removal run in the document
  lifecycle suite; they are not ranking metrics.
- Cross-tenant canaries, restricted principal/group access, and pre-retrieval
  ACL filters run in the tenant adversarial suite.
- Direct and indirect prompt-injection cases run in the deterministic security
  suite. Bounded pattern quarantine is not presented as general model-level
  injection resistance.
- ColBERT remains an experiment. The prior controlled bake-off lowered ranking
  quality and added material latency, so it did not pass the adoption gate.

## Reproduce

```bash
python -m app.evaluation \
  --embedding-provider fastembed \
  --reranker-provider lexical \
  --profiles dense sparse hybrid \
  --output docs/evaluation-semantic-baseline-v3.json \
  --raw-output docs/evaluation-semantic-baseline-v3-cases.jsonl
```

The machine-readable semantic and deterministic results are:

- [`evaluation-semantic-baseline-v3.json`](evaluation-semantic-baseline-v3.json)
- [`evaluation-semantic-baseline-v3-cases.jsonl`](evaluation-semantic-baseline-v3-cases.jsonl)
- [`evaluation-deterministic-baseline-v3.json`](evaluation-deterministic-baseline-v3.json)
- [`evaluation-deterministic-baseline-v3-cases.jsonl`](evaluation-deterministic-baseline-v3-cases.jsonl)

The [reranker bake-off](reranker-bakeoff.md) remains the controlled evidence for
the optional learned reranking profiles.
