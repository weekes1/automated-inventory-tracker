"""Real SDK requests against a local mock transport; no live model calls."""

import base64
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx2
from openai import OpenAI
from PIL import Image

from extractor import ExtractionError, extract_image, extraction_response_schema
from runs import finish_run, load_run
from schemas import InventoryRow, SourcePage


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.requests = []
        self.http_status = 200
        self.response_status = "completed"
        self.refusal = False
        self.output_text = json.dumps({
            "header_fields": dict.fromkeys(InventoryRow.model_fields),
            "rows": [{
                "row_number": 1, "cancellation": "uncertain", "uncertain": True,
                "notes": ["Strike-through is ambiguous."],
                "fields": {**dict.fromkeys(InventoryRow.model_fields),
                           "quantity": {"raw_text": "1 box", "kind": "text", "uncertain": False,
                                        "inherited_from": None, "notes": []}},
            }], "layout_notes": ["Columns differ from previous sheet."], "notes": [],
        })
        transport = httpx2.MockTransport(self.handle_request)
        self.client = OpenAI(api_key="test-only", base_url="https://example.test/v1",
                             http_client=httpx2.Client(transport=transport))
        self.addCleanup(self.client.close)
        stream = BytesIO()
        Image.new("RGB", (8, 8), "white").save(stream, format="PNG")
        self.image = stream.getvalue()

    def handle_request(self, request):
        self.requests.append(json.loads(request.content))
        if self.http_status != 200:
            return httpx2.Response(self.http_status, json={"error": {"message": "test request failure"}},
                                   headers={"x-request-id": "req-error"})
        content = ({"type": "refusal", "refusal": "test refusal"} if self.refusal else
                   {"type": "output_text", "text": self.output_text, "annotations": []})
        return httpx2.Response(200, headers={"x-request-id": "req-test"}, json={
            "id": "resp-test", "created_at": 1, "model": "returned-snapshot",
            "object": "response", "status": self.response_status,
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": [{"type": "message", "id": "msg-test", "role": "assistant",
                        "status": "completed", "content": [content]}],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
                      "input_tokens_details": {"cached_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })

    def extract(self, **changes):
        return extract_image(**{
            "image_bytes": self.image, "document_id": "doc-test", "page_number": 3,
            "model": "gpt-5.4-mini", "runs_dir": self.root / "runs",
            "client": self.client, **changes,
        })

    def test_request_and_results_use_one_run_and_one_finalization(self):
        with patch("extractor.finish_run", wraps=finish_run) as save:
            result = self.extract()
        self.assertEqual(save.call_count, 1)
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request["model"], "gpt-5.4-mini")
        self.assertFalse(request["store"])
        image = request["input"][0]["content"][1]
        self.assertEqual(image["detail"], "high")
        self.assertEqual(base64.b64decode(image["image_url"].split(",", 1)[1]), self.image)
        run = load_run(result.run_dir)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.returned_model, "returned-snapshot")
        self.assertEqual(run.provider_request_id, "req-test")
        self.assertEqual(run.usage["total_tokens"], 30)
        self.assertEqual(request["input"][0]["content"][0]["text"],
                         (result.run_dir / run.prompt.path).read_text())
        self.assertEqual(request["text"]["format"]["schema"],
                         json.loads((result.run_dir / run.response_schema.path).read_text()))
        self.assertEqual(result.page.page_number, 3)
        self.assertEqual(result.page.document_id, "doc-test")
        self.assertEqual(result.page.rows[0].fields["quantity"].raw_text, "1 box")
        self.assertNotIn("price", result.page.rows[0].fields)
        self.assertTrue(result.page.rows[0].row_id.startswith(run.run_id))
        self.assertEqual(SourcePage.model_validate_json((result.run_dir / "page.json").read_text()), result.page)
        self.assertEqual(len(list(result.run_dir.glob("raw_response*.json"))), 1)
        self.assertEqual(len(list(result.run_dir.glob("page*.json"))), 1)

    def test_failures_save_raw_response_once(self):
        for case in ("invalid-json", "refusal", "incomplete", "invalid-page"):
            with self.subTest(case=case):
                self.refusal = case == "refusal"
                self.response_status = "incomplete" if case == "incomplete" else "completed"
                self.output_text = "not JSON" if case == "invalid-json" else "{}"
                with patch("extractor.finish_run", wraps=finish_run) as save:
                    with self.assertRaises(ExtractionError) as raised:
                        self.extract()
                self.assertEqual(save.call_count, 1)
                run = load_run(raised.exception.run_dir)
                self.assertEqual(run.status, "failed")
                self.assertIsNotNone(run.raw_response)
                self.assertIsNone(run.extracted_page)
                self.assertEqual(run.provider_request_id, "req-test")
                self.assertFalse((raised.exception.run_dir / "page.json").exists())

    def test_http_failure_is_not_automatically_retried(self):
        self.http_status = 429
        with self.assertRaises(ExtractionError) as raised:
            self.extract()
        self.assertEqual(len(self.requests), 1)
        run = load_run(raised.exception.run_dir)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.provider_request_id, "req-error")
        self.assertEqual(json.loads((raised.exception.run_dir / "raw_response.json").read_text())["status_code"], 429)

    def test_repeated_calls_are_separate_explicit_runs(self):
        first = self.extract()
        second = self.extract()
        self.assertNotEqual(first.run_dir, second.run_dir)
        self.assertEqual(len(self.requests), 2)

    def test_invalid_input_is_rejected_before_call_or_run(self):
        with self.assertRaises(ValueError):
            self.extract(page_number=0)
        with self.assertRaises(OSError):
            self.extract(image_bytes=b"not an image")
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root / "runs").exists())

    def test_schema_has_only_supported_fixed_key_objects(self):
        schema = extraction_response_schema()
        self.assertNotIn("document_id", schema["properties"])
        self.assertNotIn("row_id", schema["$defs"]["SourceRow"]["properties"])
        self.assertEqual(tuple(schema["properties"]["header_fields"]["properties"]),
                         tuple(InventoryRow.model_fields))

        def check(node):
            if isinstance(node, dict):
                self.assertNotIn("default", node)
                if node.get("type") == "object":
                    self.assertIs(node["additionalProperties"], False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)

        check(schema)


if __name__ == "__main__":
    unittest.main()
