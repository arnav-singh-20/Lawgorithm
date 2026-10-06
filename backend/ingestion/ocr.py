"""
OCR ingestion (Phase 2).

Handles:
  - plain images (.png, .jpg, .jpeg)
  - scanned PDFs (rasterize each page, then OCR)

Requires system-level Tesseract (`apt install tesseract-ocr`) and, for
scanned PDFs, `poppler-utils` (for pdf2image). Both are OS packages, not
pip packages — install them on whatever machine actually runs this.

We import pytesseract / pdf2image lazily and raise a clear, actionable
error if they (or their system binaries) aren't available, rather than
letting the whole app crash at import time.
"""

from pathlib import Path


class OCRUnavailableError(RuntimeError):
    pass


def extract_with_ocr(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _ocr_pdf(file_path)
    elif suffix in {".png", ".jpg", ".jpeg"}:
        return _ocr_image(file_path)
    else:
        raise ValueError(f"OCR not supported for file type: {suffix}")


def _ocr_image(file_path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OCRUnavailableError(
            "pytesseract/Pillow not installed. Run `pip install pytesseract pillow` "
            "and install the Tesseract binary (`apt install tesseract-ocr`)."
        ) from exc

    image = Image.open(file_path)
    return pytesseract.image_to_string(image)


def _ocr_pdf(file_path: Path) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise OCRUnavailableError(
            "pdf2image/pytesseract not installed, or poppler-utils / tesseract-ocr "
            "system binaries are missing. Run `pip install pdf2image pytesseract` and "
            "`apt install poppler-utils tesseract-ocr`."
        ) from exc

    pages = convert_from_path(str(file_path))

    page_texts = []
    for page_image in pages:
        page_texts.append(pytesseract.image_to_string(page_image))

    return "\n\n".join(page_texts)
