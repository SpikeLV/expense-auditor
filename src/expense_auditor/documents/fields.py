"""Extract candidate fields from multi-line document text.

PDF and OCR extractors return text only. This module finds candidate strings
in that text and passes each candidate to ``parse_date`` or ``parse_amount``.
Those parsers still accept only one value. Missing fields stay ``None``.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from expense_auditor.identity import document_id
from expense_auditor.models.base import DomainModel
from expense_auditor.models.document import Document, DocumentType, ExtractionMethod
from expense_auditor.models.fields import OptionalCurrencyCode, OptionalPositiveMoney, OptionalText
from expense_auditor.normalization.amount import AmountParseError, NormalizedAmount, parse_amount
from expense_auditor.normalization.date import DateParseError, parse_date

_DATE_TOKEN = re.compile(r"(?<!\d)(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{4})(?!\d)")
_AMOUNT_TOKEN = re.compile(
    r"[€£]\s*\d(?:[\d .,]*\d)?"
    r"|\b[A-Za-z]{3}\s+\d(?:[\d .,]*\d)?"
    r"|\d(?:[\d .,]*\d)?(?:\s+[A-Za-z]{3})?"
)
_TOTAL_LINE = re.compile(r"(?i)\b(?:amount due|grand total|total|summa|kopā|kopa|payable)\b")
_MERCHANT_LINE = re.compile(
    r"(?im)^[ \t]*(?:supplier|merchant|seller|vendor|piegādātājs|piegadatajs)"
    r"[ \t]*[:\-][ \t]*(.+?)[ \t]*$"
)
_INVOICE_TOKEN = re.compile(
    r"(?i)\b(?:invoice|inv|rēķina|rēķins|rekina|rekins)\b"
    r"(?:[ \t]+(?:no|nr|number)\.?)?"
    r"(?:[ \t]*[:#][ \t]*|[ \t]+)"
    r"([A-Za-z0-9\-/]*\d[A-Za-z0-9\-/]*)"
)


class ExtractedDocumentFields(DomainModel):
    """Fields found in document text. Absent fields are ``None``."""

    issued_date: date | None = None
    amount: OptionalPositiveMoney = None
    currency: OptionalCurrencyCode = None
    merchant_raw: OptionalText = None
    invoice_number: OptionalText = None


def extract_document_fields(text: str) -> ExtractedDocumentFields:
    """Return candidate fields from ``text``.

    A missing date, amount, currency, merchant, or invoice number stays
    ``None``. Currency is taken only from a parsed amount. No field is invented.
    """
    if not isinstance(text, str):
        raise TypeError("document text must be text")
    lines = text.splitlines()
    amount = _amount_from_lines(lines)
    return ExtractedDocumentFields(
        issued_date=_unique_date(text),
        amount=None if amount is None else amount.amount,
        currency=None if amount is None else amount.currency,
        merchant_raw=_unique_text(_MERCHANT_LINE.findall(text)),
        invoice_number=_unique_text(_INVOICE_TOKEN.findall(text)),
    )


def document_from_content(
    *,
    filepath: Path,
    content: bytes,
    document_type: DocumentType,
    extracted_text: str,
    extraction_method: ExtractionMethod,
) -> Document:
    """Build a ``Document`` from file bytes and text that was already extracted.

    ``id`` and ``file_hash`` are the SHA-256 of ``content``. Field values come
    from ``extract_document_fields``. The file is not modified.
    """
    fields = extract_document_fields(extracted_text)
    digest = document_id(content)
    return Document(
        id=digest,
        filename=filepath.name,
        filepath=filepath,
        document_type=document_type,
        issued_date=fields.issued_date,
        merchant_raw=fields.merchant_raw,
        amount=fields.amount,
        currency=fields.currency,
        invoice_number=fields.invoice_number,
        extracted_text=extracted_text,
        extraction_method=extraction_method,
        file_hash=digest,
    )


def document_from_path(
    path: Path,
    *,
    extracted_text: str,
    extraction_method: ExtractionMethod,
    document_type: DocumentType,
) -> Document:
    """Read ``path`` for its id and build a ``Document``. The file is not modified."""
    return document_from_content(
        filepath=path,
        content=path.read_bytes(),
        document_type=document_type,
        extracted_text=extracted_text,
        extraction_method=extraction_method,
    )


def _unique_date(text: str) -> date | None:
    found: set[date] = set()
    for match in _DATE_TOKEN.finditer(text):
        try:
            found.add(parse_date(match.group(0)))
        except DateParseError:
            continue
    if len(found) != 1:
        return None
    return next(iter(found))


def _amount_from_lines(lines: list[str]) -> NormalizedAmount | None:
    labeled = [line for line in lines if _TOTAL_LINE.search(line)]
    if labeled:
        return _unique_amount(_parse_line_amounts(labeled, allow_bare=True))
    return _unique_amount(_parse_line_amounts(lines, allow_bare=False))


def _parse_line_amounts(lines: list[str], *, allow_bare: bool) -> list[NormalizedAmount]:
    parsed: list[NormalizedAmount] = []
    for line in lines:
        for token in _AMOUNT_TOKEN.findall(line):
            if not allow_bare and token.strip().isdigit():
                continue
            try:
                parsed.append(parse_amount(token))
            except AmountParseError:
                continue
    return parsed


def _unique_amount(parsed: list[NormalizedAmount]) -> NormalizedAmount | None:
    pairs = {(item.amount, item.currency) for item in parsed}
    if len(pairs) != 1:
        return None
    return parsed[0]


def _unique_text(values: list[str]) -> str | None:
    cleaned = [value.strip() for value in values if value.strip()]
    unique = set(cleaned)
    if len(unique) != 1:
        return None
    return cleaned[0]
