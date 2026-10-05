import base64
import io
import zipfile

import cv2
import numpy as np
import pymupdf

from tests.conftest import requires_db
from tests.test_auth_api import api, bearer, secrets, signup  # noqa: F401 (fixtures)

pytestmark = requires_db
JD = "Hiring AI Engineer at Acme. Python, LLMs. Mail hr@acme.ai"


def screenshot(*lines) -> bytes:
    img = np.full((60 + 50 * len(lines), 900, 3), 255, np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(img, line, (20, 50 + 50 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2)
    return cv2.imencode(".png", img)[1].tobytes()


def text_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), JD)
    return doc.tobytes()


def scanned_pdf() -> bytes:
    """A PDF that is only a picture of text (no text layer), needs OCR."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=screenshot("Hiring ML Engineer at Acme", "Mail resume to hr@acme.ai"))
    return doc.tobytes()


def docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   '<w:p><w:r><w:t>Hiring AI Engineer at Acme.</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>Mail </w:t></w:r><w:r><w:t>hr@acme.ai</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


async def extract(api, t, name, data: bytes):
    return await api.post("/chat/extract", headers=bearer(t),
                          json={"filename": name, "data": base64.b64encode(data).decode()})


async def test_screenshot_text_is_read(api):
    t = await signup(api)
    r = await extract(api, t, "job.png", screenshot("Hiring AI Engineer at Acme", "Mail resume to hr@acme.ai"))
    assert r.status_code == 200
    text = r.json()["text"]
    assert "Engineer at Acme" in text and "hr@acme.ai" in text  # ("AI" may read as "Al": same shape in this font)


async def test_pdf_text_is_read(api):
    t = await signup(api)
    r = await extract(api, t, "JD.pdf", text_pdf())
    assert r.status_code == 200 and "hr@acme.ai" in r.json()["text"]


async def test_scanned_pdf_is_read_with_ocr(api):
    t = await signup(api)
    r = await extract(api, t, "scan.pdf", scanned_pdf())
    assert r.status_code == 200 and "hr@acme.ai" in r.json()["text"]


async def test_word_docx_is_read(api):
    t = await signup(api)
    r = await extract(api, t, "JD.docx", docx())
    assert r.status_code == 200 and r.json()["text"] == "Hiring AI Engineer at Acme.\nMail hr@acme.ai"


async def test_plain_text_is_read(api):
    t = await signup(api)
    r = await extract(api, t, "jd.txt", JD.encode())
    assert r.status_code == 200 and r.json()["text"] == JD


async def test_unsupported_and_broken_files_are_refused_clearly(api):
    t = await signup(api)
    assert (await extract(api, t, "old.doc", b"\xd0\xcf\x11\xe0")).status_code == 415
    r = await extract(api, t, "bad.pdf", b"not a pdf")
    assert r.status_code == 415 and "read" in r.json()["detail"]


async def test_extract_needs_sign_in(api):
    r = await api.post("/chat/extract", json={"filename": "a.txt", "data": "aGk="})
    assert r.status_code == 401
