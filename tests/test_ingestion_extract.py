import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.ingestion.errors import IngestError
from src.ingestion.extract import extract_upload_text, safe_upload_name


def make_pdf(text: str | None = None, password: str | None = None) -> bytes:
    """Build a one-page PDF in memory. text=None leaves the page blank, like a scan without OCR."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    if text is not None:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("ascii"))
        page.replace_contents(content)
    if password is not None:
        writer.encrypt(user_password=password, algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("filename, expected", [
    ("notes.md", "notes.md"),
    ("../../etc/passwd.txt", "passwd.txt"),
    ("..\\..\\evil.md", "evil.md"),
    ("My Report (final).PDF", "my-report-final.txt"),
    (".env.txt", "env.txt"),
])
def test_safe_upload_name_flattens_and_cleans(filename, expected):
    """Verify names lose directories, unsafe characters and leading dots, and PDFs become .txt."""
    assert safe_upload_name(filename) == expected


def test_safe_upload_name_caps_length():
    """Verify very long names are cut to MAX_NAME_LENGTH before the extension."""
    assert safe_upload_name("a" * 200 + ".md") == "a" * 80 + ".md"


@pytest.mark.parametrize("filename, status", [("virus.exe", 415), ("README", 415), ("!!!.txt", 400)])
def test_safe_upload_name_rejects(filename, status):
    """Verify unsupported types and names with nothing usable are rejected with the right status."""
    with pytest.raises(IngestError) as exc:
        safe_upload_name(filename)
    assert exc.value.status_code == status


def test_text_files_tolerate_bom_and_invalid_utf8():
    """Verify a UTF-8 BOM is dropped and non-UTF-8 bytes are replaced instead of failing."""
    assert extract_upload_text("a.txt", "\ufeffhello".encode("utf-8")) == "hello"
    assert extract_upload_text("b.md", "café".encode("latin-1")) == "caf\ufffd"


def test_pdf_text_is_extracted():
    """Verify the text layer of a PDF is returned."""
    text = extract_upload_text("doc.pdf", make_pdf("Quokkas are small marsupials"))
    assert "Quokkas are small marsupials" in text


@pytest.mark.parametrize("data", [
    b"just some text",                         # no %PDF- header
    b"%PDF-1.7\nnot really a pdf",             # header, but no PDF structure
    make_pdf(None),                            # no text layer
    make_pdf("secret plans", password="pw"),   # needs a password to open
], ids=["no-header", "corrupt", "no-text", "password"])
def test_bad_pdfs_are_rejected_with_422(data):
    """Verify unreadable PDFs are rejected before anything is stored."""
    with pytest.raises(IngestError) as exc:
        extract_upload_text("doc.pdf", data)
    assert exc.value.status_code == 422


def test_empty_and_oversized_text_are_rejected():
    """Verify whitespace-only files get 400 and text over max_chars gets 413."""
    with pytest.raises(IngestError) as exc:
        extract_upload_text("a.txt", b"  \n\t ")
    assert exc.value.status_code == 400

    with pytest.raises(IngestError) as exc:
        extract_upload_text("a.txt", b"x" * 11, max_chars=10)
    assert exc.value.status_code == 413
