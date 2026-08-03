# Atlas shell specification (UI1 closure and UI2 contract)

This closes the UI1 items left open for Atlas — responsive collapse rules,
product-local tokens, component inventory and reuse map, and the seeded-data
specification — and is the contract the UI2 foundation implements.

The direction itself is not reopened here. It comes from
`PORTFOLIO_UI_DESIGN_RESEARCH_2026-07-30.md`: a quiet editorial research tool,
not a dashboard.

## Non-negotiables

Publish-blocking rules carried from the design research:

- no permanent left navigation in the primary research view;
- no KPI card row and no generic four-up stat grid anywhere;
- no control that does not execute real behaviour;
- body text readable at normal browser scale;
- serif only for long-form answer hierarchy, never for controls;
- Lucide SVG icons, never text glyphs or emoji.

## Regions

| Region | Role | Backing API |
| --- | --- | --- |
| Global header | workspace, retrieval scope, index health, provider mode | `GET /api/health`, `GET /api/health/ready` |
| Query rail | prepared cases, profile select, collection filter, top-k | `GET /api/documents` for collections |
| Answer canvas | dominant surface: question, streamed answer, citation markers, abstention | `POST /api/query` |
| Evidence pane | passage, source URI, version, checksum, page, score, security flags | `POST /api/query` sources |
| Trace rail | profile, fusion, candidates, rerank, stage latency, generation cost | `retrieval` + `generation` traces |
| Library route | documents, versions, archived state, delete, re-index | `/api/documents*` |
| Sources route | connector catalogue, folder/URL sync, job progress and sync report | `/api/connectors*`, `/api/ingestion-jobs*` |
| Comparison route | profile comparison as a table | `POST /api/evaluations/compare` |

The Sources route is new work: connector synchronization shipped in Phase B
with no interface at all.

## Responsive collapse

### 1440 px — primary

Three columns inside a fixed header:

```
┌────────────────────────────────────────────────────────────────┐
│ header: brand · scope · index health · provider · API ref      │
├───────────┬────────────────────────────────┬───────────────────┤
│ query     │ answer canvas                  │ evidence          │
│ rail      │ (dominant, fluid)              │ pane              │
│ 300px     │ min 560px                      │ 400px             │
└───────────┴────────────────────────────────┴───────────────────┘
```

- Query rail collapses to a 48 px icon strip once a question is submitted; it
  reopens on click and remembers the choice.
- Trace opens as a right-edge overlay drawer, never as a fourth column, so it
  cannot compete with the answer.

### 1024 px

- Query rail is not a column. It becomes a sheet opened from a header control,
  and the prepared cases move into the empty-state of the answer canvas.
- Answer canvas and evidence pane split 62/38 with a draggable divider.
- Trace drawer covers the evidence pane rather than the answer.

### 390 px

- Single column stack. Header condenses to brand mark, scope chip and a health
  dot; the provider label moves into the scope sheet.
- Composer anchors to the bottom of the viewport; the answer scrolls above it.
- Citation markers are tap targets (minimum 44 px) that open the evidence pane
  as a bottom sheet at 70 vh.
- Trace becomes its own route rather than a drawer.
- The comparison table scrolls horizontally inside its own container; the page
  body never scrolls horizontally.

## Tokens

Product-local CSS variables. No shared finished theme.

### Color — light

| Token | Value | Use |
| --- | --- | --- |
| `--atlas-canvas` | `#FAF8F5` | app background, warm light neutral |
| `--atlas-surface` | `#FFFFFF` | panels, answer canvas |
| `--atlas-surface-sunken` | `#F2EFEA` | rail, table headers |
| `--atlas-border-quiet` | `#E5E0D8` | dividers, default borders |
| `--atlas-border-strong` | `#CFC8BC` | focus-adjacent, active borders |
| `--atlas-ink` | `#1C1A17` | primary text |
| `--atlas-ink-muted` | `#6B655C` | secondary text, labels |
| `--atlas-ink-subtle` | `#948D82` | metadata, disabled |
| `--atlas-accent` | `#4C3FBF` | ink violet: primary action, citation marker |
| `--atlas-accent-hover` | `#3E33A3` | hover/active |
| `--atlas-accent-wash` | `#EEEBFB` | selected citation, active rail item |
| `--atlas-positive` | `#1F7A5C` | index healthy, job succeeded |
| `--atlas-warning` | `#A66A00` | degraded parser, retry pending |
| `--atlas-danger` | `#B03A2E` | failure, dead letter |
| `--atlas-flag` | `#8A5A00` on `#FBF3E2` | prompt-injection source flag |

Contrast: every text token on its intended background meets WCAG 2.2 AA
(4.5:1 body, 3:1 large). `--atlas-ink-subtle` is metadata only and never
carries the sole meaning of a state.

### Typography

| Token | Value |
| --- | --- |
| `--atlas-font-ui` | `Inter, system-ui, -apple-system, "Segoe UI", sans-serif` |
| `--atlas-font-answer` | `"Source Serif 4", Georgia, serif` |
| `--atlas-font-mono` | `ui-monospace, SFMono-Regular, Menlo, monospace` |

Scale, 1.2 ratio: `12 · 13 · 14 · 16 · 18 · 22 · 28`. Controls at 14, answer
body at 16 with 1.6 line height, headings 1.25. The serif appears only in the
answer canvas.

### Space, radius, elevation, motion

- space: `4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 56`
- radius: `4` control, `8` panel, `12` card, `999` pill — moderate, not pill-heavy
- elevation: `0` flat by default; `0 1px 2px rgb(28 26 23 / 6%)` for raised
  panels; `0 8px 24px rgb(28 26 23 / 10%)` reserved for drawers and popovers.
  Panels are separated by quiet dividers, not by shadow.
- motion: `120ms ease-out` for state changes, `200ms cubic-bezier(.2,.8,.2,1)`
  for panel and drawer transitions, and all of it disabled under
  `prefers-reduced-motion: reduce`.

## Component inventory and reuse map

### Adopted — Radix primitives via shadcn source

Button, Select, Dialog, Sheet, Tabs, Tooltip, Popover, Separator, ScrollArea,
ToggleGroup, Badge, Toast, Skeleton, Progress, Collapsible, Command.

Reused for behaviour and accessibility only. Their default visual styling is
replaced by the Atlas tokens.

### Adopted — specialist

`assistant-ui` for thread state, composer, message streaming, interruption and
retry. This is the defining interaction and the state that is easy to implement
badly.

### Atlas-owned

`AnswerCanvas`, `CitationMarker`, `EvidencePane`, `SourceCard`,
`RetrievalTraceRail`, `GenerationCostStrip`, `ProfileComparisonTable`,
`DocumentLibraryTable`, `DocumentVersionHistory`, `ConnectorCatalogue`,
`FolderSyncForm`, `UrlSyncForm`, `SyncReportTable`, `IngestionJobList`,
`IndexHealthChip`, `SecurityFlagBadge`, `ParserBadge`.

`GenerationCostStrip` renders the Phase B generation trace and must show an
explicit "not reported" rather than `0` when the provider omits token usage.
`ParserBadge` must surface the degraded fallback state.

## Required states

Every component ships these, and Storybook covers them:

loading · empty · error · disabled · success · repeated action · permission
denied · abstention (query returned no sources) · degraded parser · source
flagged for prompt injection · job failed · job dead-lettered · document
archived.

## Seeded data

The demo must be able to show every state above without a credential:

- the six fictional policy documents already seeded;
- three prepared questions: contract cancellation, security incident remedy,
  annual plan refund;
- one question that legitimately abstains;
- a connector root containing a Markdown, a CSV and an HTML file;
- one document at version 2 with version 1 superseded;
- one archived document from an upstream deletion;
- one restricted-visibility document the default principal cannot read;
- one dead-lettered ingestion job;
- one source containing embedded instructions so the flag is visible.

## Exit gate

Per the plan: every visible primary control works, the defining workflow passes
at 1440 px, 1024 px and 390 px, and the new shell beats the released static
frontend in a side-by-side review. Verified by Playwright workflows and
deterministic screenshots, Storybook state coverage, automated axe checks, and
manual keyboard, focus and zoom review.
