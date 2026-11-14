"""Raw inspection previews. Approved CSV/XLSX export is not implemented yet."""

import csv
from io import StringIO

from schemas import InventoryRow, OUTPUT_COLUMNS, ResolvedPage, ResolvedRow, SourcePage, ValidatedPage


def spreadsheet_text(text: str) -> str:
    """Keep untrusted text literal when a CSV is opened in a spreadsheet."""
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def raw_preview_csv(page: SourcePage) -> bytes:
    """Render literal row observations, including uncertain/cancelled candidates.

    No inheritance, header propagation, filtering, or approval is applied.
    Missing/illegible values display as empty cells; page.json retains details.
    """
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(OUTPUT_COLUMNS)
    for row in page.rows:
        values = []
        for name in InventoryRow.model_fields:
            field = row.fields.get(name)
            text = field.raw_text if field is not None and field.raw_text is not None else ""
            values.append(spreadsheet_text(text))
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig")


def _resolved_headers() -> list[str]:
    return [column for header in OUTPUT_COLUMNS for column in (header, f"{header}_inherited")]


def _resolved_cells(row: ResolvedRow) -> list[str]:
    return [cell for name in InventoryRow.model_fields for cell in (
        spreadsheet_text(row.values.get(name) or ""), "true" if name in row.inherited_fields else "false")]


def resolved_inherited_csv(page: ResolvedPage) -> bytes:
    """Eight value columns paired with eight explicit inheritance flags."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(_resolved_headers())
    for row in page.rows:
        writer.writerow(_resolved_cells(row))
    return output.getvalue().encode("utf-8-sig")


def validated_risk_csv(page: ValidatedPage) -> bytes:
    """Keep risk and its explanation adjacent after the value/inheritance pairs."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(_resolved_headers() + ["risk", "risk_reason"])
    for row in page.rows:
        writer.writerow(_resolved_cells(row) + [row.risk.value, spreadsheet_text(row.risk_reason)])
    return output.getvalue().encode("utf-8-sig")
