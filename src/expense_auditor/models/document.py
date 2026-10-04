"""Supporting receipt or invoice."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import (
    OptionalCurrencyCode,
    OptionalPositiveMoney,
    OptionalText,
    RequiredPath,
    RequiredText,
)


class DocumentKind(StrEnum):
    """File types V0.1 knows how to read."""

    PDF = "pdf"
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"


_KIND_SUFFIX: dict[DocumentKind, str] = {
    DocumentKind.PDF: ".pdf",
    DocumentKind.JPG: ".jpg",
    DocumentKind.JPEG: ".jpeg",
    DocumentKind.PNG: ".png",
}


class Document(DomainModel):
    """One supporting file and the fields extracted from it.

    Extracted fields stay ``None`` when the file has not yielded that value.
    ``text`` holds extracted text when a later phase has read the file.
    """

    id: RequiredText
    path: RequiredPath
    kind: DocumentKind
    issued_date: date | None = None
    amount: OptionalPositiveMoney = None
    currency: OptionalCurrencyCode = None
    merchant: OptionalText = None
    invoice_number: OptionalText = None
    text: OptionalText = None

    @model_validator(mode="after")
    def suffix_matches_kind(self) -> Self:
        suffix = self.path.suffix.lower()
        expected = _KIND_SUFFIX[self.kind]
        if suffix != expected:
            raise ValueError(f"path suffix {suffix!r} does not match kind {self.kind.value}")
        return self
