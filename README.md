# Automated inventory tracker

Planned tool for converting PDF and image inventory removal/sign-out sheets into reviewed CSV and XLSX files, with one row per line item and traceability back to the source sheet.

## Project status

Shared Pydantic entities, local run tracking (`runs.py`), and OpenAI image extraction (`extractor.py`) are implemented. Review UI, PDF rendering, resolution, and file export remain scaffolds. There is no deployed application.

Input layouts may vary. Output is fixed to **Quantity · Price · Description · Person name · Job site · Job name · Job # · Date**. `InventoryRow` defines these fields once; `ProcessingRow` adds internal acceptance (`high`, `med`, `low`) and source/inheritance references. Assignment rules remain pending. Output projections exclude all internal metadata.

`SourcePage` contains header observations, source rows, layout notes, and general notes. Each `SourceRow` retains cancellation status and uncertainty; its `SourceField` values preserve literal text, ditto/blank/illegible markers, notes, and unverified inheritance hints. Stated reasons support review; they do not expose the model's internal reasoning.

- [DESIGN.md](notes/DESIGN.md): architecture, module responsibilities, review rules, model evaluation, and implementation sequence.
- [Prompts.md](notes/Prompts.md): append-only user project prompt record, with timestamps and their provenance.
- [AGENTS.md](notes/AGENTS.md): instructions for maintaining that record in future repository work.

## Intended workflow

Upload → validate/render pages → extract raw observations → resolve repetitions and normalize → validate and flag → human review/approval → export an approved snapshot.

Source files, raw model responses, corrected values, and review history remain separate. Initially, every row requires human approval; risk flags determine review priority.

## Extraction run tracking

`runs.start_run()` creates a unique directory under `data/runs/` before an API request. Supply a `RunConfig`, document/page identity, input files (including the actual page image), the effective prompt file, rules file, and actual provider response schema. It saves copies and SHA-256 hashes so editing originals cannot change that run's record.

`RunConfig` records provider, requested model, prompt/rules/schema versions, model settings, preprocessing settings, and an optional code/build version. Record explicitly sent model options and rendering/crop settings; do not include credentials. Use saved inputs/prompt for the eventual request. A prompt template alone is insufficient if additional instructions or examples are sent.

`runs.finish_run()` saves the full raw JSON response and validated `SourcePage`, or records an error and any available response. The manifest records UTC timestamps, outcome, returned model ID, provider request ID, and usage when available. `runs.load_run()` reads the manifest. Each retry starts a new run; completed records cannot be finalized again through this API. Interrupted attempts remain `running` until explicitly recorded as failed.

The extractor uses this file-based persistence directly. Hashes identify saved artifacts; files remain editable by someone with filesystem access. No run metadata is added to business output columns.

## Run image extraction

Install the implemented components (verified with Python 3.14.6):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'openai==3.50.0' 'pydantic>=2.0,<3.0' 'python-dotenv==1.2.4' 'pillow==13.0.0'
```

Set `OPENAI_API_KEY` in your local `.env`. `VISION_MODEL` selects the model, falling back to `EXTRACTION_MODEL` for existing configurations, then `gpt-5.4-mini`. A `--model` argument overrides both. No client or network call is created at import time.

To make a live call:

```sh
.venv/bin/python extractor.py 'samples/Inventory Sheet 3.png' --model gpt-5.4-mini
```

Or call from Python:

```python
from pathlib import Path
from extractor import extract_image

result = extract_image(Path('samples/Inventory Sheet 3.png').read_bytes())
page = result.page  # schemas.SourcePage
print(result.run_dir / 'page.json')  # already saved; no second write needed
```

PNG, JPEG, WEBP, and non-animated GIF are supported. PDFs must first be rendered to page images. When extracting a rendered PDF page, pass the original document's ID and its page number via `document_id`/`page_number` (or CLI `--document-id`/`--page-number`). Otherwise the document ID defaults to the image's SHA-256 hash.

Each call makes one explicit attempt and saves results once under `data/runs/<run_id>/`: `raw_response.json`, validated `page.json` and `preview_unreviewed.csv` on success, and the run manifest/input/configuration snapshots. It does not write another copy to `outputs/raw/`. Repeating the function intentionally creates another run; there is no cache or automatic SDK retry. `ExtractionError.run_dir` locates a failed attempt. Model responses are preserved before extraction parsing; HTTP failures record sanitized status/request metadata without copying potentially sensitive SDK exception messages.

The CSV preview has exactly the eight business headers and shows raw row text, including cancelled/uncertain candidates and ditto marks. It does not resolve inheritance, propagate page headers, or grant approval. Missing/illegible values appear empty; cancellation/uncertainty details remain in `page.json`. Formula-like text is prefixed with an apostrophe for spreadsheet safety, while original text remains in JSON. UTF-8 with a BOM helps spreadsheet applications read the file; import Job # as text to preserve leading zeros in spreadsheet displays.

Older successful runs can receive a preview via `runs.add_preview(run_directory)` without another model call. It records the CSV hash in the manifest and preserves existing raw/page artifacts. Repeated calls reuse the existing preview; they do not overwrite it.

The default prompt is `prompts/extraction_v002.txt`. Pass `prompt_path` and optionally `prompt_version` to compare alternatives. A short appended contract reconciles field names and absent values with the strict API schema; the full effective prompt and exact schema are saved in the run. This follows the official [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) interface.

## Setup and deployment commands

The file/folder structure is documented in `notes/DESIGN.md`. Prompt quality and business rules still need evaluation on labeled sheets. `requirements.txt` includes planned application dependencies as well as the pinned, tested extraction dependencies above.

Copy `.env.example` to `.env` for local configuration. The extractor loads this file without overriding already-set environment variables. Everything under `data/` is included in version control: inputs, prompts/configuration snapshots, responses, manifests, CSV previews, and future databases. The `outputs/` directory remains ignored apart from its placeholder.

Verified schema-only setup and tests (Python 3.14.6, Pydantic 2.14.3):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir 'pydantic>=2.0,<3.0'
.venv/bin/python -m unittest discover -s tests -v
```

All twenty-six tests pass, including previews and real OpenAI SDK requests routed to a local mock HTTP transport. No live model calls or real-document uploads were made during verification. Install the extraction dependencies above to run the full suite.

An HTTP 401 indicates an authentication failure. Check the active API key and project/organization access using the official [error guide](https://developers.openai.com/api/docs/guides/error-codes). The extractor reports this directly without displaying key values. An exported shell key overrides `.env`; to explicitly use the project's `.env`, run `env -u OPENAI_API_KEY .venv/bin/python extractor.py 'samples/Inventory Sheet 3.png'`.

Hosting/deployment commands will be added when a deployment target is chosen.

Before deployment, record the tested Python version, dependency installation, environment variables, local start command, test command, database migration/backup procedure, and hosting/release/rollback commands here. Hosting has not been selected.

Keep `.env` and API credentials out of Git and out of run snapshots. Per the project policy, commit all `data/` artifacts so reviewers can inspect extraction runs in GitHub. The run writer saves data locally; normal Git commits/pushes publish it.
