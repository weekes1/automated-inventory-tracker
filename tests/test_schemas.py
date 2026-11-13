"""Contract tests for inventory data and output isolation."""

from datetime import date
from decimal import Decimal
import unittest

from pydantic import ValidationError

from schemas import AcceptanceLevel, InventoryRow, OUTPUT_COLUMNS, ProcessingRow


class InventorySchemaTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "Quantity": "2.5", "Price": "19.99", "Description": "Copper pipe",
            "Person name": "Alex Smith", "Job site": "North depot",
            "Job name": "Refit", "Job #": "00123", "Date": "2026-11-13",
        }

    def test_normalized_types_and_identifier_round_trip(self):
        row = InventoryRow.model_validate(self.values)
        self.assertEqual(row.quantity, Decimal("2.5"))
        self.assertEqual(row.price, Decimal("19.99"))
        self.assertEqual(row.date, date(2026, 11, 13))
        self.assertEqual(row.job_number, "00123")
        self.assertEqual(InventoryRow.model_validate_json(row.model_dump_json()), row)

    def test_processing_metadata_never_leaks_into_output_projection(self):
        row = ProcessingRow(**self.values, acceptance_level="level_2")
        expected = (
            "Quantity", "Price", "Description", "Person name",
            "Job site", "Job name", "Job #", "Date",
        )
        self.assertEqual(OUTPUT_COLUMNS, expected)
        self.assertEqual(tuple(row.to_output_dict()), expected)
        output = row.to_output_row()
        self.assertIs(type(output), InventoryRow)
        self.assertEqual(output.model_dump(by_alias=True), row.to_output_dict())
        self.assertNotIn("acceptance_level", output.model_dump())
        self.assertIn("acceptance_level", row.model_dump())

    def test_three_categories_and_unassigned_state(self):
        self.assertEqual(len(AcceptanceLevel), 3)
        self.assertIsNone(ProcessingRow().acceptance_level)
        for level in AcceptanceLevel:
            with self.subTest(level=level):
                self.assertEqual(ProcessingRow(acceptance_level=level).acceptance_level, level)
        with self.assertRaises(ValidationError):
            ProcessingRow(acceptance_level="invented_category")

    def test_missing_observations_remain_unknown(self):
        row = ProcessingRow(description="Unclear handwritten row")
        for value in (row.quantity, row.price, row.date, row.job_number):
            self.assertIsNone(value)
        self.assertEqual(len(row.to_output_dict()), 8)

    def test_unknown_fields_and_invalid_values_are_rejected(self):
        for extra in ({"currency": "GBP"}, {"acceptance_level": "level_1"}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                InventoryRow(**self.values, **extra)
        for field, value in (
            ("Quantity", "two?"), ("Quantity", "NaN"),
            ("Price", "Infinity"), ("Date", "13/11/26"), ("Job #", 123),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    InventoryRow.model_validate({**self.values, field: value})

    def test_python_field_names_and_immutable_rows(self):
        row = InventoryRow(job_number="00042", person_name="Alex")
        self.assertEqual(row.to_output_dict()["Job #"], "00042")
        with self.assertRaises(ValidationError):
            row.job_number = "42"


if __name__ == "__main__":
    unittest.main()
