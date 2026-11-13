# Automated inventory tracker

Planned tool for converting PDF and image inventory removal/sign-out sheets into reviewed CSV and XLSX files, with one row per line item and traceability back to the source sheet.

## Project status

Project scaffold created. Shared Pydantic entities, local run tracking (`runs.py`), and contract tests are implemented; provider extraction, review, and file export remain scaffolds. There is no runnable application or deployment.

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

This is local file persistence, not SQLite or automatic provider integration. Hashes identify saved artifacts; files remain editable by someone with filesystem access. No run metadata is added to business output columns.

## Setup and deployment commands

The file/folder structure is documented in `notes/DESIGN.md`. The extraction prompt and rules file remain drafts; business policies and provider integration still need implementation. `requirements.txt` lists planned application dependencies; the implemented entities require Pydantic 2.

Copy `.env.example` to `.env` for local configuration. These variables are placeholders until configuration loading is implemented. Local data and exports are ignored by Git; only their empty directory placeholders are tracked.

Verified schema-only setup and tests (Python 3.14.6, Pydantic 2.14.3):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir 'pydantic>=2.0,<3.0'
.venv/bin/python -m unittest discover -s tests -v
```

All sixteen schema/run contract tests pass. Other planned application dependencies are not needed for this check.

Start and deployment commands will be added as components become runnable and are verified.

Before deployment, record the tested Python version, dependency installation, environment variables, local start command, test command, database migration/backup procedure, and hosting/release/rollback commands here. Hosting has not been selected.

Never commit `.env`, real uploaded sheets, application databases, or generated exports containing real data. Commit only synthetic or suitably anonymized evaluation samples.
