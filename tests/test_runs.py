"""Run snapshots, audit lifecycle, and result association."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pydantic import ValidationError

from runs import finish_run, load_run, start_run
from schemas import ExtractionRun, RunConfig, SourcePage


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.image = self.root / "sheet.png"
        self.image.write_bytes(b"test input bytes; no real document")
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Transcribe visible marks.", encoding="utf-8")
        self.rules = self.root / "rules.json"
        self.rules.write_text('{"version":"v001","required_fields":[]}', encoding="utf-8")
        self.config = RunConfig(
            provider="test-provider", model="requested-model",
            prompt_version="v002", rules_version="v001", schema_version="v001",
            model_settings={"temperature": 0, "image_detail": "high"},
            preprocessing={"rotation": 0}, code_version="test-build",
        )

    def start(self, **changes):
        return start_run(**{
            "config": self.config, "document_id": "doc-1", "page_number": 1,
            "input_paths": [self.image], "prompt_path": self.prompt,
            "rules_path": self.rules, "response_schema": {"type": "object"},
            "runs_dir": self.root / "runs", **changes,
        })

    def test_configuration_and_inputs_survive_source_changes(self):
        directory = self.start()
        before = load_run(directory)
        self.prompt.write_text("Changed under the same version label.", encoding="utf-8")
        self.image.write_bytes(b"changed input")
        self.config.model_settings["temperature"] = 1
        restored = load_run(directory)
        self.assertEqual(restored, before)
        self.assertEqual(restored.config.model_settings["temperature"], 0)
        self.assertEqual((directory / restored.prompt.path).read_text(), "Transcribe visible marks.")
        self.assertEqual(restored.config.prompt_version, "v002")
        self.assertEqual(restored.config.schema_version, "v001")
        self.assertEqual(restored.config.code_version, "test-build")
        for artifact in [*restored.inputs, restored.prompt, restored.rules, restored.response_schema]:
            self.assertEqual(sha256((directory / artifact.path).read_bytes()).hexdigest(), artifact.sha256)
        later = load_run(self.start())
        self.assertNotEqual(later.run_id, restored.run_id)
        self.assertNotEqual(later.prompt.sha256, restored.prompt.sha256)
        self.assertEqual(later.config.prompt_version, restored.config.prompt_version)

    def test_success_links_raw_response_page_and_returned_model(self):
        directory = self.start()
        page = SourcePage(document_id="doc-1", page_number=1)
        response = {"output": "raw provider text", "model": "model-snapshot"}
        run = finish_run(
            directory, raw_response=response, page=page,
            returned_model="model-snapshot", provider_request_id="req-123",
            usage={"input_tokens": 10, "output_tokens": 20},
        )
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.config.model, "requested-model")
        self.assertEqual(run.returned_model, "model-snapshot")
        self.assertEqual(run.provider_request_id, "req-123")
        self.assertEqual(run.usage["input_tokens"], 10)
        self.assertEqual(load_run(directory), run)
        self.assertIsNotNone(run.started_at.tzinfo)
        self.assertGreaterEqual(run.finished_at, run.started_at)
        self.assertEqual(json.loads((directory / run.raw_response.path).read_text()), response)
        self.assertEqual(SourcePage.model_validate_json((directory / run.extracted_page.path).read_text()), page)
        for artifact in (run.raw_response, run.extracted_page):
            self.assertEqual(sha256((directory / artifact.path).read_bytes()).hexdigest(), artifact.sha256)
        with self.assertRaises(ValueError):
            finish_run(directory, error="must not overwrite")
        self.assertEqual(load_run(directory), run)

    def test_failures_keep_available_response_or_record_timeout(self):
        for response, message in (({"text": "not valid extraction JSON"}, "schema validation failed"),
                                  (None, "provider timed out")):
            with self.subTest(message=message):
                run = finish_run(self.start(), raw_response=response, error=message)
                self.assertEqual(run.status, "failed")
                self.assertEqual(run.error, message)
                self.assertIsNone(run.extracted_page)
                self.assertEqual(run.raw_response is None, response is None)

    def test_reject_wrong_page_or_false_success_without_finalizing(self):
        directory = self.start()
        with self.assertRaises(ValueError):
            finish_run(directory, raw_response={}, page=SourcePage(document_id="other", page_number=1))
        with self.assertRaises(ValueError):
            finish_run(directory, raw_response={})
        with self.assertRaises(ValueError):
            finish_run(directory, error=" ")
        self.assertEqual(load_run(directory).status, "running")

    def test_input_and_rules_version_are_required(self):
        with self.assertRaises(ValueError):
            self.start(input_paths=[])
        self.rules.write_text('{"version":"v999"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.start()

    def test_manifest_rejects_inconsistent_outcomes_and_naive_times(self):
        run = load_run(self.start())
        for changes in (
            {"status": "succeeded"},
            {"status": "failed", "finished_at": run.started_at},
            {"started_at": "2026-11-13T12:00:00"},
            {"status": "running", "error": "failed"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ExtractionRun.model_validate({**run.model_dump(), **changes})


if __name__ == "__main__":
    unittest.main()
