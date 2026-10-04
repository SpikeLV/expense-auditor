"""Unit tests for receipt and invoice PDF text extraction."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from expense_auditor.documents.pdf_parser import PdfTextError, extract_pdf_text


def _write_pdf(path: Path, page_texts: tuple[str | None, ...]) -> Path:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text is not None:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()
    return path


def _write_image_pdf(path: Path) -> Path:
    image_path = path.with_name("pixel.png")
    Image.new("RGB", (8, 8), "red").save(image_path)
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_image(pymupdf.Rect(72, 72, 144, 144), filename=str(image_path))
        document.save(path)
    finally:
        document.close()
    return path


def test_single_page_text_pdf(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "invoice.pdf", ("Invoice 1001\nAcme Supplies",))

    extracted = extract_pdf_text(path)

    assert extracted.path == path
    assert len(extracted.pages) == 1
    assert extracted.pages[0].number == 1
    assert extracted.pages[0].text == "Invoice 1001\nAcme Supplies"
    assert extracted.text == "Invoice 1001\nAcme Supplies"


def test_multi_page_pdf_preserves_page_order(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "invoice.pdf", ("Alpha Supplies", None, "Invoice 42"))

    extracted = extract_pdf_text(path)

    assert [page.number for page in extracted.pages] == [1, 2, 3]
    assert extracted.pages[0].text == "Alpha Supplies"
    assert extracted.pages[1].text == ""
    assert extracted.pages[2].text == "Invoice 42"
    assert extracted.text == "Alpha Supplies\n\nInvoice 42"


def test_blank_pdf_returns_empty_text(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "blank.pdf", (None,))

    extracted = extract_pdf_text(path)

    assert extracted.pages[0].text == ""
    assert extracted.text == ""


def test_non_text_pdf_returns_empty_text(tmp_path: Path) -> None:
    path = _write_image_pdf(tmp_path / "scan.pdf")

    extracted = extract_pdf_text(path)

    assert extracted.text == ""
    assert extracted.pages[0].text == ""


def test_extraction_does_not_modify_pdf(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "invoice.pdf", ("Acme Supplies",))
    before = path.read_bytes()
    modified_at = path.stat().st_mtime_ns

    extract_pdf_text(path)

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at


def test_encrypted_pdf_raises(tmp_path: Path) -> None:
    path = tmp_path / "secret.pdf"
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Secret")
        document.save(
            path,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="secret",
            owner_pw="owner",
        )
    finally:
        document.close()
    before = path.read_bytes()

    with pytest.raises(PdfTextError, match="encrypted"):
        extract_pdf_text(path)

    assert path.read_bytes() == before


def test_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_pdf_text(tmp_path / "missing.pdf")


def test_directory_path_raises(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        extract_pdf_text(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        b"not a pdf",
        b"",
        b"%PDF-1.4 garbage",
    ],
)
def test_corrupted_pdf_raises(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(payload)

    with pytest.raises(PdfTextError, match="cannot read PDF"):
        extract_pdf_text(path)

    assert path.read_bytes() == payload
