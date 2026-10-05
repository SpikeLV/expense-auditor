"""Controlled matching cases. These tests do not read the bank statement PDF."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from expense_auditor.config import load_matching_settings
from expense_auditor.matching.matcher import match_transactions
from expense_auditor.matching.scoring import merchant_signal
from expense_auditor.models.document import Document, DocumentType
from expense_auditor.models.match import MatchStatus
from expense_auditor.models.transaction import Transaction, TransactionDirection

_POSTED = date(2026, 9, 10)
_STATEMENT = Path("statement.pdf")


def _transaction(
    transaction_id: str,
    amount: str,
    merchant: str,
    *,
    posted: date = _POSTED,
    currency: str = "EUR",
    direction: TransactionDirection = TransactionDirection.OUTGOING,
    description: str | None = None,
) -> Transaction:
    return Transaction.model_validate(
        {
            "id": transaction_id,
            "posted_date": posted,
            "direction": direction,
            "amount": Decimal(amount),
            "currency": currency,
            "description": description or merchant,
            "merchant_raw": merchant,
            "source_file": _STATEMENT,
        }
    )


def _document(
    document_id: str,
    amount: str | None,
    merchant: str | None,
    *,
    issued: date | None = _POSTED,
    currency: str | None = "EUR",
    invoice_number: str | None = None,
    extracted_text: str | None = None,
) -> Document:
    payload: dict[str, object] = {
        "id": document_id,
        "filepath": Path(f"{document_id}.pdf"),
        "document_type": DocumentType.PDF,
        "issued_date": issued,
        "currency": currency,
        "merchant_raw": merchant,
        "invoice_number": invoice_number,
        "extracted_text": extracted_text,
    }
    if amount is not None:
        payload["amount"] = Decimal(amount)
    return Document.model_validate(payload)


def _status(transaction: Transaction, *documents: Document) -> MatchStatus:
    result = match_transactions([transaction], documents)
    assert len(result.reconciled) == 1
    return result.reconciled[0].match.status


def test_exact_match_is_confirmed() -> None:
    transaction = _transaction("txn-exact", "100.00", "Amazon")
    document = _document("doc-exact", "100.00", "Amazon")

    result = match_transactions([transaction], [document])
    match = result.reconciled[0].match

    assert match.status is MatchStatus.CONFIRMED
    assert match.documents[0].document_id == "doc-exact"
    assert match.documents[0].amount_exact is True
    assert match.amount_score == 1.0
    assert match.currency_score == 1.0
    assert match.merchant_score is not None
    assert match.merchant_score >= load_matching_settings().merchant_bands.strong
    assert match.date_score == load_matching_settings().date_bands.same_day_score
    assert match.group_amount_exact is False
    assert match.reason is not None
    assert "Exact amount and currency" in match.reason
    assert "strong merchant match" in match.reason
    assert "Classified as CONFIRMED" in match.reason
    assert result.unmatched_documents() == ()


def test_different_currency_is_not_confirmed() -> None:
    transaction = _transaction("txn-eur", "100.00", "Amazon")
    document = _document("doc-usd", "100.00", "Amazon", currency="USD")

    result = match_transactions([transaction], [document])

    assert result.reconciled[0].match.status is MatchStatus.MISSING
    assert result.reconciled[0].match.documents == ()
    assert result.unmatched_documents() == (document,)


def test_date_distance_changes_confidence() -> None:
    settings = load_matching_settings()
    expected = {
        0: (MatchStatus.CONFIRMED, settings.date_bands.same_day_score),
        1: (MatchStatus.CONFIRMED, settings.date_bands.close_score),
        3: (MatchStatus.PROBABLE, settings.date_bands.near_score),
        5: (MatchStatus.PROBABLE, settings.date_bands.outer_score),
        7: (MatchStatus.PROBABLE, 0.0),
    }
    for days, (status, date_score) in expected.items():
        transaction = _transaction("txn-date", "100.00", "Amazon", posted=_POSTED)
        document = _document(
            "doc-date",
            "100.00",
            "Amazon",
            issued=_POSTED - timedelta(days=days),
        )
        result = match_transactions([transaction], [document])
        match = result.reconciled[0].match
        assert match.status is status
        assert match.date_score == date_score
        assert match.documents[0].date_delta_days == days


def test_merchant_variations_are_strong() -> None:
    pairs = (
        ("AMAZON* NV3LD00P4", "Amazon"),
        ("BOLT.EU/R/2609200744", "Bolt"),
        ("BOLT.EU/R/2609200744", "Bolt Operations"),
        ("CARGURU", "CarGuru"),
        ("ALIBABA.COM", "Alibaba"),
    )
    for index, (bank_name, document_name) in enumerate(pairs):
        transaction = _transaction(f"txn-merchant-{index}", "18.40", bank_name)
        document = _document(f"doc-merchant-{index}", "18.40", document_name)
        assert _status(transaction, document) is MatchStatus.CONFIRMED


def test_short_merchant_is_not_strong() -> None:
    settings = load_matching_settings()
    signal = merchant_signal("CAR", "CARGURU", settings)

    assert signal is not None
    assert signal <= settings.merchant_bands.short_cap
    transaction = _transaction("txn-short", "12.00", "CAR")
    document = _document("doc-short", "12.00", "CARGURU")
    assert _status(transaction, document) is MatchStatus.MISSING


def test_reference_match_increases_confidence() -> None:
    transaction = _transaction(
        "txn-ref",
        "42.50",
        "ALPHA SUPPLIES",
        posted=_POSTED,
        description="Card payment INV-20481",
    )
    dated = _POSTED - timedelta(days=5)
    without = _document("doc-without", "42.50", "BETA SUPPLIES", issued=dated)
    with_invoice = _document(
        "doc-with",
        "42.50",
        "BETA SUPPLIES",
        issued=dated,
        invoice_number="INV-20481",
    )

    plain = match_transactions([transaction], [without]).reconciled[0].match
    linked = match_transactions([transaction], [with_invoice]).reconciled[0].match

    assert plain.status is MatchStatus.PROBABLE
    assert linked.status is MatchStatus.CONFIRMED
    assert plain.score is not None
    assert linked.score is not None
    assert linked.score > plain.score
    assert linked.reference_score == 1.0
    assert linked.reason is not None
    assert "invoice or reference text matches" in linked.reason


def test_missing_document() -> None:
    transaction = _transaction("txn-missing", "77.10", "GROCERY STORE")

    result = match_transactions([transaction], [])
    match = result.reconciled[0].match

    assert match.status is MatchStatus.MISSING
    assert match.documents == ()
    assert match.score == 0
    assert match.reason == "No supporting document found with sufficient evidence."


def test_same_amount_without_support_stays_missing() -> None:
    transaction = _transaction("txn-unrelated", "100.00", "NORTH WIND")
    document = _document("doc-unrelated", "100.00", "SOUTH DOCK")

    result = match_transactions([transaction], [document])

    assert result.reconciled[0].match.status is MatchStatus.MISSING
    assert result.unmatched_documents() == (document,)


def test_probable_match() -> None:
    transaction = _transaction("txn-probable", "42.50", "ALPHA SUPPLIES")
    document = _document(
        "doc-probable",
        "42.50",
        "BETA SUPPLIES",
        issued=_POSTED - timedelta(days=5),
    )

    result = match_transactions([transaction], [document])
    match = result.reconciled[0].match
    settings = load_matching_settings()

    assert match.status is MatchStatus.PROBABLE
    assert match.merchant_score is not None
    assert settings.merchant_bands.moderate <= match.merchant_score < settings.merchant_bands.strong
    assert match.date_score == settings.date_bands.outer_score
    assert match.reason is not None
    assert "merchant similarity is moderate" in match.reason
    assert "5 days before" in match.reason
    assert "Classified as PROBABLE" in match.reason


def test_missing_document_date_is_not_a_disqualification() -> None:
    transaction = _transaction("txn-undated", "100.00", "Amazon")
    document = _document("doc-undated", "100.00", "Amazon", issued=None)

    result = match_transactions([transaction], [document])
    match = result.reconciled[0].match

    assert match.status is MatchStatus.PROBABLE
    assert match.date_score is None
    assert match.documents[0].date_delta_days is None
    assert match.reason is not None
    assert "document date is missing" in match.reason


def test_combination_sums_to_the_transaction() -> None:
    transaction = _transaction("txn-combo", "100.00", "Office Depot")
    documents = (
        _document("doc-20", "20.00", "Office Depot"),
        _document("doc-30", "30.00", "Office Depot"),
        _document("doc-50", "50.00", "Office Depot"),
    )

    result = match_transactions([transaction], documents)
    match = result.reconciled[0].match

    assert match.status is MatchStatus.CONFIRMED
    assert match.group_amount_exact is True
    assert {item.document_id for item in match.documents} == {"doc-20", "doc-30", "doc-50"}
    assert all(item.amount_exact is False for item in match.documents)
    assert match.amount_score == 1.0
    assert match.currency_score == 1.0
    assert match.reason is not None
    assert "sum to the transaction amount" in match.reason
    assert result.unmatched_documents() == ()


def test_single_document_is_preferred_over_a_combination() -> None:
    transaction = _transaction("txn-prefer", "100.00", "Office Depot")
    single = _document("doc-full", "100.00", "Office Depot")
    parts = (
        _document("doc-20", "20.00", "Office Depot"),
        _document("doc-30", "30.00", "Office Depot"),
        _document("doc-50", "50.00", "Office Depot"),
    )

    result = match_transactions([transaction], (single, *parts))
    match = result.reconciled[0].match

    assert match.status is MatchStatus.CONFIRMED
    assert [item.document_id for item in match.documents] == ["doc-full"]
    assert {item.id for item in result.unmatched_documents()} == {"doc-20", "doc-30", "doc-50"}


def test_combination_rejects_mixed_currency() -> None:
    transaction = _transaction("txn-mixed", "100.00", "Parts Shop")
    euro = _document("doc-euro", "20.00", "Parts Shop")
    dollar = _document("doc-usd", "80.00", "Parts Shop", currency="USD")

    result = match_transactions([transaction], [euro, dollar])

    assert result.reconciled[0].match.status is MatchStatus.MISSING
    assert {item.id for item in result.unmatched_documents()} == {"doc-euro", "doc-usd"}


def test_document_is_not_reused_silently() -> None:
    first = _transaction("txn-a", "100.00", "Amazon")
    second = _transaction("txn-b", "100.00", "Amazon")
    document = _document("doc-shared", "100.00", "Amazon")

    result = match_transactions([first, second], [document])
    rows = {row.transaction.id: row for row in result.reconciled}

    assert rows["txn-a"].match.status is MatchStatus.CONFIRMED
    assert rows["txn-b"].match.status is MatchStatus.MISSING
    assert rows["txn-b"].match.reason is not None
    assert "doc-shared" in rows["txn-b"].match.reason
    assert "already used by transaction txn-a" in rows["txn-b"].match.reason
    assert result.document_references[0].transactions == (first,)


def test_unmatched_document_is_reported() -> None:
    transaction = _transaction("txn-used", "15.00", "Amazon")
    used = _document("doc-used", "15.00", "Amazon")
    unused = _document("doc-unused", "9.99", "Unused Shop")

    result = match_transactions([transaction], [used, unused])

    assert result.reconciled[0].match.status is MatchStatus.CONFIRMED
    assert result.unmatched_documents() == (unused,)
    assert result.summary().unmatched_document_count == 1


def test_incoming_transactions_are_excluded() -> None:
    incoming = _transaction(
        "txn-in",
        "500.00",
        "Salary",
        direction=TransactionDirection.INCOMING,
    )
    receipt = _document("doc-salary", "500.00", "Salary")
    outgoing = _transaction("txn-out", "15.00", "Amazon")
    receipt_out = _document("doc-amazon", "15.00", "Amazon")

    result = match_transactions([incoming, outgoing], [receipt, receipt_out])

    assert [row.transaction.id for row in result.reconciled] == ["txn-out"]
    assert result.reconciled[0].match.status is MatchStatus.CONFIRMED
    assert {item.id for item in result.unmatched_documents()} == {"doc-salary"}


def test_reconciliation_covers_each_outcome() -> None:
    confirmed = _transaction("txn-confirmed", "103.51", "AMAZON* NV3LD00P4")
    probable = _transaction("txn-probable", "42.50", "ALPHA SUPPLIES")
    missing = _transaction("txn-missing", "77.10", "GROCERY STORE")
    combo = _transaction("txn-combo", "100.00", "Office Depot")
    incoming = _transaction(
        "txn-incoming",
        "1834.71",
        "Client Payment",
        direction=TransactionDirection.INCOMING,
    )
    documents = (
        _document("doc-amazon", "103.51", "Amazon"),
        _document(
            "doc-beta",
            "42.50",
            "BETA SUPPLIES",
            issued=_POSTED - timedelta(days=5),
        ),
        _document("doc-20", "20.00", "Office Depot"),
        _document("doc-30", "30.00", "Office Depot"),
        _document("doc-50", "50.00", "Office Depot"),
        _document("doc-orphan", "9.99", "Unused Shop"),
    )

    result = match_transactions(
        [confirmed, probable, missing, combo, incoming],
        documents,
    )
    rows = {row.transaction.id: row for row in result.reconciled}

    assert [row.transaction.id for row in result.reconciled] == [
        "txn-confirmed",
        "txn-probable",
        "txn-missing",
        "txn-combo",
    ]
    assert rows["txn-confirmed"].match.status is MatchStatus.CONFIRMED
    assert [item.document_id for item in rows["txn-confirmed"].match.documents] == ["doc-amazon"]
    assert rows["txn-probable"].match.status is MatchStatus.PROBABLE
    assert rows["txn-missing"].match.status is MatchStatus.MISSING
    assert rows["txn-missing"].match.documents == ()
    assert rows["txn-combo"].match.status is MatchStatus.CONFIRMED
    assert rows["txn-combo"].match.group_amount_exact is True
    assert {item.document_id for item in rows["txn-combo"].match.documents} == {
        "doc-20",
        "doc-30",
        "doc-50",
    }
    assert [item.id for item in result.unmatched_documents()] == ["doc-orphan"]
    summary = result.summary()
    assert summary.outgoing_count == 4
    assert summary.confirmed_count == 2
    assert summary.probable_count == 1
    assert summary.missing_count == 1
    assert summary.unmatched_document_count == 1
