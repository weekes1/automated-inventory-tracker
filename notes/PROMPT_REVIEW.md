# Raw extraction prompt review

Reviewed `prompts/extraction.txt` against `schemas.py` on 2026-11-13. Original preserved. Alternative: `prompts/extraction_v002.txt`, used for the initial adapter. The v003 revision added highlighting, strike-throughs, and blank-as-ditto inference. Current default `prompts/extraction_v004.txt` also records generic review/correction markings separately from ordinary handwriting and leaves risk assignment to deterministic validation; the appended API contract was updated alongside the schema. The new revision has only been verified with mocked requests, not a fresh live transcription.

The original covers varying column order, multiline descriptions, independent contextual fields, and the limits of highlight colour well.

Recommended changes:

- Preserve raw ditto marks/arrows. Null should not erase readable evidence.
- Distinguish absent fields, visible blank cells, repetition marks, and illegible writing using SourceField's existing contract.
- Leave inheritance to deterministic resolution, including whether descriptions can repeat. The blanket rule to never inherit description is an unconfirmed business rule. The revised prompt expands no fields at all; initial tests leave inherited_from null to keep identity/reference handling simple.
- Match current model names and properties. There is no PageExtraction, inherit_fields, uncertain_fields, or cancelled boolean. Current entities use SourcePage/SourceRow/SourceField, uncertain, and three-state cancellation.
- Distinguish correction of a cell from cancellation of an entire row. Preserve ambiguous and cancelled candidates.
- Clarify that repeated-looking physical rows remain separate while a single physical row must not be emitted twice.
- Keep page-wide context in header_fields. Section-only context belongs in notes until the schema/resolver supports its scope; otherwise context can leak into unrelated rows.
- Keep uncertain header mapping and damaged/cropped-page evidence explicit. An empty row list is not proof that the source is empty.
- Request short evidence notes rather than a record of internal reasoning. Persist the actual response, prompt/model metadata, and source image when extraction is implemented.

## Integration boundary

SourcePage requires document_id/page_number and SourceRow requires row_id; these are application-owned identities. The draft in v001 asks for SourcePage while telling the model not to create its required IDs. The v002 prompt instead describes an identity-free response payload: the application supplies IDs before validating the assembled SourcePage. `extractor.py` now implements this adapter. It derives a strict provider schema, represents absent field slots as null on the wire, and removes those placeholders before validating SourcePage. An appended contract reconciles that transport detail with the original prompt's instruction to omit absent fields. Do not pass SourcePage's current schema unchanged while asking the model to omit required IDs.

The canonical Python field names remain authoritative in schemas.py. Any future response-schema builder should derive allowed field names there rather than maintaining an independent production field list in code. Prompt wording is not a substitute for schema validation or deterministic checks of observation consistency.

No model tests or performance claims accompany this revision. Compare the original and revised prompts on the same labeled pages before selecting one, especially for omitted rows, null/blank/ditto distinctions, and ambiguous cancellations.
