import io
import os
import re

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError

from src.ingestion.errors import IngestError

TEXT_EXTENSIONS = (".txt", ".md")
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS + (".pdf",)
MAX_NAME_LENGTH = 80


def safe_upload_name(filename: str) -> str:
    """Turn a user-supplied filename into a flat, safe corpus filename. PDFs are stored as .txt.

    Raises:
        IngestError: 415 for an unsupported extension, 400 if no usable characters remain.
    """
    base = os.path.basename(filename.replace("\\", "/"))
    stem, ext = os.path.splitext(base.lower())
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestError(f"Unsupported file type '{ext or base}'; use .txt, .md or .pdf", 415)

    stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-.")[:MAX_NAME_LENGTH]
    if not stem:
        raise IngestError(f"File name '{filename}' has no usable characters", 400)
    return stem + (".txt" if ext == ".pdf" else ext)


def extract_upload_text(filename: str, data: bytes, max_chars: int | None = None) -> str:
    """Return the plain text of an uploaded .txt, .md or .pdf file.

    Raises:
        IngestError: 415 unsupported type, 422 unreadable PDF, 400 no text, 413 more than max_chars.
    """
    ext = os.path.splitext(filename.lower())[1]
    if ext in TEXT_EXTENSIONS:
        text = data.decode("utf-8-sig", errors="replace")
    elif ext == ".pdf":
        text = _pdf_text(data)
    else:
        raise IngestError(f"Unsupported file type '{ext}'; use .txt, .md or .pdf", 415)

    text = text.replace("\x00", "").strip()
    if not text:
        raise IngestError("The document contains no text", 400)
    if max_chars is not None and len(text) > max_chars:
        raise IngestError(f"The document has {len(text):,} characters; the limit is {max_chars:,}", 413)
    return text


def _pdf_text(data: bytes) -> str:
    """Extract the text of every page of a PDF."""
    if b"%PDF-" not in data[:1024]:
        raise IngestError("Not a valid PDF file", 422)
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except FileNotDecryptedError as e:
        raise IngestError("Password-protected PDFs are not supported", 422) from e
    except Exception as e:  # pypdf raises many different exception types on malformed files
        raise IngestError(f"Could not read the PDF: {e}", 422) from e

    text = "\n\n".join(page.strip() for page in pages if page.strip())
    if not text:
        raise IngestError("The PDF has no extractable text (scanned pages would need OCR)", 422)
    return text
