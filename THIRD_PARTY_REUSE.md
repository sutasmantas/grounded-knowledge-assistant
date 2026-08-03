# Third-party reuse and implementation references

Atlas is original application code. This repository does not copy a showcase
application or vendor sample into the product. Maintained libraries provide
focused infrastructure behind Atlas-owned adapters.

| Component | Project | How Atlas uses it |
| --- | --- | --- |
| Vector storage and filtered search | [Qdrant client](https://github.com/qdrant/qdrant-client) | One official client API selects embedded path mode or external server URL mode; Atlas supplies measured vectors, filter payloads, and lifecycle policy |
| Local embeddings and reranking | [FastEmbed](https://github.com/qdrant/fastembed) | Version 0.8.0 ONNX APIs for BGE small embeddings, BGE cross-encoder scores, and ColBERT MaxSim behind Atlas-owned provider interfaces; no FastEmbed source is copied |
| Large local embedding experiment | [Sentence Transformers](https://github.com/huggingface/sentence-transformers) | Optional BGE-M3 dense inference through an Atlas-owned embedding adapter; no Sentence Transformers source is copied |
| Local faithfulness judge | [HHEM-2.1-Open](https://huggingface.co/vectara/hallucination_evaluation_model) | Optional claim/passage support scoring at a pinned model revision; deterministic citation-contract checks remain Atlas code |
| PDF extraction | [pypdf](https://github.com/py-pdf/pypdf) | Lightweight text extraction for the current parser profile |
| Structured parsing and chunking | [Docling](https://github.com/docling-project/docling) | Optional quality parser and tokenizer-aware `HybridChunker` benchmark behind Atlas-owned routing; no Docling source is copied |
| API service | [FastAPI](https://github.com/fastapi/fastapi) | HTTP routing, validation, and generated API schema |
| Connector HTTP client | [httpx](https://github.com/encode/httpx) | Streaming GET with redirects disabled so Atlas validates every hop itself; no httpx source is copied |
| Local generation runner | [llama.cpp](https://github.com/ggml-org/llama.cpp) | CPU-capable OpenAI-compatible server used as a measured local provider; Atlas keeps its existing generator contract |
| JWT/JWKS validation | [PyJWT](https://github.com/jpadilla/pyjwt) | Bearer-token signature and standard-claim validation with JWKS refresh; Atlas maps only verified claims into `AccessContext` |

The P2 repository- and component-level comparison, including rejected broader
frameworks, is pinned in `docs/P2_GITHUB_REUSE_AUDIT.md`.

Implementation references used for experiment design, not copied code:

- [Qdrant hybrid search documentation](https://qdrant.tech/documentation/search/hybrid-queries/)
  for dense/sparse candidate fusion and metadata filtering.
- [BEIR](https://github.com/beir-cellar/beir) and
  [MTEB](https://huggingface.co/mteb) for retrieval metric and benchmark
  conventions.
- [ColBERT](https://github.com/stanford-futuredata/ColBERT) and the
  [EMNLP 2024 reranking study](https://aclanthology.org/2024.emnlp-main.981/)
  for the measured quality/latency tradeoff.
- [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) for the
  `BAAI/bge-reranker-base` model and cross-encoder comparison target. Atlas
  calls it through FastEmbed rather than adapting FlagEmbedding source.
- [BGE-M3's official model card](https://huggingface.co/BAAI/bge-m3) for its
  1,024-dimension dense representation, 8,192-token context, multilingual
  scope, and recommended Sentence Transformers inference path.
- [Sentence Transformers](https://github.com/huggingface/sentence-transformers)
  for the MS MARCO MiniLM reranking model family used as the lightweight
  cross-encoder control; Atlas calls the FastEmbed ONNX conversion.
- [OpenAI's `text-embedding-3-large` model page](https://developers.openai.com/api/docs/models/text-embedding-3-large)
  and [dimension-shortening announcement](https://openai.com/index/new-embedding-models-and-api-updates/)
  for the credentialed 1,024-dimension hosted candidate and dated cost input.
- [RAGAS](https://arxiv.org/abs/2309.15217),
  [RAGChecker](https://arxiv.org/abs/2408.08067), and
  [ARES](https://arxiv.org/abs/2311.09476) for separating retrieval quality,
  answer faithfulness, answer relevance, and claim-level diagnostics rather
  than collapsing them into one score.
- [HHEM-2.1-Open](https://huggingface.co/vectara/hallucination_evaluation_model)
  for the no-key semantic claim-support judge. Atlas pins revision
  `8e4a2e6e96c708cc76c2344f7e4757df2515292c`, and the release gate includes
  supported/unsupported controls because judge output is not ground truth.
- [Docling chunking concepts](https://docling-project.github.io/docling/concepts/chunking/)
  for the additional structure-aware, tokenizer-aware chunking experiment.
- [RAPTOR](https://github.com/parthsarthi03/raptor) and
  [Late Chunking](https://arxiv.org/abs/2409.04701) were reviewed as alternative
  hierarchical approaches. They were not implemented because the controlled
  gate first called for the maintained Docling method already compatible with
  the measured parsing path.

## Parser and connector design references

Design influences for the Phase B parser registry and connectors. No source was
copied from these projects.

- [OWASP Server Side Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
  supplied the control set for the "arbitrary external host" case that the URL
  connector implements: protocol allow list, resolving the hostname and
  applying the deny list to every A/AAAA record, blocking metadata and private
  ranges, and disabling the HTTP client's own redirect support. Atlas adds
  per-hop revalidation and peer-address verification because disabling
  redirects alone does not cover a chain the application follows itself.
- [RFC 3986 §3.2.1](https://www.rfc-editor.org/rfc/rfc3986#section-3.2.1)
  deprecates userinfo in URIs; the connector rejects embedded credentials
  rather than forwarding them upstream.
- [RFC 1918](https://www.rfc-editor.org/rfc/rfc1918),
  [RFC 3927](https://www.rfc-editor.org/rfc/rfc3927),
  [RFC 4193](https://www.rfc-editor.org/rfc/rfc4193) and
  [RFC 6890](https://www.rfc-editor.org/rfc/rfc6890) define the private,
  link-local and special-purpose ranges; the implementation uses Python's
  `ipaddress` classification rather than a hand-written CIDR list.
- Cloud instance metadata endpoints are taken from the
  [AWS IMDS documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html),
  [Google Cloud metadata server documentation](https://cloud.google.com/compute/docs/metadata/overview)
  and
  [Azure IMDS documentation](https://learn.microsoft.com/en-us/azure/virtual-machines/instance-metadata-service).
- [LlamaIndex readers](https://github.com/run-llama/llama_index) and
  [Unstructured connectors](https://github.com/Unstructured-IO/unstructured)
  were reviewed as connector-shape references. Both attach parsing, chunking
  and identity decisions to the connector itself. Atlas deliberately inverts
  that: connectors only discover, fetch and describe, and one synchronization
  engine owns checksums, versioning, deletion policy and ACLs so a new
  connector cannot weaken the lifecycle rules.
- [Docling document conversion](https://docling-project.github.io/docling/)
  remains the structured DOCX/HTML and scanned-PDF route. Its measured result
  on the pinned fixtures is in `docs/parsing-benchmark-v2.json`; the shipped
  registry's behaviour with core dependencies only is in
  `docs/parser-registry-v1.json`.
- The DOCX fallback reads `word/document.xml` directly using the
  [WordprocessingML element reference](https://learn.microsoft.com/en-us/office/open-xml/word/)
  through the standard library `zipfile` and `xml.etree`. It exists only so the
  no-key container can read a DOCX; it reports itself as degraded and recovers
  30 of the 34 reference table rows.

## Asynchronous execution decision

Atlas does not hide ingestion inside FastAPI `BackgroundTasks`, because that
would not provide persisted progress, restart recovery, retry history, or a
dead-letter state. The bundled SQLite worker implements the small,
single-process public-demo profile without copying a queue project.

The job contract was compared against:

- [FastAPI background-task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/)
  for the boundary between same-process convenience work and an external queue;
- [RQ job lifecycle documentation](https://python-rq.org/docs/jobs/) for
  explicit cancellation and retained job state;
- [Temporal documentation](https://docs.temporal.io/) for the stronger
  crash-recovery profile appropriate to long-lived, multi-service workflows.

RQ/Celery/Temporal remain runner adapters for client deployments that actually
need Redis, RabbitMQ, multi-server workers, durable timers, or workflow replay.

The parser bake-off reuses four PDF/Markdown fixture pairs from Docling commit
`91fa745b3228fa0df0510d76eb94956b063054e1` plus scanned-PDF, DOCX, and HTML
pairs from commit `52d8a6f24de7318a9ad4be2a7361ba93fc81a5c1`, under its MIT
license. The exact paths, document classes, expected anchors, and warning about
representation bias are recorded in `evals/parsing/manifest.json`.

Model identifiers, dataset hashes, retrieval settings, and runtime metrics are
captured in `evals/experiment-manifest.json` and each generated evaluation
report.
