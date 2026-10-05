"""Attached file → text, all on this machine (₹0): PDF (text layer, or OCR for scanned pages), Word .docx, text, images."""

import io
import zipfile
from functools import lru_cache
from pathlib import PurePath
from xml.etree import ElementTree

import pymupdf
from rapidocr_onnxruntime import RapidOCR

IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TEXTS = {".txt", ".md", ".csv"}
SUPPORTED = sorted({".pdf", ".docx", *IMAGES, *TEXTS})
OCR_PAGES = 5  # scanned PDFs: OCR the first pages only (a JD is short; OCR is ~1 s/page)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Unsupported(Exception):
    pass


@lru_cache
def _ocr() -> RapidOCR:
    return RapidOCR()  # loads the models once (~1 s)


def image_text(image: bytes) -> str:
    result, _ = _ocr()(image)
    return "\n".join(line[1] for line in result or [])


def _pdf(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc).strip()
        if len(text) >= 50:
            return text
        # no text layer (a scan / photo saved as PDF): render the pages and OCR them
        return "\n".join(image_text(doc[i].get_pixmap(dpi=150).tobytes("png")) for i in range(min(len(doc), OCR_PAGES)))


def _docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")).strip()


def read_file(filename: str, data: bytes) -> str:
    """Blocking (CPU), call it in a thread. Raises Unsupported for other types or unreadable files."""
    ext = PurePath(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise Unsupported(f"Can't read {ext or 'this'} files yet. Use PDF, Word (.docx), an image or a text file.")
    try:
        if ext == ".pdf":
            return _pdf(data)
        if ext == ".docx":
            return _docx(data)
        if ext in TEXTS:
            return data.decode("utf-8", errors="replace").strip()
        return image_text(data)
    except Exception as e:  # noqa: BLE001, broken/encrypted/mislabelled file
        raise Unsupported(f"Couldn't read that {ext[1:].upper()} file. Is it damaged or password-protected?") from e
