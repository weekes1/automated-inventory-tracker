"""Deterministic downward inheritance; preserves text rather than normalizing it."""

import argparse
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from schemas import InventoryRow, ResolvedPage, ResolvedRow, SourceField, SourcePage, SourceReference


DEFAULT_RULES = Path(__file__).resolve().parent / "config/resolver_v001.json"


class ResolverRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    repetition_symbols: str
    repetition_words: list[str]
    date_formats: list[str] = Field(min_length=1)


def _is_date(text: str, rules: ResolverRules) -> bool:
    for format in rules.date_formats:
        try:
            datetime.strptime(text.strip(), format)
            return True
        except ValueError:
            continue
    return False


def _inheritance_reason(field: SourceField | None, name: str, rules: ResolverRules) -> str | None:
    text = field.raw_text if field is not None else None
    if text is None or not text.strip():
        return "blank"
    marker = "".join(text.split()).replace("\ufe0f", "")
    if (field.kind == "ditto" or marker.casefold() in {word.casefold() for word in rules.repetition_words}
            or all(char in rules.repetition_symbols for char in marker)):
        return "repetition_marker"
    if name == "date" and not _is_date(text, rules):
        return "invalid_date"
    return None


def resolve_page(page: SourcePage, rules: ResolverRules | None = None) -> ResolvedPage:
    """Carry each column independently, resetting at every page.

    Page-wide headers seed inheritance when usable. All candidate rows remain
    in order, including cancelled/uncertain rows; cancellation filtering is a
    separate future policy. References point to the original supplying cell.
    """
    rules = rules or ResolverRules.model_validate_json(DEFAULT_RULES.read_bytes())
    previous = {}
    for name, field in page.header_fields.items():
        if _inheritance_reason(field, name, rules) is None:
            previous[name] = (field.raw_text, SourceReference(
                document_id=page.document_id, page_number=page.page_number, field_name=name))
    rows = []
    for row in page.rows:
        values, inherited, reasons, unresolved = {}, {}, {}, {}
        for name in InventoryRow.model_fields:
            field = row.fields.get(name)
            reason = _inheritance_reason(field, name, rules)
            if reason is None:
                values[name] = field.raw_text
                previous[name] = (field.raw_text, SourceReference(
                    document_id=page.document_id, page_number=page.page_number,
                    row_number=row.row_number, field_name=name))
            elif name in previous:
                values[name], inherited[name] = previous[name]
                reasons[name] = reason
            else:
                values[name] = None
                unresolved[name] = f"{reason}: no preceding usable value"
        rows.append(ResolvedRow(
            source_row_id=row.row_id, row_number=row.row_number, values=values,
            inherited_fields=inherited, inheritance_reasons=reasons, unresolved_fields=unresolved))
    return ResolvedPage(document_id=page.document_id, page_number=page.page_number,
                        resolver_version=rules.version, rows=rows)


def main() -> None:
    from runs import add_resolution, load_run

    parser = argparse.ArgumentParser(description="Resolve saved extraction runs without model calls.")
    parser.add_argument("path", type=Path, help="A run directory or its parent runs directory")
    args = parser.parse_args()
    directories = ([args.path] if (args.path / "manifest.json").is_file()
                   else sorted(path.parent for path in args.path.glob("*/manifest.json")))
    if not directories:
        parser.error("No run manifests found")
    try:
        for directory in directories:
            if load_run(directory).status == "succeeded":
                print(add_resolution(directory))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Resolution failed: {exc}\n")


if __name__ == "__main__":
    main()
