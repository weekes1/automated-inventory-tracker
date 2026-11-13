# Repository instructions

## User prompt audit log

Maintain `Prompts.md` as the canonical user development prompt log (capitalization is intentional). Append every new user project prompt, including corrections and follow-up requests, before substantive project work. Do not log tool output, system/developer instructions, or automatically injected environment context as user prompts.

Preserve visible prompt text verbatim, including spelling and formatting, in a fenced text block with a unique sequential ID. Use a longer fence if the prompt contains a conflicting fence. Append amendments rather than rewriting earlier entries.

Record an ISO 8601 UTC timestamp and its provenance: use actual submitted time only when exposed; otherwise use current observed/logged time and state that submission time was unavailable. Never invent an exact submission time. Record unavailable attachments/prior context rather than claiming to capture them.

Redact credentials or secrets with an explicit redaction note rather than committing them. Keep ordinary project prompt content intact.

This manual log aids review but does not guarantee automatic capture outside this repository or tamper resistance. Runtime extraction templates belong in `prompts/`; versions/hashes belong in extraction run records.

## Design and status

Keep architectural decisions in `DESIGN.md` and verified setup/deployment commands in `README.md`. Distinguish planned components from runnable implementation. Never commit secrets, real uploaded sheets, runtime databases, or generated exports containing real data.
