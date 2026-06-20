"""Local text extraction from uploaded documents (Camino B).

Extracts plain text from PDF and DOCX files locally, without sending the file
to the LLM provider. This keeps the pipeline provider-independent and prepares
the ground for RAG chunking in later modules.
"""

from __future__ import annotations

import io

import structlog
from fastapi import UploadFile

log = structlog.get_logger()

# Hard cap per attachment to avoid blowing the LLM context window.
MAX_CHARS = 6_000


async def extract_text(upload: UploadFile) -> str:
    """Return plain text from a PDF or DOCX UploadFile, capped at MAX_CHARS.

    Returns an empty string if the file type is unsupported or extraction fails.
    """
    content = await upload.read()
    filename = (upload.filename or "").lower()

    try:
        if filename.endswith(".pdf"):
            text = _extract_pdf(content)
        elif filename.endswith(".docx"):
            text = _extract_docx(content)
        else:
            log.warning("document_unsupported_type", filename=upload.filename)
            return ""
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "document_extraction_failed",
            filename=upload.filename,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return ""

    if len(text) > MAX_CHARS:
        log.info(
            "document_text_truncated",
            filename=upload.filename,
            original_chars=len(text),
            truncated_to=MAX_CHARS,
        )
        text = text[:MAX_CHARS] + "\n[... document truncated ...]"

    log.info(
        "document_extracted",
        filename=upload.filename,
        chars=len(text),
    )
    return text


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p for p in pages if p.strip())


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
