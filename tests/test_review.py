"""Review/export boundaries and Streamlit state transitions, without live requests."""

import csv
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from pipeline import extract_upload
from ingestion import InputValidationError
from review import (approve_document, approved_download, editor_records, load_pages,
                    review_signature, saved_documents)
from runs import finish_run, start_run
from schemas import OUTPUT_COLUMNS, RunConfig, SourceField, SourcePage, SourceRow

ROOT = Path(__file__).resolve().parents[1]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        image = BytesIO()
        Image.new('RGB', (12, 12), 'white').save(image, format='PNG')
        self.image = image.getvalue()
        self.input = self.root / 'sheet.png'
        self.input.write_bytes(self.image)
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('test')
        self.rules = self.root / 'rules.json'
        self.rules.write_text('{"version":"test"}')
        self.directory = self.make_run()

    def make_run(self, number=1, count=1):
        directory = start_run(
            RunConfig(provider='test', model='test', prompt_version='test', rules_version='test',
                      schema_version='test', preprocessing={'source': {'page_count': count, 'original_name': 'Test Sheet.v2.png'}}),
            document_id='test-doc', page_number=number, input_paths=[self.input],
            prompt_path=self.prompt, rules_path=self.rules, response_schema={}, runs_dir=self.root / 'runs')
        rows = [SourceRow(row_id=f'row-{i}', row_number=i, highlighted=i == 1,
                          fields={'job_number': SourceField(raw_text='00123', kind='text'),
                                  'description': SourceField(raw_text='Pipe', kind='text')}) for i in (1, 2)]
        finish_run(directory, raw_response={}, page=SourcePage(document_id='test-doc', page_number=number, rows=rows))
        return directory

    def test_approved_csv_only_business_columns_edits_exclusions_and_safe_text(self):
        pages = load_pages([self.directory])
        before = (self.directory / 'page.json').read_bytes()
        rows = editor_records(pages)
        rows[0]['Description'] = '=HYPERLINK("x")'
        rows[0]['Quantity'] = '1 box'
        rows[1]['Exclude'] = True
        rows[1]['Exclusion reason'] = 'Cancelled on source'
        directory = approve_document(pages, rows, reviewer='Alex', confirmed=True, approved_dir=self.root / 'approved_outputs')
        signature = review_signature(pages, rows, 'Alex')
        filename, content = approved_download(directory, signature)
        self.assertEqual(filename, 'Test Sheet.v2_approved.csv')
        self.assertTrue(directory.name.endswith('_Test Sheet.v2'))
        self.assertEqual(content, (directory / filename).read_bytes())
        data = list(csv.reader(StringIO(content.decode('utf-8-sig'))))
        self.assertEqual(data[0], list(OUTPUT_COLUMNS))
        self.assertEqual(len(data), 2)
        self.assertEqual(data[1][0], '1 box')
        self.assertEqual(data[1][2], '\'=HYPERLINK("x")')
        self.assertEqual(data[1][6], '00123')
        snapshot = json.loads((directory / 'approval.json').read_text())
        self.assertEqual(snapshot['excluded_rows'], 1)
        self.assertEqual(len(snapshot['rows']), 2)
        self.assertEqual(snapshot['rows'][0]['risk'], 'high')
        self.assertEqual((self.directory / 'page.json').read_bytes(), before)
        rows[0]['Quantity'] = '2'
        with self.assertRaises(ValueError):
            approved_download(directory, review_signature(pages, rows, 'Alex'))
        (directory / filename).write_text('changed')
        with self.assertRaises(ValueError):
            approved_download(directory, signature)

    def test_requires_identity_confirmation_all_rows_and_exclusion_reasons(self):
        pages = load_pages([self.directory])
        rows = editor_records(pages)
        for reviewer, confirmed in (('', True), ('Alex', False)):
            with self.assertRaises(ValueError):
                approve_document(pages, rows, reviewer=reviewer, confirmed=confirmed, approved_dir=self.root / 'approved_outputs')
        for bad in (rows[:1], [rows[0], rows[0]], [{**rows[0], 'Exclude': True}, rows[1]]):
            with self.assertRaises(ValueError):
                approve_document(pages, bad, reviewer='Alex', confirmed=True, approved_dir=self.root / 'approved_outputs')
        self.assertFalse((self.root / 'approved_outputs').exists())

    def test_incomplete_pdf_blocked_complete_pdf_exports_in_page_order(self):
        first = self.make_run(1, 2)
        second = self.make_run(2, 2)
        pages = load_pages([first])
        with self.assertRaises(ValueError):
            approve_document(pages, editor_records(pages), reviewer='Alex', confirmed=True, approved_dir=self.root / 'approved_outputs')
        pages = load_pages([second, first])
        self.assertEqual([page.run.page_number for page in pages], [1, 2])
        directory = approve_document(pages, editor_records(pages), reviewer='Alex', confirmed=True, approved_dir=self.root / 'approved_outputs')
        self.assertEqual(json.loads((directory / 'approval.json').read_text())['included_rows'], 4)
        with self.assertRaises(ValueError):
            load_pages([first, first])

    def test_changed_source_artifact_blocks_approval(self):
        pages = load_pages([self.directory])
        (self.directory / 'page.json').write_text('{}')
        with self.assertRaises(ValueError):
            approve_document(pages, editor_records(pages), reviewer='Alex', confirmed=True, approved_dir=self.root / 'approved_outputs')

    def test_upload_uses_shared_ingestion_before_calling_model(self):
        with patch('pipeline.extract_image') as extract:
            with self.assertRaises(InputValidationError):
                extract_upload(b'invalid', 'sheet.png', data_dir=self.root)
            extract.assert_not_called()
            extract_upload(self.image, 'sheet.png', data_dir=self.root)
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(extract.call_args.kwargs['source_metadata']['page_count'], 1)
            self.assertEqual(extract.call_args.kwargs['source_metadata']['original_name'], 'sheet.png')
            self.assertTrue((self.root / extract.call_args.kwargs['source_metadata']['original_path']).is_file())

    def test_streamlit_saved_mode_approval_edit_invalidates_download_and_new_mode(self):
        with patch.dict(os.environ, {'DATA_DIR': str(self.root)}), patch('pipeline.extract_file') as extract:
            app = AppTest.from_file(str(ROOT / 'app.py')).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.dataframe[0].value.columns[-2:].tolist(), ['risk', 'risk_reason'])
            app.button[0].click().run()
            self.assertTrue(app.error)  # identity/acknowledgement required
            app.text_input[0].set_value('Alex').run()
            app.checkbox[0].check().run()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)
            self.assertIn('approval', app.session_state)
            # Submit the same delta sent by the editable table's browser widget.
            editor = 'editor_' + app.session_state['review_token']
            app.session_state[editor] = {'edited_rows': {0: {'Quantity': '42'}}, 'added_rows': [], 'deleted_rows': []}
            app.run()
            self.assertFalse(app.exception)
            self.assertNotIn('approval', app.session_state)
            app.sidebar.radio[0].set_value('New extraction').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio[0].value, 'Upload a file')
            app.radio[0].set_value('Choose a sample').run()
            self.assertFalse(app.exception)
            extract.assert_not_called()
            extract.return_value = [SimpleNamespace(run_dir=self.directory)]
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(len(app.dataframe[0].value), 2)
            app.run()
            self.assertEqual(extract.call_count, 1)
        docs, warnings = saved_documents(self.root)
        self.assertEqual(list(docs), ['test-doc'])
        self.assertEqual(warnings, [])


if __name__ == '__main__':
    unittest.main()
