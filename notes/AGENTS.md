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

Keep architectural decisions in `notes/DESIGN.md` and verified setup/deployment commands in `README.md`. Distinguish planned components from runnable implementation. Never commit secrets, real uploaded sheets, runtime databases, or generated exports containing real data.
