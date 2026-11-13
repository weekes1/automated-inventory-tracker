# Repository instructions

## User prompt audit log

Maintain `notes/Prompts.md` as the canonical user development prompt log (capitalization is intentional). Append every new user project prompt, including corrections and follow-up requests, before substantive project work. Do not log tool output, system/developer instructions, or automatically injected environment context as user prompts.

Preserve visible prompt text verbatim, including spelling and formatting, in a fenced text block with a unique sequential ID. Use a longer fence if the prompt contains a conflicting fence. Append amendments rather than rewriting earlier entries.

Record an ISO 8601 UTC timestamp and its provenance: use actual submitted time only when exposed; otherwise use current observed/logged time and state that submission time was unavailable. Never invent an exact submission time. Record unavailable attachments/prior context rather than claiming to capture them.

Redact credentials or secrets with an explicit redaction note rather than committing them. Keep ordinary project prompt content intact.

This manual log aids review but does not guarantee automatic capture outside this repository or tamper resistance. Runtime extraction templates currently live in `prompts/`; versions/hashes belong in extraction run records.

## Design and status

Keep all code as simple as possible while fulfilling the requested task. Avoid speculative abstractions or business rules.

Use `schemas.InventoryRow` as the single definition of the eight output fields, in order: Quantity, Price, Description, Person name, Job site, Job name, Job #, Date. Different input layouts must map to that contract. `schemas.ProcessingRow` inherits these fields and adds internal acceptance/provenance metadata; never add that metadata to business exports. Use `OUTPUT_COLUMNS` and output projections rather than redefining field lists. Acceptance categories are `high`, `med`, `low`; assignment rules remain pending.

Keep literal LLM observations in `SourceField`, `SourceRow`, and `SourcePage`. Preserve uncertain and cancelled rows. Inheritance hints in source fields are unverified; only the deterministic resolver may confirm inheritance in `ProcessingRow.inherited_fields`. Validate references against the source data when resolution is implemented. Notes record stated evidence and uncertainty, not access to private model reasoning. Record actual human changes separately from LLM observations when review is implemented.

Record row highlighted/crossed_out observations independently of cancellation, with colour/extent in row notes. Null means unclear/unassessed, not absent. A blank-as-ditto hypothesis belongs in SourceField.inference as blank_as_ditto; keep kind=blank, raw_text empty, uncertain=true, and a non-empty evidence note. Do not invent a literal repetition mark or populate the prior value. These are machine-readable future review signals, not acceptance rules. Current defaults are extraction_v003.txt and source-page-wire-v002; preserve prior prompt versions and historical run artifacts.

Keep architectural decisions in `notes/DESIGN.md` and verified setup/deployment commands in `README.md`. Distinguish planned components from runnable implementation. The user explicitly wants everything under `data/` committed to GitHub, including uploaded inputs, run artifacts, previews, and future databases. Do not ignore or exclude these artifacts. Keep credentials and `.env` out of Git and out of run snapshots. `outputs/` remains ignored.

Use `RunConfig`/`ExtractionRun` and `runs.start_run`/`finish_run` for extraction attempts. Save actual prompt/input/schema/rules snapshots before provider calls, use those snapshots for the request, and record returned model ID, request ID, usage, and failures when available. One run is one page extraction attempt; retries get new run IDs. Never snapshot secrets or dump environment variables into configuration.

Run directories use `YYYY-MM-DD_HH-MM-SS.ffffffZ_<run_id>` based on manifest started_at in UTC, so name sorting is chronological. Use returned run directory paths; do not assume a directory is named only by UUID. Keep UUIDs and source row references unchanged when renaming folders.

The extractor owns calling finish_run once; callers must not save a duplicate raw/page output. `ExtractionResult` returns the SourcePage plus its run directory. Keep SDK automatic retries disabled unless explicit attempt tracking is introduced. Derive the strict wire schema from shared entities and preserve the distinction between null absent slots and SourceField objects representing visible blanks/illegible writing.

Successful run finalization also writes `preview_unreviewed.csv` through the same persistence layer. This raw preview includes all candidate rows with the eight output headers; it is not an approved business export. Preserve ditto marks and do not propagate headers/inheritance into raw previews. Cancellation/uncertainty metadata remains in page.json. `runs.add_preview` backfills older successful runs without re-extraction or overwriting raw/page data.

Use ingestion.ingest_bytes/ingest_file as the upload boundary and pipeline.extract_file for complete documents. Validate/render all pages before any model call. Keep limits centralized in InputLimits; don't trust filenames, write outputs under upload-supplied paths, or disable decompression checks. Preserve originals once under data/documents/<hash>, produce versioned PNG pages, and record original references/render settings in each run. PDF annotations must remain visible; marking observations depend on them. PDF page numbering is original one-based order. Report a later extraction failure as a partial/incomplete document, keeping prior page results. Keep input validation described accurately: it is not a malware scanner or process sandbox.
