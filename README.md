# Automated inventory tracker

Planned tool for converting PDF and image inventory removal/sign-out sheets into reviewed CSV and XLSX files, with one row per line item and traceability back to the source sheet.

## Project status

Architecture and requirements stage. There is no runnable extraction application or deployment yet.

- [DESIGN.md](DESIGN.md): architecture, module responsibilities, review rules, model evaluation, and implementation sequence.
- [Prompts.md](Prompts.md): append-only user project prompt record, with timestamps and their provenance.
- [AGENTS.md](AGENTS.md): instructions for maintaining that record in future repository work.

## Intended workflow

Upload → validate/render pages → extract raw observations → resolve repetitions and normalize → validate and flag → human review/approval → export an approved snapshot.

Source files, raw model responses, corrected values, and review history remain separate. Initially, every row requires human approval; risk flags determine review priority.

## Setup and deployment commands

Commands will be added here as each component becomes runnable and is verified. The proposed file tree in DESIGN.md is not an implemented application.

Before deployment, record the tested Python version, dependency installation, environment variables, local start command, test command, database migration/backup procedure, and hosting/release/rollback commands here. Hosting has not been selected.

Never commit `.env`, real uploaded sheets, application databases, or generated exports containing real data. Commit only synthetic or suitably anonymized evaluation samples.
