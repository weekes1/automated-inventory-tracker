"""Raw previews retain candidate rows and the fixed eight-column contract."""

import csv
from io import StringIO
import unittest

from exporter import raw_preview_csv
from schemas import OUTPUT_COLUMNS, SourceField, SourcePage, SourceRow


class PreviewTests(unittest.TestCase):
    def test_raw_values_and_all_candidates_without_inheritance(self):
        page = SourcePage(
            document_id="doc", page_number=1,
            header_fields={"job_number": SourceField(raw_text="00099", kind="text")},
            rows=[
                SourceRow(row_id="a", row_number=1, fields={
                    "quantity": SourceField(raw_text="1 box", kind="text"),
                    "description": SourceField(raw_text='Pipe, 2"\nCopper', kind="text"),
                    "job_number": SourceField(raw_text="00123", kind="text"),
                }),
                SourceRow(row_id="b", row_number=2, cancellation="cancelled", fields={
                    "description": SourceField(raw_text='"', kind="ditto"),
                    "price": SourceField(raw_text=None, kind="illegible", uncertain=True),
                }),
                SourceRow(row_id="c", row_number=3, uncertain=True),
            ],
        )
        rows = list(csv.reader(StringIO(raw_preview_csv(page).decode("utf-8-sig"))))
        self.assertEqual(tuple(rows[0]), OUTPUT_COLUMNS)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1][0], "1 box")
        self.assertEqual(rows[1][2], 'Pipe, 2"\nCopper')
        self.assertEqual(rows[1][6], "00123")
        self.assertEqual(rows[2][2], '"')
        self.assertEqual(rows[2][6], "")
        self.assertEqual(rows[3], [""] * 8)

    def test_formula_like_text_is_escaped_without_changing_source(self):
        for text in ("=1+1", " +1", "-1", "@SUM(A1)", "\tvalue", "\nvalue"):
            with self.subTest(text=text):
                field = SourceField(raw_text=text, kind="text")
                page = SourcePage(document_id="doc", page_number=1, rows=[
                    SourceRow(row_id="a", row_number=1, fields={"description": field}),
                ])
                rows = list(csv.reader(StringIO(raw_preview_csv(page).decode("utf-8-sig"))))
                self.assertEqual(rows[1][2], "'" + text)
                self.assertEqual(field.raw_text, text)


if __name__ == "__main__":
    unittest.main()
