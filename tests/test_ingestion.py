"""Real parsers/rendering with synthetic fixtures and bounded-input checks."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
import pymupdf

from ingestion import DEFAULT_LIMITS, InputValidationError, ingest_bytes, ingest_file


def sample_pdf(pages=2, *, marked=False, encrypted=False, script=False, attached=False):
    with pymupdf.open() as doc:
        for number in range(pages):
            page = doc.new_page(width=240, height=160)
            page.insert_text((15, 30), f"Inventory page {number + 1}")
            page.insert_text((15, 65), "QTY  DESCRIPTION    PRICE")
            page.insert_text((15, 90), "2     Copper pipe     19.99")
            if marked:
                page.add_highlight_annot(pymupdf.Rect(10, 75, 190, 95)).update()
                page.add_strikeout_annot(pymupdf.Rect(10, 105, 190, 125)).update()
                page.set_rotation(90)
        if script:
            xref = doc.get_new_xref()
            doc.update_object(xref, "<< /S /JavaScript /JS (app.alert('test')) >>")
            doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
        if attached:
            doc.embfile_add("attachment.txt", b"test attachment")
        if encrypted:
            return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
        return doc.tobytes()


class IngestionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data_dir = self.root / "data"
        output = BytesIO()
        Image.new("RGB", (12, 8), "white").save(output, "PNG")
        self.png = output.getvalue()

    def ingest(self, content, filename, **options):
        return ingest_bytes(content, filename, data_dir=self.data_dir, **options)

    def test_pdf_pages_render_in_order_with_original_and_annotations(self):
        original = sample_pdf(marked=True)
        document = self.ingest(original, "sheet.pdf", dpi=72)
        self.assertEqual(document.original_path.read_bytes(), original)
        self.assertEqual([page.page_number for page in document.pages], [1, 2])
        self.assertEqual(len(list(self.data_dir.rglob("original.pdf"))), 1)
        for page in document.pages:
            with Image.open(page.path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (160, 240))
                self.assertEqual(image.mode, "RGB")
                self.assertTrue(any(r != g or g != b for r, g, b in image.get_flattened_data()))
            self.assertTrue(page.metadata["annotations"])
            self.assertEqual(page.metadata["rotation"], 90)
        before = document.pages[0].path.stat().st_mtime_ns
        again = self.ingest(original, "sheet.pdf", dpi=72)
        self.assertEqual(again.document_id, document.document_id)
        self.assertEqual(again.pages[0].path.stat().st_mtime_ns, before)

    def test_images_reencode_without_metadata_or_appended_payload(self):
        from PIL.PngImagePlugin import PngInfo
        metadata = PngInfo()
        metadata.add_text("comment", "untrusted metadata")
        output = BytesIO()
        Image.new("RGBA", (12, 8), (0, 0, 0, 0)).save(output, "PNG", pnginfo=metadata)
        original = output.getvalue() + b"<script>not an image pixel</script>"
        document = self.ingest(original, "sheet.png")
        self.assertEqual(document.original_path.read_bytes(), original)
        with Image.open(document.pages[0].path) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            self.assertNotIn("comment", image.info)
        self.assertNotIn(b"<script>", document.pages[0].path.read_bytes())

    def test_exif_orientation_is_applied_before_metadata_is_removed(self):
        output = BytesIO()
        image = Image.new("RGB", (12, 8), "white")
        exif = image.getexif()
        exif[274] = 6
        image.save(output, "JPEG", exif=exif)
        document = self.ingest(output.getvalue(), "sheet.jpeg")
        with Image.open(document.pages[0].path) as normalized:
            self.assertEqual(normalized.size, (8, 12))
            self.assertIsNone(normalized.getexif().get(274))

    def test_reject_bad_types_names_and_mismatched_content_before_saving(self):
        for content, name in (
            (b"", "sheet.png"), (b"MZfake executable", "sheet.png"),
            (b"<svg></svg>", "sheet.svg"), (b"%PDF-broken", "sheet.pdf"),
            (self.png[:40], "sheet.png"), (self.png, "sheet.pdf"),
            (sample_pdf(), "sheet.png"), (self.png, "sheet.exe"),
            (self.png, "../../sheet.png"), (self.png, "a\\sheet.png"),
            (self.png, "sheet\x00.png"),
        ):
            with self.subTest(name=name, size=len(content)), self.assertRaises(InputValidationError):
                self.ingest(content, name)
        self.assertFalse(self.data_dir.exists())

    def test_reject_animated_images(self):
        output = BytesIO()
        Image.new("RGB", (12, 8), "white").save(
            output, "GIF", save_all=True, append_images=[Image.new("RGB", (12, 8), "black")])
        with self.assertRaises(InputValidationError):
            self.ingest(output.getvalue(), "sheet.gif")

    def test_reject_encryption_scripts_and_attachments(self):
        for options in ({"encrypted": True}, {"script": True}, {"attached": True}):
            with self.subTest(options=options), self.assertRaises(InputValidationError):
                self.ingest(sample_pdf(**options), "sheet.pdf")
        self.assertFalse(self.data_dir.exists())

    def test_byte_pixel_and_page_limits_reject_before_render(self):
        with self.assertRaises(InputValidationError):
            self.ingest(self.png, "sheet.png", limits=replace(DEFAULT_LIMITS, max_bytes=1))
        with self.assertRaises(InputValidationError):
            self.ingest(self.png, "sheet.png", limits=replace(DEFAULT_LIMITS, max_page_pixels=10))
        pdf = sample_pdf()
        for limits in (replace(DEFAULT_LIMITS, max_pages=1),
                       replace(DEFAULT_LIMITS, max_page_pixels=1),
                       replace(DEFAULT_LIMITS, max_total_pixels=40_000),
                       replace(DEFAULT_LIMITS, max_pdf_objects=1)):
            with self.subTest(limits=limits), patch("pymupdf.Page.get_pixmap") as render:
                with self.assertRaises(InputValidationError):
                    self.ingest(pdf, "sheet.pdf", dpi=72, limits=limits)
                render.assert_not_called()
        self.assertFalse(self.data_dir.exists())

    def test_rendered_output_limit_and_invalid_dpi(self):
        with self.assertRaises(InputValidationError):
            self.ingest(sample_pdf(), "sheet.pdf", limits=replace(DEFAULT_LIMITS, max_total_png_bytes=1))
        with self.assertRaises(InputValidationError):
            self.ingest(self.png, "sheet.png", limits=replace(DEFAULT_LIMITS, max_total_png_bytes=1))
        for dpi in (0, 301, True):
            with self.subTest(dpi=dpi), self.assertRaises(InputValidationError):
                self.ingest(self.png, "sheet.png", dpi=dpi)
        self.assertFalse(self.data_dir.exists())

    def test_only_regular_local_files_are_read(self):
        path = self.root / "sheet.png"
        path.write_bytes(self.png)
        link = self.root / "link.png"
        link.symlink_to(path)
        for bad in (self.root, link, self.root / "missing.png"):
            with self.subTest(path=bad), self.assertRaises(InputValidationError):
                ingest_file(bad, data_dir=self.data_dir)
        self.assertEqual(len(ingest_file(path, data_dir=self.data_dir).pages), 1)

    def test_cli_prepare_only_renders_pdf_without_api_credentials(self):
        source = self.root / "sheet.pdf"
        source.write_bytes(sample_pdf())
        result = subprocess.run(
            [sys.executable, "extractor.py", str(source), "--prepare-only", "--dpi", "72"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATA_DIR": str(self.data_dir), "OPENAI_API_KEY": ""},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Prepared page 2:", result.stdout)
        self.assertEqual(len(list(self.data_dir.rglob("page_*.png"))), 2)
        self.assertFalse((self.data_dir / "runs").exists())


if __name__ == "__main__":
    unittest.main()
