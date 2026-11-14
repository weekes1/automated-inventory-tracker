"""Extract one image through OpenAI and persist results once through runs.py."""

import argparse
import base64
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

from ingestion import DEFAULT_LIMITS, inspect_image
from runs import add_resolution, add_validation, finish_run, load_run, start_run
from schemas import InventoryRow, RunConfig, SourcePage


ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "source-page-wire-v003"
PROMPT_CONTRACT = """
API response contract (takes precedence over conflicting output instructions):
Return the supplied JSON schema, with no document_id, page_number, or row_id.
The application assigns these identities. Number candidate rows from 1 in visual
order. Use cancellation='active', 'cancelled', or 'uncertain', and the per-field
uncertain flag. Do not return inherit_fields, uncertain_fields, or cancelled.
Every canonical key in fields/header_fields is required by the API schema:
use null for an absent/unobserved field; the application removes these placeholders.
A visible blank is a field object with kind='blank' and raw_text=''. A readable
repetition mark keeps its raw_text and kind='ditto'. Illegible writing uses a
field object with kind='illegible', raw_text=null, and uncertain=true.
Do not expand repetitions or copy previous values. inherited_from must be null.
If a visibly blank cell might mean continuation, keep kind='blank', raw_text='',
set inference='blank_as_ditto', uncertain=true, and explain the visible context
in that field's notes. Otherwise inference is null. Do not invent a ditto mark.
Record marked, highlighted and crossed_out for every row independently of cancellation:
true means visible, false means clearly absent, null means unclear/unassessed.
marked means other non-text review/correction marks, such as circles, ticks,
scribbles, or stamps. Normal field handwriting and printed grids are not marks.
Describe colour/extent and any partial-cell strike-through in row notes. Colour
alone never establishes cancellation or job identity. A field correction does
not by itself cancel the whole row. Set row uncertain=true for uncertain marks,
cancellation, or any uncertain/inferred field. Preserve all candidate rows.
Keep raw strings, uncertain/cancelled rows, and evidence notes. No acceptance
levels, normalized business rows, approval decisions, or private reasoning.
"""


@dataclass(frozen=True)
class ExtractionResult:
    page: SourcePage
    run_dir: Path


class ExtractionError(RuntimeError):
    def __init__(self, run_dir: Path, reason: str):
        self.run_dir = run_dir
        super().__init__(f"Extraction failed: {reason}\nInspect {run_dir / 'manifest.json'}")


def extraction_response_schema() -> dict:
    """Adapt the shared source schema to the API's strict, fixed-key objects.

    Identity fields are application-owned. Nullable field slots replace open
    dictionaries only on the wire, preserving absent versus observed blank.
    """
    schema = SourcePage.model_json_schema()
    for name in ("document_id", "page_number"):
        schema["properties"].pop(name)
    row = schema["$defs"]["SourceRow"]
    row["properties"].pop("row_id")
    for owner, name in ((schema, "header_fields"), (row, "fields")):
        owner["properties"][name] = {
            "type": "object",
            "properties": {
                key: {"anyOf": [{"$ref": "#/$defs/SourceField"}, {"type": "null"}]}
                for key in InventoryRow.model_fields
            },
        }
    schema["$defs"]["SourceField"]["properties"]["inherited_from"] = {"type": "null"}
    schema["$defs"].pop("SourceReference")

    def make_strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for child in node.values():
                make_strict(child)
        elif isinstance(node, list):
            for child in node:
                make_strict(child)

    make_strict(schema)
    return schema


def _source_page(text: str, document_id: str, page_number: int, run_id: str) -> SourcePage:
    payload = json.loads(text)
    # Reject unexpected app-owned identities instead of silently trusting them.
    if any(key in payload for key in ("document_id", "page_number")):
        raise ValueError("The model returned application-owned page identities")
    payload["document_id"] = document_id
    payload["page_number"] = page_number
    for fields in [payload["header_fields"], *(row["fields"] for row in payload["rows"])]:
        if fields.keys() - InventoryRow.model_fields.keys():
            raise ValueError("The model returned an unknown inventory field")
    payload["header_fields"] = {
        key: value for key, value in payload["header_fields"].items() if value is not None
    }
    for row in payload["rows"]:
        if "row_id" in row:
            raise ValueError("The model returned an application-owned row identity")
        row["row_id"] = f"{run_id}:{row['row_number']}"
        row["fields"] = {key: value for key, value in row["fields"].items() if value is not None}
    return SourcePage.model_validate(payload)


def extract_image(
    image_bytes: bytes,
    *,
    document_id: str | None = None,
    page_number: int = 1,
    model: str | None = None,
    prompt_path: Path = ROOT / "prompts/extraction_v004.txt",
    prompt_version: str | None = None,
    runs_dir: Path | None = None,
    client: OpenAI | None = None,
    source_metadata: dict | None = None,
) -> ExtractionResult:
    """Call once and save one raw response plus one validated page per run.

    No import-time calls, automatic SDK retries, or duplicate outputs/raw copy.
    Repeated invocations intentionally create distinct runs. PDFs must first be
    rendered to images. A supplied client is useful for offline tests.
    """
    load_dotenv(ROOT / ".env", override=False)
    mime, width, height = inspect_image(image_bytes)
    model = model or os.getenv("VISION_MODEL") or os.getenv("EXTRACTION_MODEL") or "gpt-5.4-mini"
    document_id = document_id or sha256(image_bytes).hexdigest()
    if not isinstance(document_id, str) or not document_id.strip() or isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        raise ValueError("Provide a non-empty document ID and positive integer page number")
    prompt_path = Path(prompt_path)
    rules_path = ROOT / "config/rules_v001.json"
    settings = {"image_detail": "high", "store": False, "timeout_seconds": 120, "max_retries": 0}
    config = RunConfig(
        provider="openai", model=model, prompt_version=prompt_version or prompt_path.stem,
        rules_version=json.loads(rules_path.read_text(encoding="utf-8"))["version"],
        schema_version=SCHEMA_VERSION, model_settings=settings,
        preprocessing={"mime_type": mime, "width": width, "height": height, "transforms": [],
                       "validation_limits": asdict(DEFAULT_LIMITS), "source": source_metadata or {}},
    )
    schema = extraction_response_schema()
    # Temporary files adapt the byte-based API to the existing snapshot writer.
    with TemporaryDirectory() as temporary:
        staging = Path(temporary)
        image_path = staging / f"page.{mime.split('/')[1]}"
        image_path.write_bytes(image_bytes)
        effective_prompt = staging / "effective_prompt.txt"
        effective_prompt.write_text(prompt_path.read_text(encoding="utf-8") + "\n" + PROMPT_CONTRACT, encoding="utf-8")
        directory = start_run(
            config, document_id=document_id, page_number=page_number,
            input_paths=[image_path], prompt_path=effective_prompt, rules_path=rules_path,
            response_schema=schema,
            runs_dir=Path(runs_dir) if runs_dir is not None else Path(os.getenv("DATA_DIR") or ROOT / "data") / "runs",
        )
    run = load_run(directory)
    raw = page = error = None
    returned_model = request_id = None
    usage = {}
    caught = None
    try:
        encoded = base64.b64encode((directory / run.inputs[0].path).read_bytes()).decode("ascii")
        with ExitStack() as stack:
            api = (client.with_options(max_retries=0, timeout=120) if client is not None
                   else stack.enter_context(OpenAI(max_retries=0, timeout=120)))
            response = api.responses.create(
                model=config.model, store=False,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": (directory / run.prompt.path).read_text(encoding="utf-8")},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"},
                ]}],
                text={"format": {"type": "json_schema", "name": "page_extraction", "strict": True,
                                 "schema": json.loads((directory / run.response_schema.path).read_text(encoding="utf-8"))}},
            )
        raw = response.model_dump(mode="json")
        returned_model = response.model
        request_id = response._request_id
        usage = response.usage.model_dump(mode="json") if response.usage else {}
        if response.status != "completed" or not response.output_text:
            raise ValueError("Model returned an incomplete response or no extraction text")
        page = _source_page(response.output_text, document_id, page_number, run.run_id)
    except Exception as exc:
        caught = exc
        # Avoid copying SDK exception messages that can contain credentials.
        error = f"{type(exc).__name__}: request or extraction validation failed"
        if isinstance(exc, APIStatusError):
            request_id = exc.request_id
            raw = {"error_type": type(exc).__name__, "status_code": exc.status_code}
            error = f"{type(exc).__name__} (HTTP {exc.status_code})"
            if exc.status_code == 401:
                error += (
                    ": authentication failed. Check that OPENAI_API_KEY is valid and active. "
                    "An existing shell variable overrides the project's .env value."
                )
    # The only persistence owner: finalization occurs once, outside the try block
    # so a disk error cannot trigger a second attempt to save the result.
    finish_run(directory, raw_response=raw, page=page, error=error,
               returned_model=returned_model, provider_request_id=request_id, usage=usage)
    if caught is not None:
        raise ExtractionError(directory, error) from caught
    add_resolution(directory)
    add_validation(directory)
    return ExtractionResult(page=page, run_dir=directory)


def main() -> None:
    from pipeline import DocumentExtractionError, extract_file

    parser = argparse.ArgumentParser(description="Validate a PDF/image, convert to PNG, and extract each page.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--document-id")
    parser.add_argument("--page-number", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=200, help="PDF rendering DPI (72-300; default 200)")
    parser.add_argument("--prepare-only", action="store_true", help="Validate/save PNG pages without calling a model")
    args = parser.parse_args()
    try:
        if args.prepare_only:
            from ingestion import ingest_file
            load_dotenv(ROOT / ".env", override=False)
            document = ingest_file(args.file, data_dir=Path(os.getenv("DATA_DIR") or ROOT / "data"), dpi=args.dpi)
            for page in document.pages:
                print(f"Prepared page {page.page_number}: {page.path}")
            return
        results = extract_file(args.file, model=args.model, document_id=args.document_id,
                               page_number=args.page_number, dpi=args.dpi)
    except DocumentExtractionError as exc:
        parser.exit(1, f"{exc}\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Invalid input or configuration: {exc}\n")
    for result in results:
        print(f"Page {result.page.page_number}: saved {len(result.page.rows)} candidate rows to {result.run_dir / 'page.json'}")
        print(f"Unreviewed CSV preview: {result.run_dir / 'preview_unreviewed.csv'}")
        print(f"Resolved inheritance CSV: {result.run_dir / 'resolved_inherited.csv'}")
        print(f"Risk CSV: {result.run_dir / 'validated_risk.csv'}")


if __name__ == "__main__":
    main()
