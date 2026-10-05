"""Regression tests for the SEB Konta pārskats parser.

Expected rows come from parsing ``data/samples/bank/kontaparskats.pdf``.
The tests do not substitute a hand-written transaction list for that file.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest

from expense_auditor.bank.base import reconciliation_transactions
from expense_auditor.bank.errors import BankStatementFormatError
from expense_auditor.bank.pdf_parser import SebBankStatementParser, inspect_statement, parse
from expense_auditor.models.transaction import Transaction, TransactionDirection

_SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples" / "bank" / "kontaparskats.pdf"


@pytest.fixture(scope="module")
def transactions() -> list[Transaction]:
    return parse(_SAMPLE)


def test_sample_pdf_opens_with_the_statement_page_count() -> None:
    document = pymupdf.open(_SAMPLE)
    try:
        assert document.page_count == 8
        assert document[0].rect.width == pytest.approx(595)
        assert document[0].rect.height == pytest.approx(842)
    finally:
        document.close()


def test_statement_format_is_recognized(transactions: list[Transaction]) -> None:
    summary = inspect_statement(_SAMPLE)

    assert summary.startswith("Bank statement format: RECOGNIZED\n")
    assert "Pages: 8\n" in summary
    assert "Transaction pages: 1-7\n" in summary
    assert "Transactions detected: 92\n" in summary
    assert "Outgoing: 67\n" in summary
    assert "Incoming: 25\n" in summary
    assert "Opening balance: 1423.70 EUR\n" in summary
    assert "Closing balance: 1544.38 EUR\n" in summary
    assert "Positional extraction: YES\n" in summary
    assert summary.endswith("OCR: NO")
    assert len(transactions) == 92


def test_first_transaction_is_the_multiline_electronics_payment(
    transactions: list[Transaction],
) -> None:
    first = transactions[0]

    assert first.posted_date == date(2026, 9, 1)
    assert first.direction is TransactionDirection.OUTGOING
    assert first.amount == Decimal("477.99")
    assert first.currency == "EUR"
    assert first.merchant_raw == "RD ELECTRONICS"
    assert first.merchant_normalized == "RD ELECTRONICS"
    assert first.source_page == 1
    assert first.source_row == 1
    assert "RO2005712620L01/ /" in first.description
    assert "CLR8877173" in first.description
    assert "UNLALV2X" in first.description
    assert "ELECTRONICS/RIGA/LVA #537073" in first.description
    assert "\n" in first.description


def test_middle_transaction_is_the_europcar_card_payment(
    transactions: list[Transaction],
) -> None:
    middle = transactions[len(transactions) // 2]

    assert middle.posted_date == date(2026, 9, 21)
    assert middle.direction is TransactionDirection.OUTGOING
    assert middle.amount == Decimal("344.47")
    assert middle.currency == "EUR"
    assert middle.merchant_raw == "Europcar"
    assert middle.source_page == 4
    assert "2500.00 DKK" in middle.description


def test_incoming_payment_stays_incoming(transactions: list[Transaction]) -> None:
    incoming = next(
        transaction
        for transaction in transactions
        if transaction.merchant_raw is not None and "ARETE TECHNOLOGIES" in transaction.merchant_raw
    )

    assert incoming.posted_date == date(2026, 9, 3)
    assert incoming.direction is TransactionDirection.INCOMING
    assert incoming.amount == Decimal("1834.71")
    assert incoming.currency == "EUR"
    assert "RO2007095853L02/ /" in incoming.description


def test_last_transaction_and_direction_counts(transactions: list[Transaction]) -> None:
    last = transactions[-1]
    outgoing = [
        transaction
        for transaction in transactions
        if transaction.direction is TransactionDirection.OUTGOING
    ]
    incoming = [
        transaction
        for transaction in transactions
        if transaction.direction is TransactionDirection.INCOMING
    ]

    assert last.posted_date == date(2026, 9, 30)
    assert last.direction is TransactionDirection.INCOMING
    assert last.amount == Decimal("48.65")
    assert last.currency == "EUR"
    assert last.merchant_raw == "LUDMILA ČERGEIKO 070383-12758"
    assert last.source_page == 7
    assert last.source_row == 92
    assert "RO2024394398L02/ /" in last.description
    assert "Kļūdains maksājums" in last.description
    assert len(outgoing) == 67
    assert len(incoming) == 25
    assert len(reconciliation_transactions(transactions)) == 67


def test_balances_and_totals_are_not_transactions(transactions: list[Transaction]) -> None:
    descriptions = "\n".join(transaction.description for transaction in transactions)

    assert "Sākuma atlikums" not in descriptions
    assert "Beigu atlikums" not in descriptions
    assert "Kopā izskaitīts" not in descriptions
    assert "Kopā ieskaitīts" not in descriptions
    assert "Overdrafta" not in descriptions
    assert "KONTA PĀRSKATS" not in descriptions
    opening = Decimal("1423.70")
    closing = Decimal("1544.38")
    incoming = sum(
        (
            transaction.amount
            for transaction in transactions
            if transaction.direction is TransactionDirection.INCOMING
        ),
        Decimal("0"),
    )
    outgoing = sum(
        (
            transaction.amount
            for transaction in transactions
            if transaction.direction is TransactionDirection.OUTGOING
        ),
        Decimal("0"),
    )
    assert opening + incoming - outgoing == closing


def test_transaction_ids_and_source_files_are_stable() -> None:
    parser = SebBankStatementParser()
    first_pass = parser.parse(_SAMPLE)
    second_pass = parser.parse(_SAMPLE)

    assert [transaction.id for transaction in first_pass] == [
        transaction.id for transaction in second_pass
    ]
    assert all(transaction.source_file == _SAMPLE for transaction in first_pass)
    assert all(transaction.currency == "EUR" for transaction in first_pass)
    assert len({transaction.id for transaction in first_pass}) == len(first_pass)


def test_a_different_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "note.pdf"
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "This is not a bank statement")
        document.save(path)
    finally:
        document.close()

    with pytest.raises(BankStatementFormatError):
        parse(path)
