# Answer faithfulness and citation evaluation

## Decision

The held-out extractive answers pass the answer-faithfulness and citation gate,
but the system does not pass abstention. Keep the deterministic citation
contract and pinned local HHEM judge as release checks; address evidence
coverage/refusal separately rather than treating faithful irrelevant text as a
correct answer.

## Why this design

Retrieval quality, answer relevance, faithfulness, and citation correctness are
different failure surfaces. RAGAS, ARES, and RAGChecker all motivate measuring
them separately. Atlas therefore combines:

- deterministic citation validity: every emitted rank exists;
- citation completeness: every factual paragraph includes a rank;
- exact support for the extractive profile: the cited statement occurs in the
  cited passage;
- semantic citation support: HHEM scores every statement/passage link;
- semantic answer faithfulness: HHEM scores each statement against the union
  of passages it cites;
- the existing retrieval and no-answer metrics, reported separately.

The local judge is
`vectara/hallucination_evaluation_model` at pinned revision
`8e4a2e6e96c708cc76c2344f7e4757df2515292c`. Transformers is constrained to
the compatible 4.x line. No document or answer is sent to an external API.

## Controlled run

- 20 enabled held-out cases: 18 answerable and two expected to abstain;
- fixed chunking and sparse retrieval;
- deterministic hash embeddings because the sparse profile does not consume
  dense vectors;
- extractive generation and `top_k=5`;
- 52 claim-to-citation links scored semantically;
- 60,473 ms evaluation time after model initialization on the recorded host.

The runner asserts the expected case count. An earlier 23-case artifact was
discarded after it exposed that capability-gated records had been included.

## Result

| Metric | Result | Gate |
| --- | ---: | ---: |
| Citation validity | 1.0000 | 1.0000 |
| Citation completeness | 1.0000 | 1.0000 |
| Exact citation support | 1.0000 | 1.0000 |
| Mean semantic citation support | 0.9735 | at least 0.5000 |
| Mean semantic answer faithfulness | 0.9735 | at least 0.5000 |
| Minimum semantic citation-link score | 0.8803 | diagnostic |
| Held-out no-answer accuracy | **0.0000** | reported separately |

The semantic judge also passed its controls:

| Control | Score | Required |
| --- | ---: | ---: |
| Directly supported refund statement | 0.9391 | at least 0.5000 |
| Unsupported cryptocurrency statement | 0.0076 | at most 0.5000 |

All citation/faithfulness gate checks pass. The controls matter because an
evaluator that assigns high support to every pair would otherwise make the
release look safer than it is.

## Failure analysis

Both expected-abstention cases returned cited but irrelevant text:

- `unanswerable-cooking` returned a public-computer security rule;
- `filter-remote-in-billing` returned a billing accrual rule despite the
  excluding collection scope.

Those answers are faithful to the passages they cite, which is precisely why
faithfulness cannot stand in for answer relevance or refusal accuracy. The
profile winner matrix records no winner for these categories. A later
evidence-coverage policy must improve abstention on representative data
without hiding relevant answers.

## Reproduce

```bash
pip install -e ".[semantic-eval]"
python -m app.semantic_evaluation \
  --output artifacts/semantic-evaluation.json \
  --raw-output artifacts/semantic-evaluation-cases.jsonl
```

Committed evidence:

- [`semantic-evaluation-v1.json`](semantic-evaluation-v1.json)
- [`semantic-evaluation-v1-cases.jsonl`](semantic-evaluation-v1-cases.jsonl)
- [`../evals/semantic-evaluation-manifest.json`](../evals/semantic-evaluation-manifest.json)

Primary references:

- [RAGAS](https://arxiv.org/abs/2309.15217)
- [ARES](https://arxiv.org/abs/2311.09476)
- [RAGChecker](https://arxiv.org/abs/2408.08067)
- [HHEM-2.1-Open model card](https://huggingface.co/vectara/hallucination_evaluation_model)
