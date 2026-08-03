# Document parser bake-off

## Decision

Keep the lightweight `pypdf` path for ordinary text PDFs. Route scanned PDFs,
layout-heavy PDFs, DOCX, and HTML through Docling in the asynchronous ingestion
worker. Do not force full-page OCR by default: Docling's normal PDF pipeline
recovered the scanned fixture perfectly and was faster than the forced
RapidOCR profile.

Do not adopt Unstructured-fast as the structured quality path. It is useful as
a low-latency text extraction candidate for DOCX and HTML, but flattened every
table in the two structured fixtures. Its `ocr_only` profile also requires a
separate Tesseract installation and failed explicitly in the tested
environment, while Docling's local RapidOCR path worked.

## Test design

The benchmark contains seven source/reference pairs pinned from Docling:

- four PDF cases covering code/formulas, long text, multilingual tables, and a
  difficult layout table from commit
  `91fa745b3228fa0df0510d76eb94956b063054e1`;
- a scanned PDF, a DOCX with merged table cells, and HTML with rich table cells
  from commit `52d8a6f24de7318a9ad4be2a7361ba93fc81a5c1`.

Every run records content-token overlap, anchor recovery, headings, Markdown
table rows, code fences, pages, output hashes, per-file failures, and
processing time. Empty parser output is a failure, not a successful parse.

The references are Docling-generated Markdown and therefore favor Docling's
representation. Token F1 is diagnostic, not a neutral winner score. The
decision uses anchor recovery, structure preservation, explicit failures,
output inspection, and latency together.

## Aggregate result

| Profile | Successful / attempted | Mean token F1 | Mean anchor recall | Median processing | Relevant result |
| --- | ---: | ---: | ---: | ---: | --- |
| pypdf 6.14.2 | 4 / 7 | 0.9460 | 0.8750 | 96 ms | fast text PDFs; no OCR, DOCX, HTML, tables, or code structure |
| Docling 2.117.0 | **7 / 7** | **0.9972** | **1.0000** | 6,915 ms | complete format and structure coverage |
| Docling + forced RapidOCR | 1 / 1 | 1.0000 | 1.0000 | 10,509 ms | correct scanned PDF, but slower than normal Docling |
| Unstructured-fast 0.24.1 | 6 / 7 | 0.9206 | 1.0000 | 440 ms | fast structured text, but zero Markdown table rows |
| Unstructured OCR-only 0.24.1 | 0 / 1 | 0.0000 | 0.0000 | — | failed because Tesseract was not installed |

Docling's aggregate median is dominated by the PDF pipeline. Its declarative
DOCX and HTML conversions took 158 ms and 113 ms respectively in this run.

## New format cases

| Fixture | pypdf/current | Docling default | Forced RapidOCR | Unstructured-fast |
| --- | --- | --- | --- | --- |
| Scanned PDF | no readable text | 100% anchors/F1 in 6,915 ms | 100% anchors/F1 in 10,509 ms | empty output |
| Rich-table DOCX | unsupported | 100% anchors/F1; 34 table rows in 158 ms | not applicable | 100% anchors, 0.8993 F1; 0 table rows in 141 ms |
| Rich-table HTML | unsupported | 100% anchors/F1; 22 table rows in 113 ms | not applicable | 100% anchors, 0.8485 F1; 0 table rows in 14 ms |

The routing decision is therefore not "Docling for everything." Plain text
PDFs retain the 96 ms lightweight median. Docling earns the quality path only
for document classes where the lightweight parser fails or loses material
structure.

## Adoption gate

The Phase B parser registry should:

1. detect supported format and whether a PDF has extractable text;
2. keep `pypdf` on the synchronous fast path for ordinary PDFs;
3. queue Docling work for scanned, layout-heavy, DOCX, and HTML documents;
4. preserve page/source provenance and table Markdown through chunking;
5. expose progress and a retryable failure instead of silently accepting empty
   output;
6. fall back only when the fallback preserves the information required by the
   client schema or retrieval tests.

## Reproduce

```bash
pip install -e ".[parsing-benchmark]"
python -m app.parsing_benchmark \
  --providers pypdf docling docling-rapidocr-full-page \
    unstructured-fast unstructured-ocr-only \
  --output docs/parsing-benchmark-v2.json \
  --artifacts-dir docs/parsing-artifacts-v2
```

The machine-readable run is
[`parsing-benchmark-v2.json`](parsing-benchmark-v2.json), and every successful
output is in [`parsing-artifacts-v2`](parsing-artifacts-v2). Runtime is
hardware-dependent and should be compared only within the same run.

Primary implementation references:

- [Docling document converter](https://docling-project.github.io/docling/reference/document_converter/)
- [Docling OCR installation and engines](https://docling-project.github.io/docling/getting_started/installation/)
- [Unstructured partitioning and PDF strategies](https://docs.unstructured.io/open-source/core-functionality/partitioning)
