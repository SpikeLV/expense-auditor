"""Compare invoices required by a contract with files found beside it."""

from __future__ import annotations

from collections.abc import Sequence

from expense_auditor.contract.analyzer import ExpectedInvoice
from expense_auditor.documents.parser import FoundInvoice


def match_invoices(
    expected: Sequence[ExpectedInvoice],
    found: Sequence[FoundInvoice],
) -> tuple[tuple[ExpectedInvoice, ...], tuple[ExpectedInvoice, ...]]:
    """Return the expected invoices that were found, then those still missing.

    A file is used for at most one expected invoice. Period and amount must
    agree, unless both sides state the same invoice number.
    """
    unused = list(found)
    matched: list[ExpectedInvoice] = []
    missing: list[ExpectedInvoice] = []
    for invoice in expected:
        choice = next((item for item in unused if _is_clear_match(invoice, item)), None)
        if choice is None:
            missing.append(invoice)
            continue
        unused.remove(choice)
        matched.append(invoice)
    return tuple(matched), tuple(missing)


def _is_clear_match(expected: ExpectedInvoice, found: FoundInvoice) -> bool:
    numbers_agree = _numbers_agree(expected.invoice_number, found.invoice_number)
    if numbers_agree is False:
        return False
    if _amounts_conflict(expected, found) or _currencies_conflict(expected, found):
        return False
    if numbers_agree is True:
        return True
    if expected.period is None or found.period != expected.period:
        return False
    if expected.amount is None or found.amount is None or found.amount != expected.amount:
        return False
    if expected.currency and not found.currency:
        return False
    return True


def _numbers_agree(expected: str | None, found: str | None) -> bool | None:
    if not expected or not found:
        return None
    if _compact(expected) == _compact(found):
        return True
    return False


def _amounts_conflict(expected: ExpectedInvoice, found: FoundInvoice) -> bool:
    if expected.amount is None or found.amount is None:
        return False
    return expected.amount != found.amount


def _currencies_conflict(expected: ExpectedInvoice, found: FoundInvoice) -> bool:
    if not expected.currency or not found.currency:
        return False
    return expected.currency != found.currency


def _compact(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())
