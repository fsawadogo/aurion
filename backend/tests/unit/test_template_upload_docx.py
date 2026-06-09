"""Unit tests for the template-upload document text extraction (#6).

`_extract_document_text` parses .docx via python-docx and decodes everything
else as UTF-8. A .docx it can't open raises 400 rather than feeding the LLM
the raw zip bytes.
"""

from __future__ import annotations

import io
import os
import zipfile

# APP_ENV before importing the route module (matches test_config_endpoint).
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
from docx import Document  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.api.v1.me import _extract_document_text  # noqa: E402


def _docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extracts_docx_paragraphs():
    data = _docx_bytes(["Chief Complaint", "History of Present Illness"])
    text = _extract_document_text("template.docx", data)
    assert "Chief Complaint" in text
    assert "History of Present Illness" in text


def test_docx_detected_by_extension_case_insensitive():
    data = _docx_bytes(["Assessment"])
    assert "Assessment" in _extract_document_text("Template.DOCX", data)


def test_decodes_plain_text():
    assert _extract_document_text("t.txt", b"hello world").strip() == "hello world"
    assert _extract_document_text("t.json", b'{"key":"x"}').strip() == '{"key":"x"}'


def test_bad_docx_raises_400():
    with pytest.raises(HTTPException) as exc:
        _extract_document_text("broken.docx", b"this is definitely not a zip")
    assert exc.value.status_code == 400


def test_lenient_utf8_decode_for_non_docx_binary():
    # Non-docx binary survives via errors='ignore' (legacy behavior).
    out = _extract_document_text("notes.txt", b"ok\xff\xfetext")
    assert "ok" in out and "text" in out


def test_decompression_bomb_rejected_413():
    # A .docx-named zip whose member inflates past the uncompressed cap is
    # rejected at the streaming guard BEFORE python-docx decompresses it.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"\0" * (26 * 1024 * 1024))  # ~25KB zipped
    with pytest.raises(HTTPException) as exc:
        _extract_document_text("bomb.docx", buf.getvalue())
    assert exc.value.status_code == 413
