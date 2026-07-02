"""Extract text from a BG PDF.

Digital PDFs (e.g. NeSL e-BG) -> direct text layer extraction via PyMuPDF.
Scanned PDFs (physical BG)    -> page rasterisation @300dpi + Tesseract OCR.

The decision is made per page: a page whose text layer yields fewer than
40 characters is treated as a scan.
"""
import io
import re

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

MIN_TEXT_CHARS = 40
OCR_DPI = 300


def extract(pdf_bytes):
    """Return dict with full text, per-page text, ocr flag and doc kind."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages, ocr_pages = [], 0
    for page in doc:
        text = page.get_text("text")
        if len(text.strip()) < MIN_TEXT_CHARS:
            pix = page.get_pixmap(dpi=OCR_DPI)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img, config="--psm 4")
            ocr_pages += 1
        pages.append(text)
    full = "\n".join(pages)
    kind = _detect_kind(full, ocr_pages, len(pages))
    return {
        "text": full,
        "pages": pages,
        "page_count": len(pages),
        "ocr_pages": ocr_pages,
        "used_ocr": ocr_pages > 0,
        "kind": kind,
    }


def _detect_kind(text, ocr_pages, page_count):
    t = text.lower()
    nesl_signals = sum(
        1 for s in ("nesl", "e-stamp", "sfms", "ifn 760", "digitally signed")
        if s in t
    )
    if nesl_signals >= 2 and ocr_pages == 0:
        return "nesl"
    if ocr_pages == page_count:
        return "physical"
    if ocr_pages > 0:
        return "physical"
    return "nesl" if nesl_signals else "digital"


def normalise(text):
    """Whitespace-collapsed, ampersand-normalised copy used by all regexes."""
    t = re.sub(r"\s+", " ", text)
    return t.strip()
