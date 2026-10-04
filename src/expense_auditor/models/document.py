"""Supporting receipt or invoice."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import (
    OptionalCurrencyCode,
    OptionalPositiveMoney,
    OptionalSha256,
    OptionalText,
    RequiredPath,
    RequiredText,
)
from expense_auditor.normalization.merchant import normalize_merchant


class DocumentType(StrEnum):
    """File types V0.1 knows how to read."""

    PDF = "pdf"
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"


class ExtractionMethod(StrEnum):
    """How ``extracted_text`` was obtained. Field extraction is a later step."""

    PDF_TEXT = "pdf_text"
    OCR = "ocr"


_TYPE_SUFFIX: dict[DocumentType, str] = {
    DocumentType.PDF: ".pdf",
    DocumentType.JPG: ".jpg",
    DocumentType.JPEG: ".jpeg",
    DocumentType.PNG: ".png",
}


class Document(DomainModel):
    """One supporting file and the fields extracted from its text.

    Missing fields stay ``None``. ``merchant_raw`` keeps the extracted name.
    ``merchant_normalized`` is filled from that name and is never a substitute
    for it. ``id`` is the SHA-256 of the file bytes when the file has been read.
    """

    id: RequiredText
    filename: RequiredText
    filepath: RequiredPath
    document_type: DocumentType
    issued_date: date | None = None
    merchant_raw: OptionalText = None
    merchant_normalized: OptionalText = None
    amount: OptionalPositiveMoney = None
    currency: OptionalCurrencyCode = None
    invoice_number: OptionalText = None
    extracted_text: OptionalText = None
    extraction_method: ExtractionMethod | None = None
    file_hash: OptionalSha256 = None

    @model_validator(mode="before")
    @classmethod
    def fill_derived_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        _fill_filename(payload)
        _fill_merchant(payload)
        return payload

    @model_validator(mode="after")
    def derived_fields_agree(self) -> Self:
        if self.filename != self.filepath.name:
            raise ValueError("filename must match the filepath name")
        suffix = self.filepath.suffix.lower()
        expected_suffix = _TYPE_SUFFIX[self.document_type]
        if suffix != expected_suffix:
            raise ValueError(
                f"path suffix {suffix!r} does not match document type {self.document_type.value}"
            )
        if self.file_hash is not None and self.id != self.file_hash:
            raise ValueError("document id must equal file_hash")
        expected = _normalized_merchant(self.merchant_raw)
        if self.merchant_normalized != expected:
            raise ValueError("merchant_normalized does not match merchant_raw")
        return self


def normalize_document(document: Document) -> Document:
    """Return ``document`` with ``merchant_normalized`` filled from ``merchant_raw``.

    ``merchant_raw`` and ``extracted_text`` are kept. Matching should run after
    this step.
    """
    expected = _normalized_merchant(document.merchant_raw)
    if document.merchant_normalized == expected:
        return document
    payload = document.model_dump()
    payload["merchant_normalized"] = expected
    return Document.model_validate(payload)


def _fill_filename(payload: dict[str, object]) -> None:
    if payload.get("filename") not in (None, ""):
        return
    filepath = payload.get("filepath")
    if isinstance(filepath, Path):
        payload["filename"] = filepath.name
    elif isinstance(filepath, str) and filepath.strip():
        payload["filename"] = Path(filepath.strip()).name


def _fill_merchant(payload: dict[str, object]) -> None:
    raw = payload.get("merchant_raw")
    expected = _normalized_merchant(raw if isinstance(raw, str) else None)
    supplied = payload.get("merchant_normalized", None)
    if isinstance(supplied, str) and not supplied.strip():
        supplied = None
    if supplied is None:
        payload["merchant_normalized"] = expected
        return
    if isinstance(supplied, str) and supplied.strip() != expected:
        raise ValueError("merchant_normalized does not match merchant_raw")


def _normalized_merchant(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    return normalize_merchant(raw) or None
