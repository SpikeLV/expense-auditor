"""Unit tests for the supporting-document model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from expense_auditor.models import Document, DocumentKind


def _document(**overrides: object) -> Document:
    payload: dict[str, object] = {
        "id": "doc-1",
        "path": Path("data/2026/10-October/documents/acme.pdf"),
        "kind": DocumentKind.PDF,
    }
    payload.update(overrides)
    return Document.model_validate(payload)


def test_document_allows_unextracted_fields() -> None:
    document = _document()

    assert document.issued_date is None
    assert document.amount is None
    assert document.currency is None
    assert document.merchant is None
    assert document.invoice_number is None
    assert document.text is None


def test_document_stores_extracted_fields() -> None:
    document = _document(
        issued_date=date(2026, 10, 3),
        amount="42.10",
        currency="gbp",
        merchant="  Acme Ltd  ",
        invoice_number=" INV-9 ",
        text="Invoice INV-9",
    )

    assert document.issued_date == date(2026, 10, 3)
    assert document.amount == Decimal("42.10")
    assert document.currency == "GBP"
    assert document.merchant == "Acme Ltd"
    assert document.invoice_number == "INV-9"
    assert document.text == "Invoice INV-9"


def test_suffix_match_is_case_insensitive() -> None:
    document = _document(path=Path("scans/Receipt.PDF"), kind=DocumentKind.PDF)

    assert document.kind is DocumentKind.PDF


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        (Path("receipt.jpg"), DocumentKind.JPG),
        (Path("receipt.jpeg"), DocumentKind.JPEG),
        (Path("receipt.png"), DocumentKind.PNG),
    ],
)
def test_supported_image_suffixes(path: Path, kind: DocumentKind) -> None:
    document = _document(path=path, kind=kind)

    assert document.path == path
    assert document.kind is kind


def test_jpg_and_jpeg_are_distinct_kinds() -> None:
    with pytest.raises(ValidationError, match="does not match kind"):
        _document(path=Path("receipt.jpg"), kind=DocumentKind.JPEG)


def test_kind_must_match_suffix() -> None:
    with pytest.raises(ValidationError, match="does not match kind"):
        _document(path=Path("receipt.pdf"), kind=DocumentKind.PNG)


def test_amount_rejects_float() -> None:
    with pytest.raises(ValidationError):
        _document(amount=12.5)


def test_blank_optional_text_is_missing() -> None:
    document = _document(invoice_number="  ", currency="  ", merchant="")

    assert document.invoice_number is None
    assert document.currency is None
    assert document.merchant is None


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _document(kind="tiff")


def test_json_round_trip() -> None:
    document = _document(amount=Decimal("8.00"), issued_date=date(2026, 10, 1))
    dumped = document.model_dump(mode="json")

    assert isinstance(dumped["amount"], str)
    assert Document.model_validate(dumped) == document
