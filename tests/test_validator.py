"""Risk rule precedence, thresholds, and saved audit artifacts."""

import csv
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pydantic import ValidationError

from exporter import resolved_inherited_csv, validated_risk_csv
from resolver import resolve_page
from runs import add_resolution, add_validation, finish_run, load_run, start_run
from schemas import RunConfig, SourceField, SourcePage, SourceRow, ValidatedPage
from validator import DEFAULT_RULES, ValidatorRules, validate_page


VALUES = dict(quantity="2", price="19.99", description="Pipe", person_name="Alex",
              job_site="Depot", job_name="Refit", job_number="00123", date="2025-04-14")


def source_row(number=1, values=None, **marks):
    return SourceRow(
        row_id=f"row-{number}", row_number=number,
        marked=False, highlighted=False, crossed_out=False,
        fields={name: SourceField(raw_text=value, kind="text" if value else "blank")
                for name, value in (VALUES if values is None else values).items()},
    ).model_copy(update=marks)


class ValidatorTests(unittest.TestCase):
    def assess(self, rows, rules=None):
        source = SourcePage(document_id="doc", page_number=1, rows=rows)
        resolved = resolve_page(source)
        return validate_page(source, resolved, rules)

    def test_complete_unmarked_row_is_low_and_zero_is_present(self):
        for values in (VALUES, {**VALUES, "quantity": "0", "price": "0"}):
            result = self.assess([source_row(values=values)])
            self.assertEqual(result.rows[0].risk, "low")
            self.assertEqual(result.rows[0].risk_reason, "No configured risk rule matched")

    def test_missing_required_values_after_resolution_are_medium(self):
        for name, label in (("job_number", "Job #"), ("price", "Price"), ("quantity", "Quantity")):
            with self.subTest(name=name):
                result = self.assess([source_row(values={**VALUES, name: " "})])
                self.assertEqual(result.rows[0].risk, "medium")
                self.assertIn(f"Missing {label}", result.rows[0].risk_reason)
        # Missing Description alone is not a supplied risk rule.
        self.assertEqual(self.assess([source_row(values={**VALUES, "description": ""})]).rows[0].risk, "low")

    def test_any_single_critical_inherited_field_is_medium(self):
        for name, label in (("quantity", "Quantity"), ("price", "Price"), ("description", "Description")):
            with self.subTest(name=name):
                result = self.assess([source_row(), source_row(2, {**VALUES, name: ""})])
                self.assertEqual(result.rows[1].risk, "medium")
                self.assertIn(f"{label} was inherited", result.rows[1].risk_reason)

    def test_more_than_three_inherited_fields_threshold(self):
        for count in (3, 4):
            values = dict(VALUES)
            for name in ["person_name", "job_site", "job_name", "date"][:count]:
                values[name] = ""
            result = self.assess([source_row(), source_row(2, values)])
            self.assertEqual(result.rows[1].risk, "medium" if count == 4 else "low")
            if count == 4:
                self.assertIn("4 fields inherited (more than 3)", result.rows[1].risk_reason)

    def test_each_mark_and_cancelled_status_are_high(self):
        for flag in ("marked", "highlighted", "crossed_out", "cancellation"):
            with self.subTest(flag=flag):
                marks = {flag: "cancelled" if flag == "cancellation" else True}
                self.assertEqual(self.assess([source_row(**marks)]).rows[0].risk, "high")

    def test_high_takes_precedence_and_preserves_all_matching_reasons(self):
        result = self.assess([source_row(values={**VALUES, "price": "", "quantity": ""},
                                         highlighted=True, crossed_out=True)])
        row = result.rows[0]
        self.assertEqual(row.risk, "high")
        for text in ("crossed out", "highlighted", "Missing Price", "Missing Quantity"):
            self.assertIn(text, row.risk_reason)

    def test_inherited_job_number_is_present_and_unknown_marks_are_explicit(self):
        result = self.assess([source_row(), source_row(2, {**VALUES, "job_number": ""})])
        self.assertEqual(result.rows[1].risk, "low")
        legacy = source_row(marked=None, highlighted=None, crossed_out=None)
        result = self.assess([legacy])
        self.assertEqual(result.rows[0].risk, "low")
        self.assertIn("assessment is incomplete", result.rows[0].risk_reason)

    def test_parameters_are_configurable_and_invalid_config_is_rejected(self):
        rules = ValidatorRules.model_validate_json(DEFAULT_RULES.read_bytes())
        changed = rules.model_copy(update={"high_risk_flags": [], "inherited_fields_medium": [],
                                           "missing_fields_medium": [], "max_inherited_fields": 8})
        self.assertEqual(self.assess([source_row(values={}, highlighted=True)], changed).rows[0].risk, "low")
        for changes in ({"max_inherited_fields": -1}, {"missing_fields_medium": ["invented"]}):
            with self.assertRaises(ValidationError):
                ValidatorRules.model_validate({**rules.model_dump(), **changes})

    def test_csv_appends_adjacent_risk_and_reason_without_changing_values(self):
        source = SourcePage(document_id="doc", page_number=1, rows=[source_row(highlighted=True)])
        resolved = resolve_page(source)
        validated = validate_page(source, resolved)
        rows = list(csv.reader(StringIO(validated_risk_csv(validated).decode("utf-8-sig"))))
        original = list(csv.reader(StringIO(resolved_inherited_csv(resolved).decode("utf-8-sig"))))
        self.assertEqual(rows[0][-2:], ["risk", "risk_reason"])
        self.assertEqual(len(rows[0]), 18)
        self.assertEqual(rows[1][:16], original[1])
        self.assertEqual(rows[1][-2], "high")
        self.assertEqual(ValidatedPage.model_validate_json(validated.model_dump_json()), validated)
        wrong = resolved.model_copy(update={"document_id": "other"})
        with self.assertRaises(ValueError):
            validate_page(source, wrong)
        wrong_row = resolved.rows[0].model_copy(update={"source_row_id": "wrong-row"})
        with self.assertRaises(ValueError):
            validate_page(source, resolved.model_copy(update={"rows": [wrong_row]}))

    def test_saved_validation_is_hashed_idempotent_and_preserves_prior_stages(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            prompt, image, rules = root / "prompt.txt", root / "input.png", root / "rules.json"
            prompt.write_text("test")
            image.write_bytes(b"test")
            rules.write_text('{"version":"v001"}')
            directory = start_run(
                RunConfig(provider="test", model="test", prompt_version="v1", rules_version="v001", schema_version="v1"),
                document_id="doc", page_number=1, input_paths=[image], prompt_path=prompt,
                rules_path=rules, response_schema={}, runs_dir=root / "runs")
            source = SourcePage(document_id="doc", page_number=1, rows=[source_row(highlighted=True)])
            finish_run(directory, raw_response={}, page=source)
            add_resolution(directory)
            prior = {name: (directory / name).read_bytes() for name in
                     ("page.json", "raw_response.json", "resolved_inherited.csv", "resolved_inherited.json")}
            path = add_validation(directory)
            timestamp = path.stat().st_mtime_ns
            manifest = (directory / "manifest.json").read_bytes()
            self.assertEqual(add_validation(directory), path)
            self.assertEqual(path.stat().st_mtime_ns, timestamp)
            self.assertEqual((directory / "manifest.json").read_bytes(), manifest)
            self.assertEqual({name: (directory / name).read_bytes() for name in prior}, prior)
            self.assertIsNotNone(load_run(directory).validation)
            self.assertEqual(json.loads((directory / "validated_risk.json").read_text())["rows"][0]["risk"], "high")
            modified = root / "validator.json"
            modified.write_bytes(DEFAULT_RULES.read_bytes() + b"\n")
            with self.assertRaises(ValueError):
                add_validation(directory, modified)
            path.write_text("edited")
            with self.assertRaises(ValueError):
                add_validation(directory)


if __name__ == "__main__":
    unittest.main()
