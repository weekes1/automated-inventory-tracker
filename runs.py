"""Local run manifests and artifact snapshots; no database or provider calls."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

from filenames import source_stem
from exporter import raw_preview_csv, resolved_inherited_csv, validated_risk_csv
from resolver import DEFAULT_RULES, ResolverRules, resolve_page
from schemas import ExtractionRun, ResolutionArtifacts, ResolvedPage, RunArtifact, RunConfig, SourcePage, ValidationArtifacts
from validator import DEFAULT_RULES as DEFAULT_VALIDATOR_RULES, ValidatorRules, validate_page


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


def run_directory_name(run_id: str, started_at: datetime, original_name: str = "") -> str:
    """UTC timestamp first for chronological name sorting; retain UUID identity."""
    timestamp = started_at.astimezone(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S.%fZ")
    stem = source_stem(original_name)
    return f"{timestamp}_{run_id}" + (f"_{stem}" if stem else "")


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
    started_at = datetime.now(timezone.utc)
    source = config.preprocessing.get("source", {})
    directory = runs_dir / run_directory_name(run_id, started_at, source.get("original_name", ""))
    directory.mkdir(parents=True)
    run = ExtractionRun(
        run_id=run_id, document_id=document_id, page_number=page_number,
        started_at=started_at, config=config,
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
    preview = raw_preview_csv(page) if page is not None and error is None else None
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
        "preview_csv": None if preview is None else RunArtifact(
            path="preview_unreviewed.csv", sha256=sha256(preview).hexdigest()),
    })
    if raw_bytes is not None:
        _save_artifact(directory, "raw_response.json", raw_bytes)
    if page_bytes is not None:
        _save_artifact(directory, "page.json", page_bytes)
    if preview is not None:
        _save_artifact(directory, "preview_unreviewed.csv", preview)
    _save_manifest(directory, result)
    return result


def add_preview(directory: Path) -> Path:
    """Add a preview to an older successful run without another model call.

    Preserve existing previews and raw/page files. Register the derived file
    and its hash in the manifest; repeated calls do not rewrite it.
    """
    run = load_run(directory)
    if run.status != "succeeded" or run.extracted_page is None:
        raise ValueError("Only successful runs with a validated page have previews")
    if run.preview_csv is not None:
        path = directory / run.preview_csv.path
        if sha256(path.read_bytes()).hexdigest() != run.preview_csv.sha256:
            raise ValueError("Existing preview differs from its recorded hash")
        return path
    data = (directory / run.extracted_page.path).read_bytes()
    if sha256(data).hexdigest() != run.extracted_page.sha256:
        raise ValueError("Saved page differs from its recorded hash")
    page = SourcePage.model_validate_json(data)
    preview = raw_preview_csv(page)
    path = directory / "preview_unreviewed.csv"
    if path.exists():
        if path.read_bytes() != preview:
            raise ValueError("Refusing to overwrite an existing different preview")
    else:
        path.write_bytes(preview)
    updated = ExtractionRun.model_validate({
        **run.model_dump(),
        "preview_csv": RunArtifact(path=path.name, sha256=sha256(preview).hexdigest()),
    })
    _save_manifest(directory, updated)
    return path


def _save_derived_artifacts(directory: Path, files: dict[str, bytes]) -> dict[str, RunArtifact]:
    """Preflight all paths, then save missing derived files without overwriting."""
    for name, content in files.items():
        path = directory / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Refusing to overwrite a different derived artifact: {name}")
    artifacts = {}
    for name, content in files.items():
        path = directory / name
        if not path.exists():
            path.write_bytes(content)
        artifacts[name] = RunArtifact(path=name, sha256=sha256(content).hexdigest())
    return artifacts


def add_resolution(directory: Path, rules_path: Path = DEFAULT_RULES) -> Path:
    """Resolve a successful run once, retaining source data and rules provenance."""
    run = load_run(directory)
    if run.status != "succeeded" or run.extracted_page is None:
        raise ValueError("Only a successful extracted page can be resolved")
    page_bytes = (directory / run.extracted_page.path).read_bytes()
    page_hash = sha256(page_bytes).hexdigest()
    if page_hash != run.extracted_page.sha256:
        raise ValueError("Saved page differs from its recorded hash")
    rules_bytes = Path(rules_path).read_bytes()
    rules_hash = sha256(rules_bytes).hexdigest()
    if run.resolution is not None:
        if (run.resolution.source_page_sha256 != page_hash
                or run.resolution.rules.sha256 != rules_hash):
            raise ValueError("Resolution already exists with different source/rules; preserve it as a revision before replacing")
        for artifact in (run.resolution.rules, run.resolution.rows, run.resolution.csv):
            if sha256((directory / artifact.path).read_bytes()).hexdigest() != artifact.sha256:
                raise ValueError(f"Resolution artifact differs from its recorded hash: {artifact.path}")
        return directory / run.resolution.csv.path
    rules = ResolverRules.model_validate_json(rules_bytes)
    page = SourcePage.model_validate_json(page_bytes)
    if page.document_id != run.document_id or page.page_number != run.page_number:
        raise ValueError("Saved page does not belong to this run")
    resolved = resolve_page(page, rules)
    files = {
        "resolver_rules.json": rules_bytes,
        "resolved_inherited.json": resolved.model_dump_json(indent=2).encode("utf-8"),
        "resolved_inherited.csv": resolved_inherited_csv(resolved),
    }
    artifacts = _save_derived_artifacts(directory, files)
    resolution = ResolutionArtifacts(
        resolved_at=datetime.now(timezone.utc), source_page_sha256=page_hash,
        rules=artifacts["resolver_rules.json"], rows=artifacts["resolved_inherited.json"],
        csv=artifacts["resolved_inherited.csv"])
    _save_manifest(directory, ExtractionRun.model_validate({**run.model_dump(), "resolution": resolution}))
    return directory / resolution.csv.path


def add_validation(directory: Path, rules_path: Path = DEFAULT_VALIDATOR_RULES) -> Path:
    """Persist deterministic risk with source, resolution, and rule hashes."""
    run = load_run(directory)
    if run.status != "succeeded" or run.extracted_page is None:
        raise ValueError("Only a successful extracted page can be validated")
    if run.resolution is None:
        add_resolution(directory)
        run = load_run(directory)
    page_bytes = (directory / run.extracted_page.path).read_bytes()
    page_hash = sha256(page_bytes).hexdigest()
    if page_hash != run.extracted_page.sha256 or page_hash != run.resolution.source_page_sha256:
        raise ValueError("Validation source differs from the recorded extraction/resolution")
    for artifact in (run.resolution.rules, run.resolution.rows, run.resolution.csv):
        if sha256((directory / artifact.path).read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError(f"Resolution artifact differs from its recorded hash: {artifact.path}")
    rules_bytes = Path(rules_path).read_bytes()
    rules_hash = sha256(rules_bytes).hexdigest()
    if run.validation is not None:
        if (run.validation.source_page_sha256 != page_hash
                or run.validation.resolution_rows_sha256 != run.resolution.rows.sha256
                or run.validation.rules.sha256 != rules_hash):
            raise ValueError("Validation already exists with different source/rules; preserve it as a revision before replacing")
        for artifact in (run.validation.rules, run.validation.rows, run.validation.csv):
            if sha256((directory / artifact.path).read_bytes()).hexdigest() != artifact.sha256:
                raise ValueError(f"Validation artifact differs from its recorded hash: {artifact.path}")
        return directory / run.validation.csv.path
    validated = validate_page(
        SourcePage.model_validate_json(page_bytes),
        ResolvedPage.model_validate_json((directory / run.resolution.rows.path).read_bytes()),
        ValidatorRules.model_validate_json(rules_bytes))
    artifacts = _save_derived_artifacts(directory, {
        "validation_rules.json": rules_bytes,
        "validated_risk.json": validated.model_dump_json(indent=2).encode("utf-8"),
        "validated_risk.csv": validated_risk_csv(validated),
    })
    validation = ValidationArtifacts(
        validated_at=datetime.now(timezone.utc), source_page_sha256=page_hash,
        resolution_rows_sha256=run.resolution.rows.sha256,
        rules=artifacts["validation_rules.json"], rows=artifacts["validated_risk.json"],
        csv=artifacts["validated_risk.csv"])
    _save_manifest(directory, ExtractionRun.model_validate({**run.model_dump(), "validation": validation}))
    return directory / validation.csv.path
