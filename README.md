# Automated inventory tracker

Planned tool for converting PDF and image inventory removal/sign-out sheets into reviewed CSV and XLSX files, with one row per line item and traceability back to the source sheet.

## Project status

Project scaffold created. Shared Pydantic entities and contract tests are implemented in `schemas.py` and `tests/test_schemas.py`; extraction, review, and file export remain scaffolds. There is no runnable application or deployment.

Input layouts may vary. Output is fixed to **Quantity · Price · Description · Person name · Job site · Job name · Job # · Date**. `InventoryRow` defines these fields once; `ProcessingRow` adds internal acceptance level with three provisional categories pending business rules. Output projections exclude acceptance level.

- [DESIGN.md](notes/DESIGN.md): architecture, module responsibilities, review rules, model evaluation, and implementation sequence.
- [Prompts.md](notes/Prompts.md): append-only user project prompt record, with timestamps and their provenance.
- [AGENTS.md](notes/AGENTS.md): instructions for maintaining that record in future repository work.

## Intended workflow

Upload → validate/render pages → extract raw observations → resolve repetitions and normalize → validate and flag → human review/approval → export an approved snapshot.

Source files, raw model responses, corrected values, and review history remain separate. Initially, every row requires human approval; risk flags determine review priority.

## Setup and deployment commands

The file/folder structure in `notes/DESIGN.md` exists. The extraction prompt and rules file remain drafts; raw observation schemas and business policies still need definition. `requirements.txt` lists planned application dependencies; the implemented entities require Pydantic 2.

Copy `.env.example` to `.env` for local configuration. These variables are placeholders until configuration loading is implemented. Local data and exports are ignored by Git; only their empty directory placeholders are tracked.

Verified schema-only setup and tests (Python 3.14.6, Pydantic 2.14.3):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir 'pydantic>=2.0,<3.0'
.venv/bin/python -m unittest discover -s tests -v
```

All six schema contract tests pass. Other planned application dependencies are not needed for this check.

Start and deployment commands will be added as components become runnable and are verified.

Before deployment, record the tested Python version, dependency installation, environment variables, local start command, test command, database migration/backup procedure, and hosting/release/rollback commands here. Hosting has not been selected.

Never commit `.env`, real uploaded sheets, application databases, or generated exports containing real data. Commit only synthetic or suitably anonymized evaluation samples.
