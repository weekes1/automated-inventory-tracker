"""Load auditable page results and save explicit whole-document approvals."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from uuid import uuid4

from exporter import spreadsheet_text
from runs import add_validation, load_run
from schemas import ExtractionRun, InventoryRow, OUTPUT_COLUMNS, SourcePage, ValidatedPage


@dataclass
class ReviewPage:
    directory: Path
    run: ExtractionRun
    source: SourcePage
    validated: ValidatedPage
    image: bytes


def saved_documents(data_dir: Path) -> tuple[dict[str, list[Path]], list[str]]:
    """Group successful runs by document; leave the page attempt choice to the UI."""
    documents = {}
    warnings = []
    for manifest in sorted((data_dir / "runs").glob("*/manifest.json"), reverse=True):
        try:
            run = load_run(manifest.parent)
            if run.status == "succeeded":
                documents.setdefault(run.document_id, []).append(manifest.parent)
        except (ValueError, OSError):
            warnings.append(f"Could not read run {manifest.parent.name}")
    return documents, warnings


def artifact_bytes(directory: Path, artifact) -> bytes:
    path = (directory / artifact.path).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Artifact path is outside its run")
    content = path.read_bytes()
    if sha256(content).hexdigest() != artifact.sha256:
        raise ValueError(f"Saved artifact has changed: {artifact.path}")
    return content


def load_pages(directories: list[Path]) -> list[ReviewPage]:
    pages = []
    for directory in directories:
        add_validation(directory)
        run = load_run(directory)
        source = SourcePage.model_validate_json(artifact_bytes(directory, run.extracted_page))
        validated = ValidatedPage.model_validate_json(artifact_bytes(directory, run.validation.rows))
        image = artifact_bytes(directory, run.inputs[0])
        pages.append(ReviewPage(directory, run, source, validated, image))
    pages.sort(key=lambda page: page.run.page_number)
    if not pages or len({page.run.document_id for page in pages}) != 1:
        raise ValueError("Choose pages from one document")
    if len({page.run.page_number for page in pages}) != len(pages):
        raise ValueError("Choose exactly one extraction attempt per page")
    return pages


def expected_pages(pages: list[ReviewPage]) -> int:
    counts = {page.run.config.preprocessing.get("source", {}).get("page_count", 1) for page in pages}
    if len(counts) != 1:
        raise ValueError("Page counts disagree across the chosen runs")
    return counts.pop()


def check_complete(pages: list[ReviewPage]) -> None:
    if [page.run.page_number for page in pages] != list(range(1, expected_pages(pages) + 1)):
        raise ValueError("Every page must have a successful extraction before file approval")


def row_key(page: ReviewPage, row) -> str:
    return f"{page.run.run_id}:{row.source_row_id}"


def editor_records(pages: list[ReviewPage]) -> list[dict]:
    return [
        {"_row_id": row_key(page, row), "Page": page.run.page_number, "Row": row.row_number,
         "Exclude": False, "Exclusion reason": "",
         **{field.alias or name: row.values.get(name) or ""
            for name, field in InventoryRow.model_fields.items()},
         "risk": row.risk.value, "risk_reason": row.risk_reason}
        for page in pages for row in page.validated.rows
    ]


def checked_records(pages: list[ReviewPage], records: list[dict]) -> list[dict]:
    originals = {row["_row_id"]: row for row in editor_records(pages)}
    if len(records) != len(originals) or {row.get("_row_id") for row in records} != set(originals):
        raise ValueError("Review must account for every extracted row exactly once")
    checked = {}
    for row in records:
        if type(row.get("Exclude")) is not bool:
            raise ValueError("Each row needs an explicit exclusion choice")
        if any(not isinstance(row.get(header), str) for header in OUTPUT_COLUMNS):
            raise ValueError("Business cells must contain text; use an empty string for missing values")
        reason = row.get("Exclusion reason", "")
        if not isinstance(reason, str) or (row["Exclude"] and not reason.strip()):
            raise ValueError("Enter an exclusion reason for every excluded row")
        # Risk, page, and row identity always come from saved evidence, not editable input.
        checked[row["_row_id"]] = {**originals[row["_row_id"]],
                                  **{header: row[header] for header in OUTPUT_COLUMNS},
                                  "Exclude": row["Exclude"], "Exclusion reason": reason}
    return [checked[key] for key in originals]


def review_signature(pages: list[ReviewPage], records: list[dict], reviewer: str) -> str:
    data = {"runs": [page.run.model_dump(mode="json") for page in pages],
            "rows": records, "reviewer": reviewer.strip()}
    return sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def approve_document(pages: list[ReviewPage], records: list[dict], *, reviewer: str,
                     confirmed: bool, reviews_dir: Path) -> Path:
    """The export boundary requires explicit completeness and risk acknowledgement."""
    if not confirmed or not reviewer.strip():
        raise ValueError("Enter your name and confirm all pages, rows, and risk warnings were reviewed")
    check_complete(pages)
    # Recheck source dependencies immediately before approving a specific snapshot.
    fresh = load_pages([page.directory for page in pages])
    if [page.run.model_dump() for page in fresh] != [page.run.model_dump() for page in pages]:
        raise ValueError("Source results changed; reload and review them again")
    records = checked_records(pages, records)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(OUTPUT_COLUMNS)
    for row in records:
        if not row["Exclude"]:
            writer.writerow([spreadsheet_text(row[header]) for header in OUTPUT_COLUMNS])
    csv_bytes = output.getvalue().encode("utf-8-sig")
    now = datetime.now(timezone.utc)
    directory = reviews_dir / (now.strftime("%Y-%m-%d_%H-%M-%S.%fZ_") + str(uuid4()))
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = {
        "approved_at": now.isoformat(), "reviewer": reviewer.strip(),
        "identity": "self-asserted local reviewer name", "document_id": pages[0].run.document_id,
        "confirmed_all_pages_rows_and_risks": True,
        "signature": review_signature(pages, records, reviewer),
        "sources": [{"run_directory": page.directory.name, "manifest": page.run.model_dump(mode="json")}
                    for page in pages],
        "rows": records, "csv_sha256": sha256(csv_bytes).hexdigest(),
        "included_rows": sum(not row["Exclude"] for row in records),
        "excluded_rows": sum(row["Exclude"] for row in records),
    }
    (directory / "approved.csv").write_bytes(csv_bytes)
    # Write the approval last; an interrupted CSV write alone never grants approval.
    (directory / "approval.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return directory


def approved_download(directory: Path, signature: str) -> bytes:
    approval = json.loads((directory / "approval.json").read_text())
    content = (directory / "approved.csv").read_bytes()
    if approval["signature"] != signature or sha256(content).hexdigest() != approval["csv_sha256"]:
        raise ValueError("Approval does not match this review or the saved CSV")
    return content
