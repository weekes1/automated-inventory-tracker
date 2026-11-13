"""Evidence round trips and provenance/output boundary contracts."""

import unittest

from pydantic import ValidationError

from schemas import ProcessingRow, SourceField, SourcePage, SourceReference, SourceRow


class SourceSchemaTests(unittest.TestCase):
    def test_visual_marks_are_separate_from_cancellation(self):
        row = SourceRow(row_id="a", row_number=1, highlighted=True,
                        crossed_out=True, cancellation="active",
                        notes=["Yellow highlight; only the price is struck through."])
        restored = SourceRow.model_validate_json(row.model_dump_json())
        self.assertTrue(restored.highlighted)
        self.assertTrue(restored.crossed_out)
        self.assertEqual(restored.cancellation, "active")
        legacy = SourceRow(row_id="old", row_number=1)
        self.assertIsNone(legacy.highlighted)
        self.assertIsNone(legacy.crossed_out)

    def test_blank_continuation_is_an_uncertain_inference_not_a_mark(self):
        field = SourceField(raw_text="", kind="blank", inference="blank_as_ditto",
                            uncertain=True, notes=["Blank below a populated person within the same visible group."])
        self.assertEqual(field.raw_text, "")
        self.assertEqual(field.kind, "blank")
        self.assertIsNone(field.inherited_from)
        self.assertEqual(SourceField.model_validate_json(field.model_dump_json()), field)
        for changes in ({"raw_text": '"'}, {"kind": "ditto"},
                        {"uncertain": False}, {"notes": []}, {"notes": [" "]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SourceField.model_validate({**field.model_dump(), **changes})
        mark = SourceField(raw_text='"', kind="ditto")
        self.assertIsNone(mark.inference)

    def reference(self, **changes):
        return SourceReference.model_validate({
            "document_id": "sheet-1", "page_number": 1,
            "row_number": 1, "field_name": "description", **changes,
        })

    def test_page_round_trip_preserves_cautious_observations(self):
        page = SourcePage(
            document_id="sheet-1", page_number=1,
            header_fields={"job_number": SourceField(raw_text="00123", kind="text")},
            rows=[
                SourceRow(row_id="row-1", row_number=1, fields={
                    "description": SourceField(raw_text="Pipe", kind="text"),
                }),
                SourceRow(row_id="row-2", row_number=2, cancellation="uncertain",
                          notes=["Line crosses quantity; cancellation is unclear."],
                          fields={
                              "description": SourceField(
                                  raw_text='"', kind="ditto", inherited_from=self.reference()),
                              "quantity": SourceField(
                                  raw_text="2?", kind="text", uncertain=True,
                                  notes=["Last digit overlaps a strike-through."]),
                              "price": SourceField(raw_text=None, kind="illegible", uncertain=True),
                              "person_name": SourceField(raw_text="", kind="blank"),
                          }),
                SourceRow(row_id="row-3", row_number=3, cancellation="cancelled"),
            ],
            layout_notes=["Job number is in the header; columns have no grid."],
            notes=["Right edge of the photo is cropped."],
        )
        restored = SourcePage.model_validate_json(page.model_dump_json())
        self.assertEqual(restored, page)
        self.assertEqual(len(restored.rows), 3)
        self.assertEqual(restored.rows[1].cancellation, "uncertain")
        self.assertEqual(restored.rows[1].fields["description"].raw_text, '"')
        self.assertNotIn("job_number", restored.rows[1].fields)

    def test_verified_inheritance_remains_internal(self):
        row = ProcessingRow(
            description="Pipe", source_row_id="row-2", acceptance_level="low",
            inherited_fields={"description": self.reference()},
        )
        self.assertEqual(row.inherited_fields["description"].row_number, 1)
        self.assertEqual(row.to_output_dict(), row.to_output_row().model_dump(by_alias=True))
        self.assertEqual(len(row.to_output_dict()), 8)
        self.assertNotIn("source_row_id", row.to_output_dict())
        self.assertNotIn("inherited_fields", row.to_output_dict())
        header = self.reference(row_number=None, field_name="job_number")
        self.assertIsNone(header.row_number)

    def test_unknown_canonical_fields_are_rejected(self):
        field = SourceField(raw_text="Pipe", kind="text")
        with self.assertRaises(ValidationError):
            SourceRow(row_id="row-1", row_number=1, fields={"invented": field})
        with self.assertRaises(ValidationError):
            SourcePage(document_id="sheet-1", page_number=1, header_fields={"invented": field})
        with self.assertRaises(ValidationError):
            self.reference(field_name="invented")
        with self.assertRaises(ValidationError):
            ProcessingRow(inherited_fields={"invented": self.reference()})

    def test_invalid_positions_duplicate_rows_and_states_are_rejected(self):
        for number in (0, -1, True):
            with self.subTest(number=number), self.assertRaises(ValidationError):
                self.reference(page_number=number)
        for rows in (
            [SourceRow(row_id="same", row_number=1), SourceRow(row_id="same", row_number=2)],
            [SourceRow(row_id="a", row_number=1), SourceRow(row_id="b", row_number=1)],
            [SourceRow(row_id="a", row_number=2), SourceRow(row_id="b", row_number=1)],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                SourcePage(document_id="sheet-1", page_number=1, rows=rows)
        with self.assertRaises(ValidationError):
            SourceRow(row_id="row-1", row_number=1, cancellation="discarded")
        with self.assertRaises(ValidationError):
            SourceField(raw_text="Pipe", kind="guessed")


if __name__ == "__main__":
    unittest.main()
