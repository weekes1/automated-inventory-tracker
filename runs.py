"""Local run manifests and artifact snapshots; no database or provider calls."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

from schemas import ExtractionRun, RunArtifact, RunConfig, SourcePage


def _save_artifact(directory: Path, name: str, content: bytes,
                   original_name: str | None = None) -> RunArtifact:
    (directory / name).write_bytes(content)
    return RunArtifact(path=name, sha256=sha256(content).hexdigest(),
                       original_name=original_name)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def _save_manifest(directory: Path, run: ExtractionRun) -> None:
    # Replace the manifest atomically so readers see a complete JSON record.
    temporary = directory / "manifest.tmp"
    temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(directory / "manifest.json")


def load_run(directory: Path) -> ExtractionRun:
    """Read and validate an existing manifest."""
    return ExtractionRun.model_validate_json(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )


def start_run(
    config: RunConfig,
    *,
    document_id: str,
    page_number: int,
    input_paths: list[Path],
    prompt_path: Path,
    rules_path: Path,
    response_schema: dict[str, JsonValue],
    runs_dir: Path = Path("data/runs"),
) -> Path:
    """Snapshot the effective inputs/config BEFORE making a provider request.

    Use the saved prompt and inputs for the actual call, not mutable originals.
    response_schema must be the actual provider response schema. Each retry
    gets a new run directory; an interrupted call remains visibly running.
    """
    if not input_paths:
        raise ValueError("At least one input file is required")
    prompt = prompt_path.read_bytes()
    rules = rules_path.read_bytes()
    if json.loads(rules).get("version") != config.rules_version:
        raise ValueError("rules_version does not match the supplied rules file")
    schema = _json_bytes(response_schema)
    inputs = [(path, path.read_bytes()) for path in input_paths]
    run_id = str(uuid4())
    directory = runs_dir / run_id
    directory.mkdir(parents=True)
    run = ExtractionRun(
        run_id=run_id, document_id=document_id, page_number=page_number,
        started_at=datetime.now(timezone.utc), config=config,
        inputs=[
            _save_artifact(directory, f"input_{index:03d}{path.suffix}", data, path.name)
            for index, (path, data) in enumerate(inputs, start=1)
        ],
        prompt=_save_artifact(directory, "prompt.txt", prompt, prompt_path.name),
        rules=_save_artifact(directory, "rules.json", rules, rules_path.name),
        response_schema=_save_artifact(directory, "response_schema.json", schema),
    )
    _save_manifest(directory, run)
    return directory


def finish_run(
    directory: Path,
    *,
    raw_response: JsonValue = None,
    page: SourcePage | None = None,
    error: str | None = None,
    returned_model: str | None = None,
    provider_request_id: str | None = None,
    usage: dict[str, JsonValue] | None = None,
) -> ExtractionRun:
    """Save success or failure, preserving any available raw provider response.

    Pass the full JSON response, including refusals/invalid extraction content,
    and a concise error for failures. No approval or completeness is implied.
    """
    run = load_run(directory)
    if run.status != "running":
        raise ValueError("This run already has a final outcome; start a new run")
    if error is not None and not error.strip():
        raise ValueError("A failure needs a non-empty error explanation")
    if error is None and (page is None or raw_response is None):
        raise ValueError("Success requires a raw response and a validated page")
    if page is not None and (
        page.document_id != run.document_id or page.page_number != run.page_number
    ):
        raise ValueError("The extracted page does not belong to this run")
    # Validate before writing. Invalid extraction text can still be stored as a
    # JSON string inside the full response, rather than being parsed/rewritten.
    raw = TypeAdapter(JsonValue).validate_python(raw_response)
    raw_bytes = None if raw is None else _json_bytes(raw)
    page_bytes = None if page is None else page.model_dump_json(indent=2).encode("utf-8")
    result = ExtractionRun.model_validate({
        **run.model_dump(),
        "status": "failed" if error is not None else "succeeded",
        "finished_at": datetime.now(timezone.utc),
        "returned_model": returned_model,
        "provider_request_id": provider_request_id,
        "usage": usage or {},
        "error": error,
        "raw_response": None if raw_bytes is None else RunArtifact(
            path="raw_response.json", sha256=sha256(raw_bytes).hexdigest()),
        "extracted_page": None if page_bytes is None else RunArtifact(
            path="page.json", sha256=sha256(page_bytes).hexdigest()),
    })
    if raw_bytes is not None:
        _save_artifact(directory, "raw_response.json", raw_bytes)
    if page_bytes is not None:
        _save_artifact(directory, "page.json", page_bytes)
    _save_manifest(directory, result)
    return result
