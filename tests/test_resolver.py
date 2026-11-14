"""Deterministic column inheritance and its audit trail."""

import csv
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from exporter import resolved_inherited_csv
from resolver import DEFAULT_RULES, resolve_page
from runs import add_resolution, finish_run, load_run, start_run
from schemas import InventoryRow, SourceField, SourcePage, SourceRow


def row(number, **values):
    return SourceRow(row_id=f"row-{number}", row_number=number, fields={
        name: SourceField(raw_text=value, kind="text" if value else "blank")
        for name, value in values.items()
    })


class ResolverTests(unittest.TestCase):
    def page(self, rows, **changes):
        return SourcePage(document_id="doc", page_number=1, rows=rows, **changes)

    def test_downward_fill_all_columns_and_independent_replacement(self):
        initial = dict(quantity="2", price="19.99", description="Copper pipe", person_name="Alex",
                       job_site="Depot", job_name="Refit", job_number="00123", date="4-14-25")
        page = self.page([row(1, **initial), row(2), row(3, person_name="Sam", quantity="3"), row(4)])
        resolved = resolve_page(page)
        self.assertEqual(resolved.rows[0].inherited_fields, {})
        self.assertEqual(resolved.rows[1].values, initial)
        self.assertEqual(set(resolved.rows[1].inherited_fields), set(InventoryRow.model_fields))
        self.assertEqual(resolved.rows[3].values["person_name"], "Sam")
        self.assertEqual(resolved.rows[3].values["quantity"], "3")
        self.assertEqual(resolved.rows[3].inherited_fields["person_name"].row_number, 3)
        self.assertEqual(resolved.rows[3].inherited_fields["description"].row_number, 1)
        self.assertNotIn("person_name", resolved.rows[2].inherited_fields)
        self.assertEqual(page.rows[1].fields, {})

    def test_markers_are_detected_even_when_llm_labels_them_as_text(self):
        markers = ['"', "''", '“ ”', "〃", "↓", "↓ ↓", "⬇️", "⇓", "Ditto", "d/o"]
        resolved = resolve_page(self.page([row(1, description="Pipe"),
                                          *[row(n, description=mark) for n, mark in enumerate(markers, 2)]]))
        for result in resolved.rows[1:]:
            self.assertEqual(result.values["description"], "Pipe")
            self.assertEqual(result.inheritance_reasons["description"], "repetition_marker")
            self.assertEqual(result.inherited_fields["description"].row_number, 1)
        # Symbols inside actual text must not erase a new value.
        fresh = resolve_page(self.page([row(1, description="Pipe"), row(2, description='2" pipe')]))
        self.assertEqual(fresh.rows[1].values["description"], '2" pipe')
        self.assertNotIn("description", fresh.rows[1].inherited_fields)

    def test_invalid_dates_inherit_until_a_real_calendar_date(self):
        resolved = resolve_page(self.page([
            row(1, date="2025-01-31"), row(2, date="31/02/2025"),
            row(3, date="not a date"), row(4, date="14/04/2025"),
            row(5, date="↓"), row(6, date="4-15-25"), row(7),
        ]))
        self.assertEqual([r.values["date"] for r in resolved.rows],
                         ["2025-01-31", "2025-01-31", "2025-01-31", "14/04/2025",
                          "14/04/2025", "4-15-25", "4-15-25"])
        self.assertEqual(resolved.rows[1].inheritance_reasons["date"], "invalid_date")
        self.assertEqual(resolved.rows[4].inherited_fields["date"].row_number, 4)

    def test_leading_unknowns_stay_unresolved_and_pages_do_not_share_state(self):
        resolved = resolve_page(self.page([row(1, date="invalid"), row(2, date="↓")]))
        for result in resolved.rows:
            self.assertIsNone(result.values["date"])
            self.assertNotIn("date", result.inherited_fields)
            self.assertIn("date", result.unresolved_fields)
        resolve_page(self.page([row(1, person_name="Alex")]))
        self.assertIsNone(resolve_page(self.page([row(1)])).rows[0].values["person_name"])

    def test_header_context_and_cancelled_candidates_are_retained(self):
        cancelled = row(1, person_name="Sam").model_copy(update={"cancellation": "cancelled"})
        page = self.page([cancelled, row(2)], header_fields={
            "job_number": SourceField(raw_text="00123", kind="text")})
        result = resolve_page(page)
        self.assertEqual(len(result.rows), 2)
        self.assertIsNone(result.rows[0].inherited_fields["job_number"].row_number)
        self.assertEqual(result.rows[1].values["person_name"], "Sam")

    def test_csv_has_eight_value_flag_pairs_and_safe_text(self):
        page = resolve_page(self.page([row(1, description="=1+1", job_number="00123"), row(2)]))
        records = list(csv.DictReader(StringIO(resolved_inherited_csv(page).decode("utf-8-sig"))))
        self.assertEqual(len(records[0]), 16)
        self.assertEqual(list(records[0])[:4], ["Quantity", "Quantity_inherited", "Price", "Price_inherited"])
        self.assertEqual(records[0]["Description"], "'=1+1")
        self.assertEqual(records[0]["Description_inherited"], "false")
        self.assertEqual(records[1]["Description_inherited"], "true")
        self.assertEqual(records[1]["Job #"], "00123")
        self.assertEqual(page.rows[1].values["description"], "=1+1")

    def test_saved_resolution_is_auditable_and_idempotent(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt, image, rules = root / "prompt.txt", root / "input.png", root / "rules.json"
            prompt.write_text("test")
            image.write_bytes(b"test")
            rules.write_text('{"version":"v001"}')
            from schemas import RunConfig
            directory = start_run(
                RunConfig(provider="test", model="test", prompt_version="v1", rules_version="v001", schema_version="v1"),
                document_id="doc", page_number=1, input_paths=[image], prompt_path=prompt,
                rules_path=rules, response_schema={}, runs_dir=root / "runs")
            finish_run(directory, raw_response={}, page=self.page([row(1, date="2025-01-31"), row(2)]))
            original = (directory / "page.json").read_bytes()
            path = add_resolution(directory)
            timestamp = path.stat().st_mtime_ns
            manifest_before = (directory / "manifest.json").read_bytes()
            self.assertEqual(add_resolution(directory), path)
            self.assertEqual(path.stat().st_mtime_ns, timestamp)
            self.assertEqual((directory / "manifest.json").read_bytes(), manifest_before)
            self.assertEqual((directory / "page.json").read_bytes(), original)
            run = load_run(directory)
            self.assertIsNotNone(run.resolution)
            detail = json.loads((directory / "resolved_inherited.json").read_text())
            self.assertEqual(detail["rows"][1]["inherited_fields"]["date"]["row_number"], 1)
            modified = root / "modified_rules.json"
            modified.write_bytes(DEFAULT_RULES.read_bytes() + b"\n")
            with self.assertRaises(ValueError):
                add_resolution(directory, modified)
            path.write_text("edited")
            with self.assertRaises(ValueError):
                add_resolution(directory)


if __name__ == "__main__":
    unittest.main()
