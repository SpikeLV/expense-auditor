"""Unit tests for the supporting-document model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from expense_auditor.models import Document, DocumentType


def _document(**overrides: object) -> Document:
    payload: dict[str, object] = {
        "id": "doc-1",
        "filepath": Path("data/2026/10-October/documents/acme.pdf"),
        "document_type": DocumentType.PDF,
    }
    payload.update(overrides)
    return Document.model_validate(payload)


def test_document_allows_unextracted_fields() -> None:
    document = _document()

    assert document.filename == "acme.pdf"
    assert document.issued_date is None
    assert document.amount is None
    assert document.currency is None
    assert document.merchant_raw is None
    assert document.merchant_normalized is None
    assert document.invoice_number is None
    assert document.extracted_text is None
    assert document.extraction_method is None
    assert document.file_hash is None


def test_document_stores_extracted_fields() -> None:
    document = _document(
        issued_date=date(2026, 10, 3),
        amount="42.10",
        currency="gbp",
        merchant_raw="  Acme Ltd  ",
        invoice_number=" INV-9 ",
        extracted_text="Invoice INV-9",
    )

    assert document.issued_date == date(2026, 10, 3)
    assert document.amount == Decimal("42.10")
    assert document.currency == "GBP"
    assert document.merchant_raw == "Acme Ltd"
    assert document.merchant_normalized == "ACME"
    assert document.invoice_number == "INV-9"
    assert document.extracted_text == "Invoice INV-9"


def test_suffix_match_is_case_insensitive() -> None:
    document = _document(filepath=Path("scans/Receipt.PDF"), document_type=DocumentType.PDF)

    assert document.document_type is DocumentType.PDF
    assert document.filename == "Receipt.PDF"


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (Path("receipt.jpg"), DocumentType.JPG),
        (Path("receipt.jpeg"), DocumentType.JPEG),
        (Path("receipt.png"), DocumentType.PNG),
    ],
)
def test_supported_image_suffixes(path: Path, kind: DocumentType) -> None:
    document = _document(filepath=path, document_type=kind)

    assert document.filepath == path
    assert document.document_type is kind


def test_jpg_and_jpeg_are_distinct_kinds() -> None:
    with pytest.raises(ValidationError, match="does not match document type"):
        _document(filepath=Path("receipt.jpg"), document_type=DocumentType.JPEG)


def test_kind_must_match_suffix() -> None:
    with pytest.raises(ValidationError, match="does not match document type"):
        _document(filepath=Path("receipt.pdf"), document_type=DocumentType.PNG)


def test_amount_rejects_float() -> None:
    with pytest.raises(ValidationError):
        _document(amount=12.5)


def test_blank_optional_text_is_missing() -> None:
    document = _document(invoice_number="  ", currency="  ", merchant_raw="")

    assert document.invoice_number is None
    assert document.currency is None
    assert document.merchant_raw is None
    assert document.merchant_normalized is None


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _document(document_type="tiff")


def test_json_round_trip() -> None:
    document = _document(amount=Decimal("8.00"), issued_date=date(2026, 10, 1))
    dumped = document.model_dump(mode="json")

    assert isinstance(dumped["amount"], str)
    assert Document.model_validate(dumped) == document
