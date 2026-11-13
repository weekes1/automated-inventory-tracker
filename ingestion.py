"""Bounded local ingestion: validate uploads, preserve originals, create PNGs."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import warnings

import PIL
from PIL import Image, ImageOps
import pymupdf


@dataclass(frozen=True)
class InputLimits:
    max_bytes: int = 20 * 1024 * 1024
    max_pages: int = 20
    max_dimension: int = 10_000
    max_page_pixels: int = 20_000_000
    max_total_pixels: int = 100_000_000
    max_total_png_bytes: int = 100 * 1024 * 1024
    max_pdf_objects: int = 20_000


DEFAULT_LIMITS = InputLimits()
IMAGE_TYPES = {"PNG": ("image/png", {".png"}), "JPEG": ("image/jpeg", {".jpg", ".jpeg"}),
               "WEBP": ("image/webp", {".webp"}), "GIF": ("image/gif", {".gif"})}


class InputValidationError(ValueError):
    """The upload cannot be accepted under the configured input policy."""


@dataclass(frozen=True)
class IngestedPage:
    page_number: int
    path: Path
    metadata: dict


@dataclass(frozen=True)
class IngestedDocument:
    document_id: str
    original_path: Path
    pages: list[IngestedPage]


def _check_bytes(data: bytes, limits: InputLimits) -> None:
    if not isinstance(data, bytes) or not data:
        raise InputValidationError("Provide a non-empty file as bytes")
    if len(data) > limits.max_bytes:
        raise InputValidationError(f"File exceeds the {limits.max_bytes // (1024 * 1024)} MiB limit")


def _check_dimensions(width: int, height: int, limits: InputLimits) -> None:
    if min(width, height) < 1 or max(width, height) > limits.max_dimension or width * height > limits.max_page_pixels:
        raise InputValidationError("Page dimensions or pixel count exceed the input limits")


def inspect_image(data: bytes, limits: InputLimits = DEFAULT_LIMITS) -> tuple[str, int, int]:
    """Validate decoded type, dimensions, frame count, integrity, and decoding."""
    _check_bytes(data, limits)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in IMAGE_TYPES:
                    raise InputValidationError("Only PNG, JPEG, WEBP, and static GIF images are accepted")
                mime = IMAGE_TYPES[image.format][0]
                width, height = image.size
                _check_dimensions(width, height, limits)
                if getattr(image, "n_frames", 1) != 1:
                    raise InputValidationError("Animated or multi-frame images are not accepted")
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
        return mime, width, height
    except InputValidationError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InputValidationError("Image is malformed, truncated, or too large to decode") from exc


def _image_png(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as image:
        oriented = ImageOps.exif_transpose(image).convert("RGBA")
        white = Image.new("RGBA", oriented.size, "white")
        rgb = Image.alpha_composite(white, oriented).convert("RGB")
        output = BytesIO()
        rgb.save(output, format="PNG")
        return output.getvalue()


def _pdf_pngs(data: bytes, dpi: int, limits: InputLimits) -> list[tuple[bytes, dict]]:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass or document.is_encrypted or document.metadata.get("encryption"):
                raise InputValidationError("Encrypted/password-protected PDFs are not accepted")
            if document.is_repaired:
                raise InputValidationError("Malformed PDFs requiring repair are not accepted")
            if not 1 <= document.page_count <= limits.max_pages:
                raise InputValidationError(f"PDF must contain 1 to {limits.max_pages} pages")
            if document.xref_length() > limits.max_pdf_objects:
                raise InputValidationError("PDF contains too many objects")
            if document.embfile_count():
                raise InputValidationError("PDF attachments are not accepted")
            # Inspect parsed object dictionaries, including compressed objects.
            # Reject active features rather than trying to repair/sanitize them.
            active = re.compile(r"/(?:JS|JavaScript|Launch|AA|XFA|EmbeddedFile|FileAttachment|RichMedia|SubmitForm|ImportData|GoToR|GoToE|Rendition)\b")
            for xref in range(1, document.xref_length()):
                if active.search(document.xref_object(xref)):
                    raise InputValidationError("PDF scripting, attachments, or active actions are not accepted")
            total_pixels = 0
            for page in document:
                if not all(math.isfinite(value) and value > 0 for value in (page.rect.width, page.rect.height)):
                    raise InputValidationError("PDF page has invalid dimensions")
                width = math.ceil(page.rect.width * dpi / 72)
                height = math.ceil(page.rect.height * dpi / 72)
                _check_dimensions(width, height, limits)
                total_pixels += width * height
                if total_pixels > limits.max_total_pixels:
                    raise InputValidationError("PDF total rendered pixels exceed the input limit")
            pages = []
            total_bytes = 0
            for page in document:
                pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False, annots=True)
                _check_dimensions(pixmap.width, pixmap.height, limits)
                png = pixmap.tobytes("png")
                _check_bytes(png, limits)
                total_bytes += len(png)
                if total_bytes > limits.max_total_png_bytes:
                    raise InputValidationError("Rendered PNGs exceed the total output size limit")
                pages.append((png, {"renderer": "pymupdf", "renderer_version": pymupdf.VersionBind,
                                    "dpi": dpi, "rotation": page.rotation, "annotations": True,
                                    "width": pixmap.width, "height": pixmap.height}))
            return pages
    except InputValidationError:
        raise
    except (RuntimeError, ValueError, TypeError, OverflowError) as exc:
        raise InputValidationError("PDF could not be parsed or rendered") from exc


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise InputValidationError(f"Existing ingestion artifact differs: {path.name}")
        return
    with path.open("xb") as output:
        output.write(data)


def ingest_bytes(
    data: bytes, filename: str, *, data_dir: Path = Path("data"), dpi: int = 200,
    limits: InputLimits = DEFAULT_LIMITS,
) -> IngestedDocument:
    """Validate/render the entire upload before persisting or calling a model.

    Only generated hash-based paths are used for output, never upload names.
    Originals are kept once per content hash; rendering profiles are immutable.
    """
    _check_bytes(data, limits)
    if not isinstance(filename, str) or not filename or len(filename) > 255 or any(
        ord(char) < 32 or char in "/\\" for char in filename
    ):
        raise InputValidationError("Provide a plain filename without paths or control characters")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 300:
        raise InputValidationError("PDF rendering DPI must be an integer from 72 to 300")
    extension = Path(filename).suffix.lower()
    if data.startswith(b"%PDF-"):
        if extension != ".pdf":
            raise InputValidationError("File extension does not match PDF content")
        rendered = _pdf_pngs(data, dpi, limits)
        source_extension = ".pdf"
        profile = f"pdf_v001_pymupdf-{pymupdf.VersionBind}_{dpi}dpi"
    else:
        mime, _, _ = inspect_image(data, limits)
        extensions = next(suffixes for media, suffixes in IMAGE_TYPES.values() if media == mime)
        if extension not in extensions:
            raise InputValidationError("File extension does not match image content")
        png = _image_png(data)
        _, width, height = inspect_image(png, limits)
        rendered = [(png, {"renderer": "pillow", "renderer_version": PIL.__version__,
                           "transforms": ["exif_transpose", "white_background", "rgb_png"],
                           "width": width, "height": height})]
        source_extension = ".jpg" if mime == "image/jpeg" else "." + mime.split("/")[1]
        profile = f"image_v001_pillow-{PIL.__version__}"
    if sum(metadata["width"] * metadata["height"] for _, metadata in rendered) > limits.max_total_pixels:
        raise InputValidationError("Total prepared pixels exceed the input limit")
    if sum(len(png) for png, _ in rendered) > limits.max_total_png_bytes:
        raise InputValidationError("Prepared PNGs exceed the total output size limit")
    document_id = sha256(data).hexdigest()
    directory = Path(data_dir) / "documents" / document_id
    render_dir = directory / profile
    render_dir.mkdir(parents=True, exist_ok=True)
    original = directory / f"original{source_extension}"
    _write_once(original, data)
    pages = []
    records = []
    for number, (png, metadata) in enumerate(rendered, start=1):
        path = render_dir / f"page_{number:03d}.png"
        _write_once(path, png)
        pages.append(IngestedPage(number, path, metadata))
        records.append({"page_number": number, "path": path.name, "sha256": sha256(png).hexdigest(), **metadata})
    manifest = {"document_id": document_id, "original": original.name,
                "page_count": len(pages), "pages": records}
    _write_once(render_dir / "ingestion.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return IngestedDocument(document_id, original, pages)


def ingest_file(path: Path, **options) -> IngestedDocument:
    """Read only a bounded regular local file; do not follow file symlinks."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise InputValidationError("Input must be a regular file, not a directory or symlink")
    limits = options.get("limits", DEFAULT_LIMITS)
    with path.open("rb") as source:
        data = source.read(limits.max_bytes + 1)
    return ingest_bytes(data, path.name, **options)
