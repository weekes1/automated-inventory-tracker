# Inventory sheet extraction design

Status: initial architecture, 2026-11-13. Canonical entities, run tracking, bounded ingestion, PDF rendering, and extraction implemented. Review, typed normalization, and approved export remain scaffolds; transcription quality still needs evaluation.

## Goal and assumptions

Convert inventory removal/sign-out sheets into CSV and XLSX, one row per line item. A reviewer can flag files or rows, correct values, and approve the exact revision exported.

Start with a single operator, low volume, local persistence, and mandatory review of every row. Input pictures/PDFs may have different layouts; all map to the fixed canonical fields below. Quantity/unit rules, date conventions, and item catalogue remain to be established from samples. Inventory balance updates and signature authentication are outside the initial scope.

## Canonical entities (implemented)

`schemas.py` defines the fields once in `InventoryRow`. `ProcessingRow` inherits them and adds internal `acceptance_level`, `source_row_id`, and `inherited_fields`. All layout adapters and review services must use these shared entities.

Business output headers, strictly in order: **Quantity · Price · Description · Person name · Job site · Job name · Job # · Date**. `OUTPUT_COLUMNS` derives from the base model. `to_output_dict()` projects exactly those fields, even on a processing row. `ProcessingRow.to_output_row()` produces a base entity. Internal `model_dump()` retains acceptance level for storage and must not be used directly as the business export.

Quantity and Price use finite `Decimal` values without assuming currency, rounding, unit-price versus line-total meaning, positivity, or integer-only quantities. Date is a calendar date; normalize source date conventions before validation. Job # and other text fields remain strings to preserve leading zeros. Python field names and exact output aliases are accepted. Unknown fields are forbidden and entities are immutable.

All eight values are nullable during processing so missing/illegible observations need not be guessed. Nullability is not export permission: later validation and approval policies will decide which missing values block export. Raw source entities are separate; persisted review events remain to be implemented.

Acceptance uses `high`, `med`, `low`, reflecting the current user-edited enum. Assignment rules remain pending; there is no automatic assignment. `None` means unassigned, not a fourth category. Acceptance is separate from human approval and never appears in business output.

## Source evidence entities (implemented)

- `SourceField`: literal `raw_text`, `kind` (`text`, `blank`, `ditto`, `illegible`), `uncertain`, an optional suggested `inherited_from` reference, and short evidence notes. Do not replace ditto marks with expanded text in this record.
- `SourceRow`: application-assigned `row_id`, one-based `row_number`, a dictionary of observed fields, `cancellation` (`active`, `cancelled`, `uncertain`), row uncertainty, and general notes. Retain cancelled rows for review rather than dropping them.
- `SourcePage`: document ID, one-based page number, header fields, ordered rows, layout notes, and general notes. Row IDs and row numbers must be unique within a page. An empty row list does not certify a blank or fully extracted page.
- `SourceReference`: document/page/row/field pointer. A null row number refers to a page header. Field keys and reference names must use existing Python field names from `InventoryRow`, such as `job_number`; validation reuses that model instead of repeating the eight field definitions.

Source field inheritance is an LLM suggestion, not a verified copy instruction. The future resolver must validate target existence, document/section boundaries, earlier-row order, and cycles before copying values. It records verified inheritance in `ProcessingRow.inherited_fields` and links the normalized row with `source_row_id`. Schema validation alone does not establish reference correctness. The implemented text inheritance stage is described below; typed normalization and cancellation exclusion remain unimplemented.

Keep stated evidence/uncertainty notes, raw responses, and the original page for audit. Notes describe model claims; they are not a record of private internal reasoning or proof that a transcription is correct. Extraction-run metadata is implemented below; persisted human review events remain planned. Preserve source observations when later human edits occur.

Keep implementation simple: use these nested Pydantic models and existing business fields rather than introducing a generic provenance framework. The source entities do not implement rendering coordinates, approval, or provider calls. Source pages can be saved as artifacts through run tracking.

## Run tracking (implemented)

Successful runs also save a hashed `preview_unreviewed.csv`, derived by `exporter.raw_preview_csv` from literal SourceRow observations. It uses exactly the eight output headers, retains all cancelled/uncertain candidates, and performs no inheritance or header propagation. Missing/illegible values render empty; details remain in page.json. Standard CSV quoting preserves commas/newlines, UTF-8 BOM supports common spreadsheet imports, and formula-like text is apostrophe-prefixed without changing source JSON. This inspection artifact is separate from the future approved export. `runs.add_preview` can append it to older successful manifests without rerunning the model or changing raw/page artifacts; an existing preview is reused rather than rewritten.

`RunConfig` records the provider/requested model, prompt/rules/schema versions, explicitly sent model settings, preprocessing configuration, and optional code/build version. `ExtractionRun` records a UUID, document/page identity, timezone-aware timestamps, outcome, returned model ID, request ID, usage, and errors. `RunArtifact` records each saved relative path, original filename where relevant, and SHA-256 hash. No run metadata belongs in business exports or LLM-generated source content.

`runs.start_run()` saves prompt, rules, actual provider response schema, and input snapshots under `data/runs/<UTC timestamp>_<run_id>/`, then atomically writes a running manifest. Pass the original and rendered input images as needed to capture both provenance and the exact pixels used. Use saved artifacts for the request; capture the full effective prompt, including additional instructions/examples. Rules version must match the rules JSON. Filenames/version labels alone do not establish configuration identity; hashes distinguish edits under the same version label.

`runs.finish_run()` records success with a validated matching SourcePage and full raw JSON response, or failure with an error and any available response. It saves result hashes and updates the manifest atomically. Finalized runs cannot be finalized again through this API; retry with a new run ID. An interrupted attempt remains running until explicitly failed. One run currently represents one page extraction attempt; batching/parent run relationships are not implemented.

`runs.load_run()` validates the manifest. Artifact hashes support later comparison; loading does not rehash all artifacts, and local files are not tamper-proof. Preserving inputs/configuration supports replay/comparison, not guaranteed identical future LLM output. Provider defaults, alias changes, or unavailable returned metadata remain limitations; record explicit settings and returned model snapshots when available. This file-based layer is implemented independently of provider calls and SQLite, and assumes a single local writer per run.

## Architecture

### Implemented extraction adapter

`extractor.extract_image(bytes, ...)` calls OpenAI's Responses API with high-detail image input and strict JSON Schema output. It returns `ExtractionResult(page, run_dir)`; `page` is the existing SourcePage entity, not a second PageExtraction model. PNG/JPEG/WEBP/non-animated GIF are supported; PDFs are prepared by ingestion.py and passed page-by-page through pipeline.extract_file. The default model is `gpt-5.4-mini`, configurable by argument or VISION_MODEL/EXTRACTION_MODEL. Environment loading and client creation happen on invocation, not import.

`extraction_response_schema()` derives a wire schema from SourcePage/SourceRow/SourceField and InventoryRow's canonical keys. Application-owned IDs are omitted. Open field dictionaries become fixed-key objects whose slots are nullable for absent fields; observed blanks and illegible text remain SourceField objects. Defaults are removed, all properties are required, and extra keys are forbidden for the strict API interface. Inheritance references are null in this initial extraction phase. After the response, null field slots are removed and run-scoped row IDs/document/page identities are attached before SourcePage validation. The provider schema version is `source-page-wire-v002` and its exact contents are saved per run.

The default extraction_v003 prompt receives a short appended transport contract to reconcile nullable slots and current property names. The complete effective prompt is snapshotted before the request. The model call reads saved prompt/image/schema artifacts, and finish_run is invoked exactly once outside the call/parse error handler. Only runs.py writes result artifacts: full raw JSON response plus page.json on success, or a failed manifest with available raw output on refusal, truncation, or validation failure. HTTP errors retain sanitized status/request metadata. No duplicate outputs/raw copy is created.

SDK retries are disabled; another invocation creates another explicit run, rather than silently retrying or caching. A 120-second SDK timeout and store=false are recorded. The local client is closed when owned by the extractor. Provider request/model/usage metadata is captured when available. Tests use the actual SDK with a mock HTTP transport; no live model accuracy or account access has been verified.

Use a modular Python application, initially one deployable process. A thin review UI calls application services; those services own persistence and state transitions. Microservices and an agent framework add little value to the initial sequential workflow.

```mermaid
flowchart TD
    A[Upload PDF or image] --> B[Validate, hash, persist original]
    B --> C[Render and orient pages]
    C --> D[Vision extraction: raw observations]
    D --> E[Resolve repetitions and normalize]
    E --> F[Validate fields and page completeness]
    F --> G[Review source beside editable rows]
    G --> H[Approve current revisions]
    H --> I[Create approved export snapshot]
    I --> J[CSV and XLSX]
    G -->|Edit or flag| F
```

Persist intermediate stages so reloads, timeouts, and retries do not erase work. LLM calls occur only in extraction; deterministic stages and manual edits can rerun against stored responses.

## Project layout

The structure below includes implemented schemas, ingestion, run tracking, extraction orchestration, and raw previews. Review, risk/acceptance policy, typed normalization, and approved exports remain scaffolds.

```text
app.py                  # review UI; no extraction or approval business rules
pipeline.py             # stage orchestration, run identity, retries
runs.py                 # implemented local run manifests and artifact snapshots
ingestion.py            # validation, hashing, PDF rendering, orientation
extractor.py            # provider adapter, structured response parsing
schemas.py              # typed observations, revisions, flags
resolver.py             # downward text inheritance and source-cell dependencies
validator.py            # versioned checks and risk reasons
review.py               # edits, flags, approvals, exclusions
storage.py              # transactions, revisions, audit events, artifacts
exporter.py             # approved snapshot to CSV/XLSX
prompts/
  extraction_v001.md    # versioned prompt sent to the vision model
config/
  rules_v001.json       # versioned field and repetition policies
samples/                # synthetic/anonymized examples only
tests/
  fixtures/             # labeled truth and recorded provider responses
data/                   # version-controlled inputs, run artifacts, previews, SQLite
outputs/                # ignored export snapshots and manifests
.env                    # local secrets; ignored
.env.example            # committed names/placeholders, no secrets
requirements.txt        # pin tested dependencies when implementation starts
README.md               # verified setup/run/deployment commands
notes/
  Prompts.md            # user development prompt audit log
  DESIGN.md             # decisions and rationale
  AGENTS.md             # collaboration and logging rules
```

A simple Python review UI and SQLite are suitable MVP choices. UI session state is a convenience, never the source of truth. Move to an API, durable worker queue, shared object storage, and PostgreSQL when concurrent jobs, reviewers, or hosting requirements justify them. Retain the service boundaries during that transition.

## Ingestion and evidence

Validate decoded file type, size, page count, and image dimensions rather than trusting filenames. Start with PDF, PNG, and JPEG. Fail explicitly for corrupt/encrypted PDFs and record failures per file/page. Never label a partially processed batch complete.

Store unchanged originals under generated document IDs and content hashes. Detect duplicate uploads by hash; distinguish an accidental duplicate from an intentional new extraction run. Never silently merge different sheets.

Render PDFs into page images at a recorded resolution. Preserve original renders and record rotation, deskew, scaling, and coordinate transforms. Embedded PDF text or OCR can supplement extraction; the visible sheet remains review evidence.

Start with page-level extraction to retain headers and row context. For dense pages, evaluate overlapping table crops with a page overview and deterministic overlap reconciliation. Retain the preceding row needed for a ditto mark. Validate model-generated row/cell coordinates before use; they are approximate pointers, not ground truth.

## Raw extraction contract

Request schema-constrained JSON and parse into typed objects. Preserve literal observations before resolving them. Do not ask the model to silently repair quantities, expand ditto marks, select catalogue items, or guess illegible text.

| Entity | Essential data |
| --- | --- |
| Document | ID, filename, content hash, ingest time, page inventory |
| Page | document ID, page number, render hash, dimensions, transforms, status |
| Extraction run | run ID, model/snapshot, prompt hash, schema/rule versions, parameters, request ID, times, usage, outcome |
| Observed row | assigned ID, run/page/table/order, source region, row classification |
| Observed cell | literal text, kind (`text`, `blank`, `ditto`, `illegible`), optional region, uncertainty reason |
| Resolved revision | row/revision ID, typed values, transformation reasons, source dependencies |
| Flag | target document/page/row/cell, reason code, severity, status, actor |
| Review event | actor, UTC time, action, target revision, before/after values, reason |
| Export | snapshot ID, approved revision IDs, scope, schema version, output hashes |

Assign stable IDs in application code. Store dates/quantities as raw text plus separately parsed values; use decimal quantities and explicit units. Keep identifiers such as `00123` as strings. Blank, illegible, and ditto remain distinct even when the typed value is null.

Record headers, section boundaries, crossed-out rows, and uncertain row candidates. Do not silently discard uncertain rows. Treat provider refusal, truncation, invalid JSON/schema, and timeout as failures or blocking review states, never as an empty successful table.

Structured output constrains shape, not transcription correctness. See the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Resolution and risk

Resolution creates a derived revision; validation returns explicit reason codes and severities. Low risk is not proof of correctness. Do not treat model self-reported confidence as a calibrated probability.

The current user-selected policy (2026-11-14) fills all eight columns independently from preceding usable values for blank/missing cells and repetition markers, and fills invalid date strings from the last valid date. Header fields can seed a column. Raw blanks remain distinct from literal ditto marks in SourcePage even though both trigger resolution. State resets per page; inferred section/job boundaries and cancellation exclusions are not applied in this initial policy. Every copied value has a recorded source reference and reason. This replaces the earlier proposed conservative per-column policy.

When a predecessor changes, recompute dependent cells and invalidate affected approvals. A human override explicitly breaks or replaces its dependency; recomputation must preserve that override and flag a new conflict.

Checks should cover required fields, ambiguous dates, quantity/unit validity, unresolved repetition, unknown item IDs, conflicting catalogue suggestions, possible duplicates, and merged columns. Catalogue matches are suggestions unless a rule is demonstrably unambiguous; retain the handwriting transcription.

Start with `blocked`, `needs_review`, and `informational` flags rather than a numeric score. Row priority is the highest relevant field/page/document severity. Fixes resolve flags; explicitly permitted ambiguity can be acknowledged with a recorded reason. Required export values and structural failures remain blocking.

Plausible rows can still be missing. Account for every uploaded page and reconcile visible candidate rows. Row detection/count estimates are warning signals, not proof of completeness. Require a reviewer page-completeness sign-off against the full source page. Add an independent row detector/OCR pass only if evaluation shows it reduces omissions.

## Human review

Show the source page and highlighted row beside raw and resolved values. Support zoom, cell edits, whole-file/row flags, adding missed rows, splitting/merging row detections, and explicit exclusion of non-data/duplicate rows with reasons. Structural changes require source references and review events.

Persist row states such as `needs_review`, `approved`, and `excluded`; keep flags separate. A document is export-ready only when all pages are accounted for, completeness is signed off, all candidate rows have a disposition, and no unresolved blocking document/page flags remain.

Approve a specific revision with source/pipeline versions. Edits, new extraction runs, changed dependencies, and changed validation policies make affected approvals stale and require revalidation. Row structure edits invalidate page completeness sign-off. Every included row initially requires human approval, even with no flags.

Use transactional writes with an expected revision number so a stale UI cannot overwrite newer edits. A local MVP can record a configured operator identity, explicitly documented as self-asserted. Shared deployment needs authenticated identities and authorization checks in the service layer.

## Export and auditability

Enforce approval in the export service, not just the UI. Create CSV and XLSX from the same immutable approved snapshot in a transaction. Default complete-file export blocks on pending rows, pages, or flags. A batch may export fully approved files; its manifest identifies pending files. Never silently export part of a document.

Use stable configurable column order, UTF-8 CSV, and standard quoting. Write XLSX identifiers/free text as literal strings and preserve leading zeros. Define and test spreadsheet formula-injection handling in both formats, including `=`, `+`, `-`, `@` and leading control characters; CSV quoting alone does not prevent execution. Preserve original values in the audit store and document export escaping.

A separate manifest records source/run IDs, row revisions, exclusions, reviewers/times, export schema, and file hashes. Keep business tables clean. Preserve raw responses, derivations, and review events so each exported cell is traceable.

SQLite history and Git-reviewed Markdown are useful MVP records, but editable by someone with filesystem access. They are not tamper-proof. Stronger assurance needs restricted append-only storage and externally anchored hashes/backups. Per the user's explicit project policy, everything under data/ is version-controlled for GitHub review, including source sheets, responses, previews, and future databases. Credentials remain outside data/ and Git. outputs/ remains ignored.

## Model evaluation

Initial candidates, capabilities checked against official documentation on 2026-11-13:

- [GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5): candidate quality baseline; supports image input and structured outputs.
- [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini): candidate lower-cost baseline; supports image input and structured outputs.

These are candidates to benchmark, not claims of handwriting accuracy or an exhaustive ranking. Pin an available snapshot after evaluation and record the actual returned model ID. Keep provider/model configuration outside deterministic rules.

Use page images through a vision-capable API with a versioned prompt. Consult the [vision guide](https://developers.openai.com/api/docs/guides/images-vision) for supported inputs and limits; small/rotated text and spatial localization need particular care. A crop retry or second model may help difficult rows; model agreement is not approval.

Create an initial labeled set of roughly 20–50 representative pages: clear print, messy handwriting, ditto chains, page breaks, crossed-out rows, duplicate scans, blur, rotation, missing fields, and blank pages. This is a starting dataset, not sufficient evidence of production reliability. Split tuning and held-out evaluation by document, not rows from the same sheet.

Measure row recall/precision, critical-field exact match (especially quantity/item ID), ditto accuracy, unflagged errors, review time, latency, and cost per approved row. Report transcription quality before edits separately from final output quality. Compare render/crop strategies on the same labels. Choose models and escalation policies from results rather than generic benchmarks.

## Implementation sequence and checks

1. Use the canonical entities above; establish layout mappings and repetition/date/unit policies from samples, and finalize acceptance categories/rules. Create labeled synthetic/anonymized fixtures and a versioned extraction prompt.
2. Implement schemas, ingestion, stored raw extraction, and replayable deterministic stages. Bound retry/backoff for transient errors; fail permanent errors explicitly. Key artifacts by source/render/prompt/schema/model settings so retries cannot duplicate rows. Replay stored responses for reproducibility; LLM reruns are not guaranteed identical.
3. Implement persisted review, dependency invalidation, flags, and completeness sign-off, then export snapshots.
4. Test invariants: unresolved ditto never guesses; upstream edits invalidate dependent approval; stale writes fail; failed/missed pages block export; unapproved rows cannot export; CSV/XLSX represent the same approved revisions and preserve text safely. Use recorded responses for routine tests and opt-in live model evaluations.
5. Benchmark held-out sheets, document verified local commands in README.md, then select hosting based on volume, authentication, retention, and reviewer concurrency.

## Decision record

| Date | Proposed decision | Reason |
| --- | --- | --- |
| 2026-11-13 | Modular monolith with persistent local state | Simple iteration with clean service boundaries |
| 2026-11-13 | Separate raw, derived, and reviewed values | Correction, replay, and traceability |
| 2026-11-13 | Ditto dependencies and page completeness review | Error propagation and silent omissions |
| 2026-11-13 | Revision-specific mandatory human approval | Risk rules cannot certify correctness |
| 2026-11-13 | Separate development log and runtime prompts | Different audit subjects and versioning |
| 2026-11-13 | Shared Pydantic business row plus inherited processing row | Variable input layouts map to eight fixed output fields; acceptance stays internal |
| 2026-11-13 | Simple page/row/field source models plus explicit inheritance references | Preserve cancellations, uncertainty, and evidence separately from resolved values |
| 2026-11-13 | File-based run manifests with versioned, hashed snapshots | Compare extraction attempts before introducing a database |
| 2026-11-13 | Single-image Responses API adapter with one persistence owner | Preserve raw failures and avoid duplicate result writes |
| 2026-11-13 | Include all data/ artifacts in GitHub version control | User preference for reviewing this small project's inputs and extraction results together |

Run folder naming uses `YYYY-MM-DD_HH-MM-SS.ffffffZ_<run_id>` with the manifest start time in UTC. Name sorting is chronological, including microseconds. Existing UUID-only folders were renamed from their recorded start times; run IDs, row references, manifests, and artifact bytes were preserved.


## Visual observations and blank continuation (implemented)

SourceRow.highlighted and crossed_out record visible markings independently of cancellation. True means observed, false means clearly absent, and null means unclear/unassessed (including older records). Notes describe colour, extent, and affected cells. Highlight colour alone must not establish job identity or cancellation; a crossed-out correction can coexist with an active row.

SourceField.inference optionally records blank_as_ditto. This hypothesis requires kind=blank, raw_text="", uncertain=true, and a non-empty evidence note. The literal cell stays blank; no quote, arrow, or copied text is invented. A visible repetition mark instead remains kind=ditto with its literal text. References remain null in the initial API extraction; later deterministic rules/review may resolve inheritance. Inference and visual marks provide structured review inputs without assigning acceptance or approval. CSV previews still contain only the eight literal business columns; review metadata remains in page.json.

The current default prompt is prompts/extraction_v003.txt, paired with source-page-wire-v002. Both are snapshotted in new runs. Previous prompts and historical run responses/pages are preserved rather than relabeled after the fact. A fresh extraction is required to assess highlighting, strike-throughs, and continuation hypotheses on an older image.


## Bounded ingestion and PDF support (implemented)

The CLI now accepts PDFs and images through pipeline.extract_file. ingestion.ingest_bytes provides a future backend upload boundary; ingest_file bounds local reads and rejects non-files and file symlinks. Check nonempty bytes, filename/path-control characters, extension-versus-content, full image decoding, dimensions, animation, PDF encryption/repair, object/page counts, and detected active features. Reject attachments and scripting/launch/additional-action dictionaries. Only generated content-hash/page paths are used for stored artifacts.

InputLimits defaults are 20 MiB input, 20 PDF pages, 10,000 pixels per side, 20 MP per page, 100 MP aggregate, 100 MiB prepared PNGs, and 20,000 PDF objects. Byte limits apply before decoding. PDF dimensions/aggregate pixels are checked before get_pixmap; rendered PNG size is also bounded. This is a local validation policy, not an antivirus guarantee or native-parser sandbox; isolated CPU/time/memory-bounded workers remain a requirement for untrusted public hosting.

Images are re-encoded after EXIF orientation onto white RGB PNGs, dropping original metadata/trailing data from the model input. PDFs render at 200 DPI by default (72–300 configurable), in RGB with annotations enabled and transparency disabled, respecting page rotation. The entire document must finish preparation before any API call. --prepare-only saves PNGs without credentials/model requests.

Preserve original bytes once under data/documents/<source_sha256>/original.<type>. Versioned renderer/profile folders contain numbered PNGs and an ingestion.json with page count, file hashes, dimensions, and renderer settings/version. Existing identical artifacts are reused; differing contents at an immutable path fail rather than overwrite. Whole originals are not copied into every page run. Each run snapshots its own PNG and references the original/prepared paths relative to data/, with original hash, page count, DPI/rotation/transform information, and validation limits. All data/ remains Git-tracked under the user's policy.

All PDF pages share the original source hash as document ID by default. Source page numbers retain PDF order. Extraction is sequential and stops on the first API failure, raising DocumentExtractionError with the failed page/total count and prior completed results. Saved earlier runs remain valid page results but never imply document-level completeness. There is no database, automatic retry, or approved document export added here.


## Downward inheritance resolver (implemented, 2026-11-14)

resolve_page reads SourcePage rather than the lossy preview CSV. It carries each canonical column independently until a new non-empty, non-marker value appears. Date is special: only real calendar dates matching the configured formats update its source; invalid date text triggers inheritance. A usable page header seeds that field with a null source row number. All eight columns participate, including quantities/prices/descriptions. All candidates remain in order and can supply values, including cancelled/uncertain rows; human review and cancellation exclusion are still separate future policies. There is no cross-page inheritance or automatic inferred section reset.

ResolvedRow holds text values, source row identity, inherited_fields referencing original observed cells, inheritance_reasons, and unresolved_fields. ResolvedPage records page identity and resolver version. It does not use the typed InventoryRow prematurely: quantities such as "1 box" and source date spellings must survive this intermediary step. Empty/invalid cells without a preceding usable source remain unresolved, blank in CSV, and flagged inherited=false. Ambiguous numeric dates may match either day/month or month/day; they remain literal text without locale normalization.

config/resolver_v001.json specifies whole-cell repetition symbols/words and accepted date formats. New successful extractions invoke runs.add_resolution after saving extraction output. Saved successful runs can be processed separately with resolver.py. Each run gets resolved_inherited.csv (16 interleaved value/flag columns), resolved_inherited.json (source references/reasons/unresolved fields), and resolver_rules.json (exact rule snapshot). ResolutionArtifacts in the run manifest records timestamp, source page hash, and hashes of the derived files. Extraction data and the eight-column raw preview are unchanged. Intermediate flags are not added to the eventual approved eight-column business export.

Repeated resolution verifies and reuses existing artifacts. Changed rules or edited artifacts fail rather than overwrite an audit record. A future revision-management feature is needed to store multiple resolutions of one source under changing policies. This stage assigns no acceptance levels, does not approve records, and does not implement human overrides or approval invalidation yet.
