"""Validate/prepare a whole document, then extract its pages sequentially."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from extractor import ExtractionError, ExtractionResult, ROOT, extract_image
from ingestion import IngestedDocument, InputValidationError, ingest_bytes, ingest_file


class DocumentExtractionError(RuntimeError):
    def __init__(self, completed: list[ExtractionResult], failed_page: int,
                 total_pages: int, cause: ExtractionError):
        self.completed = completed
        self.failed_page = failed_page
        self.total_pages = total_pages
        self.run_dir = cause.run_dir
        super().__init__(f"Document incomplete: page {failed_page} of {total_pages} failed; "
                         f"{len(completed)} earlier page results were saved.\n{cause}")


def extract_file(
    path: Path, *, model: str | None = None, document_id: str | None = None,
    page_number: int = 1, dpi: int = 200, data_dir: Path | None = None,
    client: OpenAI | None = None,
) -> list[ExtractionResult]:
    """Accept one regular PDF/image. Invalid uploads make no model calls.

    A model failure stops processing and reports partial progress explicitly.
    All validated/rendered pages and the original remain available for retry.
    """
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        raise InputValidationError("Page number must be a positive integer")
    if Path(path).suffix.lower() == ".pdf" and page_number != 1:
        raise InputValidationError("PDF page numbers come from the document; omit --page-number")
    if document_id is not None and (not isinstance(document_id, str) or not document_id.strip()):
        raise InputValidationError("Document ID must be a non-empty string")
    load_dotenv(ROOT / ".env", override=False)
    data_dir = Path(data_dir) if data_dir is not None else Path(os.getenv("DATA_DIR") or ROOT / "data")
    document = ingest_file(path, data_dir=data_dir, dpi=dpi)
    return _extract_document(document, data_dir=data_dir, model=model, document_id=document_id,
                             page_number=page_number, client=client)


def extract_upload(content: bytes, filename: str, *, model: str | None = None,
                   data_dir: Path | None = None, client: OpenAI | None = None) -> list[ExtractionResult]:
    """Use the same bounded ingestion and page pipeline for browser uploads."""
    load_dotenv(ROOT / ".env", override=False)
    data_dir = Path(data_dir) if data_dir is not None else Path(os.getenv("DATA_DIR") or ROOT / "data")
    document = ingest_bytes(content, filename, data_dir=data_dir)
    return _extract_document(document, data_dir=data_dir, model=model, client=client)


def _extract_document(document: IngestedDocument, *, data_dir: Path, model: str | None = None,
                      document_id: str | None = None, page_number: int = 1,
                      client: OpenAI | None = None) -> list[ExtractionResult]:
    completed = []
    for page in document.pages:
        try:
            completed.append(extract_image(
                page.path.read_bytes(), document_id=document_id or document.document_id,
                page_number=page.page_number + page_number - 1, model=model,
                runs_dir=data_dir / "runs", client=client,
                source_metadata={
                    "original_path": document.original_path.relative_to(data_dir).as_posix(),
                    "original_sha256": document.document_id,
                    "prepared_path": page.path.relative_to(data_dir).as_posix(),
                    "page_number": page.page_number, "page_count": len(document.pages),
                    **page.metadata,
                },
            ))
        except ExtractionError as exc:
            raise DocumentExtractionError(completed, page.page_number, len(document.pages), exc) from exc
    return completed
