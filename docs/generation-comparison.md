# Measured generation decision

Atlas compared its no-key extractive generator with a real local
OpenAI-compatible model on the same 20 held-out cases used by the semantic
release gate. The candidate was `ggml-org/gemma-3-1b-it-GGUF` served by the
pinned llama.cpp container recorded in
`atlas-p2-generation-resources.json`.

## Predeclared gate

The candidate could replace the default only if it:

1. completed every case with complete provider token accounting;
2. recorded runner/model resource use;
3. stayed at or above the extractive baseline for citation validity,
   citation completeness, semantic citation support, semantic answer
   faithfulness, and abstention accuracy;
4. improved semantic support by at least 0.02; and
5. kept cold p95 generation latency at or below 15 seconds.

The benchmark captures uncited model text for scoring, but the production
generator still rejects that same text. This preserves the real failure shape
without weakening the serving path.

## Cold-cache result

| Metric | Extractive | Local Gemma 3 1B |
| --- | ---: | ---: |
| Completed cases | 20/20 | 20/20 |
| Production rejection cases | 2/20 | 19/20 |
| Citation validity | 1.0000 | 0.0000 |
| Citation completeness | 1.0000 | 0.0000 |
| Mean semantic citation support | 0.973520 | 0.000000 |
| Mean semantic answer faithfulness | 0.973520 | 0.000000 |
| Abstention accuracy | 0.90 | 0.30 |
| Provider token coverage | not applicable | 20/20 |
| Total provider tokens | not applicable | 16,992 |
| Provider API cost | USD 0.00 | USD 0.00 |
| p50 generation latency | 1 ms | 18,316 ms |
| p95 generation latency | 1 ms | 31,212 ms |

The HHEM controls remained separated (`0.939087` supported and `0.007601`
unsupported). The candidate failed every quality noninferiority check, the
quality-gain check, and the latency check. Atlas therefore keeps extractive as
the default. The candidate remains selectable for client-specific experiments;
this measurement is not evidence that every larger local or hosted model will
fail.

The aggregate artifact is
`atlas-p2-generation-comparison.json`; the 40 provider/case rows are in
`atlas-p2-generation-comparison-cases.jsonl`. Per-category failures, tokens,
latency, resource limits, model bytes, and the complete promotion decision are
preserved in those artifacts.

## Reproduction

Start any OpenAI-compatible local server, install the semantic extra with the
project's pinned Transformers 4.x range, and run:

```bash
python -m app.generation_evaluation \
  --candidate-base-url http://127.0.0.1:18080/v1 \
  --candidate-model gemma-3-1b-it \
  --resource docs/atlas-p2-generation-resources.json \
  --output artifacts/generation-comparison.json \
  --raw-output artifacts/generation-comparison-cases.jsonl
```

Use a newly started model server for the cold-cache latency result. Reusing the
same llama.cpp process may reuse prompt state and produces a separate warm-cache
number that must not replace the cold release artifact.

## Verification

- full core profile: Ruff clean; 193 tests passed and the five expected
  Docling-extra tests skipped in a clean `python:3.11-slim` container;
- affected generation/semantic/accounting tests: 21 passed;
- production image: `docker build -t atlas-p2-generation:verify .` passed,
  including the frontend typecheck and production build;
- live no-key container: readiness returned metadata/jobs `ok`, Docker health
  became `healthy`, and `/api/health` reported `generation_provider` as
  `extractive`.

An all-extras run in the pre-existing `atlas-docling-env:1` image failed one
unrelated scanned-PDF test because that cached image lacks `libxcb.so.1`.
Atlas raised its existing explicit `ParserUnavailableError`; the clean core
profile and every affected test passed.
