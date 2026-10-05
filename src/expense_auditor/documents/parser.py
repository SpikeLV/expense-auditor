"""Read one supporting file into the invoice fields already extracted elsewhere.

PDF text comes from the existing text-layer parser. Images use the existing
OCR path. This module does not add a second extractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_auditor.documents.fields import extract_document_fields
from expense_auditor.documents.ocr import OcrError, extract_image_text
from expense_auditor.documents.pdf_parser import PdfTextError, extract_pdf_text

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_YEAR = re.compile(
    r"(?i)\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(20\d{2})\b"
)
_ISO_MONTH = re.compile(r"\b(20\d{2})[-_](0[1-9]|1[0-2])\b")
_MONTH_THEN_YEAR = re.compile(r"(?<!\d)(0[1-9]|1[0-2])[-_](20\d{2})(?!\d)")
_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


@dataclass(frozen=True)
class FoundInvoice:
    """Fields gathered from one file in the contract folder."""

    filename: str
    filepath: Path
    invoice_number: str | None
    issued_date: date | None
    period: str | None
    amount: Decimal | None
    currency: str | None
    supplier: str | None


def read_document_text(path: Path) -> str:
    """Return text from a PDF or image. An unreadable file yields an empty string."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return extract_pdf_text(path).text
        if suffix in _IMAGE_SUFFIXES:
            return extract_image_text(path)
    except (PdfTextError, OcrError, OSError):
        return ""
    return ""


def parse_invoice_file(path: Path) -> FoundInvoice:
    """Extract invoice fields from ``path`` without modifying the file."""
    text = read_document_text(path)
    fields = extract_document_fields(text)
    return FoundInvoice(
        filename=path.name,
        filepath=path,
        invoice_number=fields.invoice_number,
        issued_date=fields.issued_date,
        period=_period(path.name, text, fields.issued_date),
        amount=fields.amount,
        currency=fields.currency,
        supplier=fields.merchant_raw,
    )


def _period(filename: str, text: str, issued: date | None) -> str | None:
    signals: list[str] = []
    if issued is not None:
        signals.append(f"{issued.year:04d}-{issued.month:02d}")
    text_periods = _periods_in_text(text)
    if len(text_periods) == 1:
        signals.append(text_periods[0])
    named = _period_in_filename(filename)
    if named is not None:
        signals.append(named)
    unique = set(signals)
    if len(unique) != 1:
        return None
    return next(iter(unique))


def _periods_in_text(text: str) -> tuple[str, ...]:
    found: set[str] = set()
    for match in _MONTH_YEAR.finditer(text):
        month = _MONTHS.index(match.group(1).lower()) + 1
        found.add(f"{match.group(2)}-{month:02d}")
    for match in _ISO_MONTH.finditer(text):
        found.add(f"{match.group(1)}-{match.group(2)}")
    return tuple(sorted(found))


def _period_in_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    iso = _ISO_MONTH.search(stem)
    if iso is not None:
        return f"{iso.group(1)}-{iso.group(2)}"
    swapped = _MONTH_THEN_YEAR.search(stem)
    if swapped is not None:
        return f"{swapped.group(2)}-{swapped.group(1)}"
    named = _MONTH_YEAR.search(stem.replace("_", " ").replace("-", " "))
    if named is not None:
        month = _MONTHS.index(named.group(1).lower()) + 1
        return f"{named.group(2)}-{month:02d}"
    return None
