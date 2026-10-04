"""Deterministic identifiers for documents and bank transactions.

Identifiers are SHA-256 hex digests. They do not use random UUIDs, so scanning
or parsing the same input again yields the same ids.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_auditor.models.transaction import TransactionDirection


def document_id(content: bytes) -> str:
    """Return the document id for ``content``.

    The id is the SHA-256 hex digest of the file bytes. The same bytes always
    produce the same id. Different bytes produce a different id.
    """
    if not isinstance(content, bytes):
        raise TypeError("document content must be bytes")
    return hashlib.sha256(content).hexdigest()


def document_id_for_path(path: Path) -> str:
    """Return the document id for the bytes currently stored at ``path``.

    The file is read and is not modified.
    """
    return document_id(path.read_bytes())


def transaction_id(
    *,
    source_file: Path,
    posted_date: date,
    direction: TransactionDirection | str,
    amount: Decimal,
    currency: str,
    description: str,
    source_page: int | None = None,
    source_row: int | None = None,
) -> str:
    """Return a stable id for one statement row.

    The digest covers the statement path, posting date, direction, amount,
    currency, description, and source location. Parsing the same row again
    with the same values returns the same id.
    """
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be Decimal")
    direction_value = direction.value if isinstance(direction, TransactionDirection) else direction
    payload = "\n".join(
        _field(value)
        for value in (
            source_file.as_posix(),
            posted_date.isoformat(),
            direction_value.strip().lower(),
            _canonical_amount(amount),
            currency.strip().upper(),
            description.strip(),
            "" if source_page is None else str(source_page),
            "" if source_row is None else str(source_row),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _field(value: str) -> str:
    return f"{len(value)}:{value}"


def _canonical_amount(amount: Decimal) -> str:
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
