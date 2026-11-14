# Automated inventory tracker

Planned tool for converting PDF and image inventory removal/sign-out sheets into reviewed CSV and XLSX files, with one row per line item and traceability back to the source sheet.

## Quick set up and summary

Create your own .env file. Use the key provided in the email--it will be deactivated once your review is done.

OPENAI_API_KEY= see email

History of prompts can be seen in notes/Prompts.md and my write up.

Structured outputs can be found in: data/approved_outputs and other run history can be found in data/runs

Approximate time working: 4-4.5 hours

follow the below commands to get the system running:

cd '/automated-inventory-tracker'

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

to run the front end: 

.venv/bin/python -m streamlit run app.py

to run the pipeline in terminal:

.venv/bin/python extractor.py 'samples/Inventory Sheet 3.png'

## Project status

Shared Pydantic entities, run tracking, input validation, PDF/image-to-PNG preparation, OpenAI extraction, downward inheritance resolution, and deterministic risk validation are implemented. The Streamlit review UI and explicitly approved CSV export are implemented. Typed-value normalization, acceptance rules, and XLSX export remain future work. There is no hosted deployment.

Input layouts may vary. Output is fixed to **Quantity · Price · Description · Person name · Job site · Job name · Job # · Date**. `InventoryRow` defines these fields once; `ProcessingRow` adds internal acceptance (`high`, `med`, `low`) and source/inheritance references. Assignment rules remain pending. Output projections exclude all internal metadata.

`SourcePage` contains header observations, source rows, layout notes, and general notes. Each `SourceRow` retains cancellation, visual marking, highlighting, strike-through observations, and uncertainty; its `SourceField` values preserve literal text, ditto/blank/illegible markers, notes, and unverified inheritance hints. Stated reasons support review; they do not expose the model's internal reasoning.

`marked`, `highlighted`, and `crossed_out` are true/false when assessed, or null when unclear/unassessed. They are separate from cancellation: a highlighted row can remain active, and a corrected cell does not necessarily cancel a whole row. Row notes describe colour, extent, and affected cells. A blank suspected of meaning continuation stays `kind="blank"`, `raw_text=""`, with `inference="blank_as_ditto"`, `uncertain=true`, and a required explanatory field note. This is a review candidate, not permission to copy values. A visible quote/arrow remains a literal ditto mark rather than a blank inference.

- [DESIGN.md](notes/DESIGN.md): architecture, module responsibilities, review rules, model evaluation, and implementation sequence.
- [Prompts.md](notes/Prompts.md): append-only user project prompt record, with timestamps and their provenance.
- [AGENTS.md](notes/AGENTS.md): instructions for maintaining that record in future repository work.

## Start the review app (owner setup)

Run these commands from the project directory. Python 3.14.6 was used for verification; use the project's virtual environment rather than Conda's base interpreter.

```sh
cd /Users/luisweekes/Code/Inventory-tracker/automated-inventory-tracker
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

If `.venv` already exists, skip its creation and run the installation/start commands. Open **http://127.0.0.1:8501** in your browser. Leave the terminal running; press **Ctrl+C** there to stop the app. If the port is occupied, use `.venv/bin/python -m streamlit run app.py --server.port 8502` and open the port shown in the terminal.

**Saved results** works with the committed `data/runs/` and requires no API key. For live extraction, create `.env` from `.env.example` if it does not already exist (do not replace an existing configured file). Set:

```dotenv
OPENAI_API_KEY=your-key-here
VISION_MODEL=gpt-5.4-mini
DATA_DIR=./data
```

Keep the real key in `.env`, never in Git or the UI. Restart Streamlit after changing settings. Shell environment values override `.env`. An API authentication error is saved in a failed run; check the configured key without sharing it with reviewers. Live extraction uses the existing pipeline and its per-page run tracking; clicking Extract sheet again deliberately creates new attempts. Normal editing, approval, and downloading never call the LLM.

The theme takes visual cues from [Towards AI](https://towardsai.com/): cream backgrounds, navy text, blue accents, serif headings, and restrained dividers. The review table uses [Streamlit's editable data grid](https://docs.streamlit.io/develop/api-reference/data/st.data_editor).

## Reviewer instructions

1. Open the app at **http://127.0.0.1:8501** on the computer where it is running.
2. In the sidebar choose **Saved results**. Select a saved document, then an extraction attempt for each page. The newest successful attempt per page is selected initially; timestamps are UTC. Document labels show the source filename when known, with a short hash as fallback. Match the source preview before editing.
3. Inspect **Original sheet** beside the table. Use **View page** to inspect each page of a PDF; the table contains all selected pages in page/row order. Hover over the image and use fullscreen for handwriting. **Download original file** is available for runs with original-file metadata; older runs still show their saved source image.
4. Edit any of the eight business cells by double-clicking it, typing, and pressing Enter or clicking outside the cell to commit. Values are text to preserve handwriting such as `1 box`, original date spellings, and leading zeros. Use the grid's fullscreen control or horizontal scrollbar for wider tables. Page/Row and the final **risk** / **risk_reason** columns are read-only.
5. Read every risk warning. The displayed risk describes the saved extraction; correcting a value keeps its original warning visible. Expand **Source notes & inherited fields** for inheritance, uncertainty, and visual evidence. Edits do not propagate to other rows: check every affected value yourself.
6. To leave out a row, check **Exclude** and enter an **Exclusion reason**. The row remains visible for audit, but does not appear in the final CSV. Cancelled/high-risk rows are not silently excluded for you.
7. Enter your **Reviewer name**. Check the confirmation only after comparing every page and every included row with the source, checking exclusions and risk warnings, and confirming that no rows were missed. Incomplete PDFs cannot be approved. If extraction missed a row, do not approve: adding/splitting rows is not implemented yet.
8. Click **Approve file & prepare CSV →**, then **Download approved CSV ↓** to save the file through your browser as well as keeping the approval snapshot on the server. The CSV contains only **Quantity, Price, Description, Person name, Job site, Job name, Job #, Date**, in that order. It includes only rows you kept, with your edits. Risk/inheritance/reviewer fields stay out of the business CSV.

For a new file, select **New extraction**, then **Upload a file** or **Choose a sample**. Choose a PDF, PNG, JPEG, WEBP, or static GIF and click **Extract sheet →**. The owner must have configured the API key; this explicit action sends prepared page images to the model and may incur charges. Files are limited to 20 MiB, with the existing ingestion page/pixel/content checks. Wait for extraction, then follow steps 3–8. A failed page stops extraction and reports an incomplete document; earlier results remain in Saved results. Do not refresh during an extraction.

Draft edits are held only in the browser session. Closing/reloading the tab or changing document/mode/attempt can discard an unapproved draft. Source pages, rows, and extraction artifacts are never overwritten. Committing another cell edit or changing the reviewer removes the current download and requires renewed approval. A previously downloaded CSV remains a separate historical snapshot.

Approval saves a new immutable folder under `data/approved_outputs/<UTC timestamp>_<UUID>_<source stem>/` containing `<source stem>_approved.csv` and `approval.json`. The JSON records reviewer/time, all final row values and exclusions, source run manifests/hashes, extraction risks, and CSV hash. Reviewer names are self-asserted for this local MVP. The existing pipeline's typed numeric/date normalization and acceptance categories remain separate future work: this export preserves explicitly reviewed text and applies spreadsheet formula escaping. Import Job # as text in Excel to preserve leading zeros. All `data/` remains Git-tracked per project policy; saving is local and does not automatically commit/push anything.

A reviewer on their own computer needs a copy of the project **including `data/`**, then runs the same virtual-environment installation and Streamlit command locally. Saved-result review does not need your API key. The app defaults to localhost and has no login; a remotely hosted multiuser deployment has not been configured. Use this as a local review workspace.

## Intended workflow

Upload → validate/render pages → extract raw observations → resolve repetitions and normalize → validate and flag → human review/approval → export an approved snapshot.

Source files, raw model responses, corrected values, and review history remain separate. Initially, every row requires human approval; risk flags determine review priority.

## Extraction run tracking

`runs.start_run()` creates a unique directory under `data/runs/` before an API request. Folder names use `YYYY-MM-DD_HH-MM-SS.ffffffZ_<run_id>[_<source stem>]` (UTC), so sorting by name orders runs oldest to newest. The timestamp matches the manifest's `started_at`; the UUID remains the stable run ID. Supply a `RunConfig`, document/page identity, input files (including the actual page image), the effective prompt file, rules file, and actual provider response schema. It saves copies and SHA-256 hashes so editing originals cannot change that run's record.

`RunConfig` records provider, requested model, prompt/rules/schema versions, model settings, preprocessing settings, and an optional code/build version. Record explicitly sent model options and rendering/crop settings; do not include credentials. Use saved inputs/prompt for the eventual request. A prompt template alone is insufficient if additional instructions or examples are sent.

`runs.finish_run()` saves the full raw JSON response and validated `SourcePage`, or records an error and any available response. The manifest records UTC timestamps, outcome, returned model ID, provider request ID, and usage when available. `runs.load_run()` reads the manifest. Each retry starts a new run; completed records cannot be finalized again through this API. Interrupted attempts remain `running` until explicitly recorded as failed.

The extractor uses this file-based persistence directly. Hashes identify saved artifacts; files remain editable by someone with filesystem access. No run metadata is added to business output columns.

## Run PDF or image extraction

Install the implemented components (verified with Python 3.14.6):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'openai==3.50.0' 'pydantic>=2.0,<3.0' 'python-dotenv==1.2.4' 'pillow==13.0.0' 'pymupdf==2.1'
```

Set `OPENAI_API_KEY` in your local `.env`. `VISION_MODEL` selects the model, falling back to `EXTRACTION_MODEL` for existing configurations, then `gpt-5.4-mini`. A `--model` argument overrides both. No client or network call is created at import time.

To make a live call:

```sh
.venv/bin/python extractor.py 'samples/Inventory Sheet 3.png' --model gpt-5.4-mini
```

Or call from Python:

```python
from pathlib import Path
from pipeline import extract_file

results = extract_file(Path('samples/Inventory Sheet 3.png'))
for result in results:
    print(result.run_dir / 'preview_unreviewed.csv')  # already saved
```

PDF, PNG, JPEG, WEBP, and non-animated GIF are supported. The same CLI accepts a PDF and extracts each page sequentially. To validate/render without an API call or API key:

```sh
.venv/bin/python extractor.py '/path/to/inventory.pdf' --prepare-only
```

Remove `--prepare-only` to extract all pages. PDF rendering defaults to 200 DPI; `--dpi` accepts 72–300. All pages share the original file's SHA-256 document ID and retain their one-based PDF page numbers. `--page-number` is only for a single image's supplied context; it cannot relabel PDF pages.

Originals are saved once under `data/documents/<document_hash>/original.<type>`. A versioned renderer/profile folder contains `page_001.png`, subsequent pages, and `ingestion.json` with hashes, dimensions, renderer version, DPI/rotation, and page count. Repeating preparation with the same profile reuses identical artifacts instead of rewriting them. Each extraction run snapshots its actual PNG and records relative original/prepared paths plus the original hash and renderer settings.

`ingestion.ingest_bytes(content, filename)` is the reusable boundary for future uploads; `ingest_file(path)` reads a bounded regular local file. `pipeline.extract_file(path)` prepares the entire document before calling a model. On a later page's API failure it raises `DocumentExtractionError`, reports partial progress, and retains previous results; it never reports the incomplete document as complete. `extractor.extract_image(bytes)` remains the lower-level validated single-image API.

## Input validation

- Allowed filename extensions must match the decoded file type. Empty files, malformed/truncated files, directories, symlink inputs, animated images, unsupported formats, and upload names containing path separators/control characters are rejected.
- Defaults: 20 MiB per input file, 20 PDF pages, 10,000 pixels per side, 20 million pixels per page, 100 million pixels per document, 100 MiB of prepared PNG data, and 20,000 PDF objects. Oversized PDF page dimensions and aggregate pixels are checked before rendering. Limits are centralized in `ingestion.InputLimits` and recorded in run configuration.
- Encrypted PDFs, PDFs requiring repair, attachments, and detected scripting/launch/additional-action features are rejected. Native parsers are used without executing PDF actions or fetching document links. Rendering includes visible annotations to preserve highlights and strike-throughs. See [PyMuPDF rendering documentation](https://pymupdf.readthedocs.io/en/latest/page.html).
- Images are fully decoded, EXIF-oriented, composited onto white, and re-encoded as RGB PNGs without their original metadata or trailing payload. Originals remain untrusted audit artifacts; generated output paths use hashes and page numbers rather than upload filenames.

These checks constrain the supported input surface; they are not antivirus scanning or an OS sandbox. A future public upload backend should run native parsing/rendering in an isolated worker with CPU/time/memory limits. The current local implementation enforces byte/page/pixel/object limits but has no separate parser timeout.

Each call makes one explicit attempt and saves results once under `data/runs/<UTC timestamp>_<run_id>[_<source stem>]/`: `raw_response.json`, validated `page.json` and `preview_unreviewed.csv` on success, and the run manifest/input/configuration snapshots. It does not write another copy to `outputs/raw/`. Repeating the function intentionally creates another run; there is no cache or automatic SDK retry. `ExtractionError.run_dir` locates a failed attempt. Model responses are preserved before extraction parsing; HTTP failures record sanitized status/request metadata without copying potentially sensitive SDK exception messages.

The CSV preview has exactly the eight business headers and shows raw row text, including cancelled/uncertain candidates and ditto marks. It does not resolve inheritance, propagate page headers, or grant approval. Missing/illegible values appear empty; cancellation/uncertainty details remain in `page.json`. Formula-like text is prefixed with an apostrophe for spreadsheet safety, while original text remains in JSON. UTF-8 with a BOM helps spreadsheet applications read the file; import Job # as text to preserve leading zeros in spreadsheet displays.

Older successful runs can receive a preview via `runs.add_preview(run_directory)` without another model call. It records the CSV hash in the manifest and preserves existing raw/page artifacts. Repeated calls reuse the existing preview; they do not overwrite it.

Run folders include the source filename stem when known, so all intermediate files are grouped under a readable name. Intermediate basenames stay fixed. Older sample runs were renamed only where an original or input hash matched a bundled sample; stored run IDs and artifact hashes are unchanged.

## Resolve inherited values

Each successful extraction now also creates `resolved_inherited.csv` in its run directory. It has 16 columns: each business value followed by a `true`/`false` flag, for example `Quantity, Quantity_inherited, Price, Price_inherited, ...`. This is an unreviewed intermediary, not the final eight-column approved output.

The resolver reads `page.json`, preserving richer source evidence than the preview CSV. Per column, a new non-empty value replaces the current source. Blanks/missing values, explicit ditto fields, and whole-cell repetition markers (quotes, downward arrows, `ditto`, `do.`, `d/o`) inherit from above. Markers are recognized even when the model labels them as text; text containing a quote, such as `2" pipe`, remains a real value. All eight columns participate, including Quantity, Price, and Description, per the current requested policy.

Date values must parse as real calendar dates under the formats in `config/resolver_v001.json`; invalid date strings inherit the previous valid date. Formats include ISO, day/month and month/day with two- or four-digit years, and selected written-month forms. Values retain their original spelling; ambiguous dates are not converted to a presumed locale. If no usable preceding value exists, the cell stays empty, its inherited flag is false, and JSON records it as unresolved.

Page-wide header values can seed a column. State resets at every page: there is no cross-page/document inheritance or inferred section reset. Columns remain independent; a new person/job value does not reset the others. All candidate rows, including cancelled/uncertain rows, remain in the intermediary and can supply subsequent values. Cancelled rows receive high risk during validation; automatic exclusion remains unimplemented.

`resolved_inherited.json` records each source row ID, resolved text values, inherited source-cell references, reasons (`blank`, `repetition_marker`, `invalid_date`), and unresolved fields. References point to the original supplying row (or page header), not just the preceding copied row. `resolver_rules.json` snapshots the applied rules. The manifest records artifact hashes, resolution time, and the source page hash. Original raw/page/preview files are untouched. Quantity/Price remain text (for example `1 box`); no typed normalization or approval is implied.

To resolve existing successful runs without any model call:

```sh
.venv/bin/python resolver.py data/runs
```

You can also pass one run directory. Failed runs are skipped. Repeating resolution reuses the recorded artifacts after hash checks; differing rules or edited artifacts are rejected rather than overwriting history. Resolution revision management for future rule changes is not implemented yet. Spreadsheet text escaping applies to both raw and resolved CSVs.

The default prompt is `prompts/extraction_v004.txt`, with visual markings, highlighting, strike-throughs, and blank-continuation inferences requested explicitly. The wire schema is `source-page-wire-v003`. Generic markings mean review/correction annotations such as circles, ticks, and scribbles; ordinary handwritten values and printed grid lines are not markings. Pass `prompt_path` and optionally `prompt_version` to compare alternatives. A short appended contract reconciles field names and absent values with the strict API schema; the full effective prompt and exact schema are saved in the run. This follows the official [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) interface. Existing run snapshots are unchanged; make a new extraction to obtain the new observations.

## Assign row risk

Successful extractions also create `validated_risk.csv`: the 16 resolved value/inherited columns followed by adjacent `risk` and `risk_reason` columns. `validated_risk.json` retains source references and all resolution metadata. Risk is separate from acceptance and human approval.

Defaults in `config/validator_v001.json`:

- **High:** a row is marked, crossed out/drawn across, highlighted, or explicitly cancelled.
- **Medium:** Job #, Price, or Quantity remains missing after resolution; any Quantity, Price, or Description is inherited; or more than three fields are inherited.
- **Low:** no configured rule matches.

The later “anything … inherited” rule takes precedence over the earlier “two or more” wording. High overrides medium; reasons include all matching rules. Missing means empty/whitespace or null after resolution; zero is present. Four inherited fields meet the count threshold, while three alone do not. Unknown visual observations add an incomplete-assessment note without inventing a positive marking. Older runs need fresh extraction to assess previously unrecorded markings.

Backfill saved successful runs without a model call:

```sh
.venv/bin/python validator.py data/runs
```

One run directory is also accepted; failed runs are skipped. The validator reads source JSON and saved resolution JSON, creating resolution first if absent. `validation_rules.json` snapshots the parameters; the manifest records timestamps, dependency hashes, and output hashes. Repeated validation verifies and reuses saved artifacts. Changed rules or edited artifacts are rejected rather than overwriting history. To supply an alternate rules file programmatically, call `runs.add_validation(run_directory, rules_path=Path(...))`.

## Setup and deployment commands

The file/folder structure is documented in `notes/DESIGN.md`. Prompt quality and business rules still need evaluation on labeled sheets. `requirements.txt` includes the pinned, tested Streamlit/pandas and extraction dependencies, plus test dependencies.

Copy `.env.example` to `.env` for local configuration. The extractor loads this file without overriding already-set environment variables. Everything under `data/` is included in version control: inputs, prompts/configuration snapshots, responses, manifests, CSV previews, and future databases. The `outputs/` directory remains ignored apart from its placeholder.

Verified tests (Python 3.14.6, Pydantic 2.14.3), after installing the dependencies above:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The test suite covers real PDF rendering, preserved annotations/rotation, EXIF handling, malformed/mismatched/oversized/active inputs, prepare-only CLI usage, multi-page extraction, partial failures, risk precedence, inheritance thresholds, configurable rules, artifact reuse, approval/export boundaries, multi-page completeness, Streamlit editing/approval state, upload routing, and existing schema/run/preview contracts. API calls use the real SDK with a local mock HTTP transport; no live model requests were made during verification. Install the extraction dependencies above to run the full suite.

An HTTP 401 indicates an authentication failure. Check the active API key and project/organization access using the official [error guide](https://developers.openai.com/api/docs/guides/error-codes). The extractor reports this directly without displaying key values. An exported shell key overrides `.env`; to explicitly use the project's `.env`, run `env -u OPENAI_API_KEY .venv/bin/python extractor.py 'samples/Inventory Sheet 3.png'`.

Hosting/deployment commands will be added when a deployment target is chosen.

Before deployment, record the tested Python version, dependency installation, environment variables, local start command, test command, database migration/backup procedure, and hosting/release/rollback commands here. Hosting has not been selected.

Keep `.env` and API credentials out of Git and out of run snapshots. Per the project policy, commit all `data/` artifacts so reviewers can inspect extraction runs in GitHub. The run writer saves data locally; normal Git commits/pushes publish it.
