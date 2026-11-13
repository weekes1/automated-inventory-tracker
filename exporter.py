"""Raw inspection previews. Approved CSV/XLSX export is not implemented yet."""

import csv
from io import StringIO

from schemas import InventoryRow, OUTPUT_COLUMNS, SourcePage


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
            # Quoting CSV cells alone does not stop spreadsheet formula execution.
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            values.append(text)
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig")
