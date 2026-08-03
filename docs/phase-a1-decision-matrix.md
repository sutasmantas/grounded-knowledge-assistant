# Phase A1 decision matrix

## Deployment profile

The measured Atlas profile is deliberately mixed rather than "use the largest
model everywhere":

| Layer | Default or route | Measured reason |
| --- | --- | --- |
| Ordinary text PDF parsing | pypdf | 96 ms median on the tested PDFs; avoids the quality pipeline when text is already extractable |
| Scanned/layout PDF, DOCX, HTML | Docling in the ingestion worker | 7/7 fixtures, full anchor recall, scanned OCR, and preserved DOCX/HTML table structure |
| Chunking | Fixed overlapping windows | Only candidate with complete held-out source recall under both sparse and hybrid retrieval; 19 rather than 51 records |
| Local semantic embedding | BGE small | Stronger latency/resource profile; BGE-M3's aggregate gain is uneven and expensive on CPU |
| Hosted embedding | `text-embedding-3-large`, 1,024 dimensions, credential-gated | Current shortlisted hosted quality option; no result claimed without a paid run |
| Retrieval | Sparse for the bundled corpus | Frozen Phase A0 winner; hybrid remains selectable for corpora that measure differently |
| Learned reranking | None interactively | BGE's 0.0068 held-out nDCG gain cost roughly 60× held-out p95 latency |

## Candidate disposition

| Experiment | Candidate | Quality result | Operational result | Disposition |
| --- | --- | --- | --- | --- |
| Parser | pypdf | Correct on ordinary text PDFs; no OCR/Office/HTML route | Fastest relevant PDF path | Keep fast route |
| Parser | Docling default | Full anchors on all seven fixtures; preserves tested tables | Slower PDF path; fast DOCX/HTML conversion | Keep asynchronous quality route |
| Parser | forced RapidOCR | Correct scanned fixture | Slower than default Docling OCR | Do not force by default |
| Parser | Unstructured-fast | Text retained; tested tables flattened | Low-latency DOCX/HTML | Do not use as structured quality route |
| Chunking | heading-aware | Higher MRR, lower source recall | 2.68× records | Keep experimental |
| Chunking | parent-child | Same result as heading-aware here | 2.68× records | Keep seam, do not promote |
| Chunking | Docling hybrid | No recall/nDCG win | Roughly 17.5 s local index build | Keep experimental |
| Embedding | BGE-M3 dense | Better aggregate ranking; worse multi-document category | 2.29 GB local cache and slower CPU retrieval | Re-test for multilingual/long-context clients |
| Embedding | OpenAI large 1,024d | Not run without credential | Hosted cost and data boundary | Credentialed adapter only |
| Reranker | MiniLM | No aggregate gain | About 19× held-out p95 | Reject for this corpus |
| Reranker | BGE cross-encoder | Small nDCG gain, no held-out MRR/recall gain | About 60× held-out p95 | Offline/client-specific experiment |
| Reranker | ColBERT | Lower MRR and nDCG | About 1.6 s held-out p95 | Reject for this corpus |

## Category-level lessons

| Category | Observed result | Client adaptation rule |
| --- | --- | --- |
| Exact identifiers and policy terms | Sparse retrieval is already very strong; BGE-M3 also improves dense/hybrid ordering | Keep sparse in the candidate set; do not pay for a larger dense model solely for exact terms |
| Paraphrase | BGE-M3 improves dense and hybrid ranking | Re-run the embedding bake-off when semantic paraphrase is the client's dominant workload |
| Multi-document | Hierarchical chunkers lose a required source; BGE-M3 lowers category nDCG | Preserve source-level recall and test deduplication before optimizing aggregate MRR |
| Tables | Structure is primarily a parser problem in these fixtures | Route structured formats through Docling before changing retrieval models |
| Scanned documents | Lightweight extraction fails; Docling OCR succeeds | Detect empty/scanned PDFs and queue the quality parser |
| Unanswerable questions | No retrieval/model choice solves abstention in the held-out split | Treat abstention and semantic faithfulness as a separate Phase A2 gate |

## Transition rule

These winners apply only to the committed six-document corpus and frozen
questions. A client deployment should replace or extend the cases with its
documents, preserve the held-out split, and rerun the relevant layer before
changing the profile. A model's published benchmark position is a shortlist,
not an adoption result.
