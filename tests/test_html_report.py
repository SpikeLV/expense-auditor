"""HTML bank-statement report from synthetic transactions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from expense_auditor.config import load_matching_settings
from expense_auditor.models.document import Document, DocumentType
from expense_auditor.models.match import Match, MatchedDocument, MatchStatus
from expense_auditor.models.reconciliation import (
    ReconciledTransaction,
    build_reconciliation_result,
)
from expense_auditor.models.transaction import Transaction, TransactionDirection
from expense_auditor.reporting.html import write_html_report

_STATEMENT = Path("statement.pdf")
_POSTED = date(2026, 9, 1)


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.links: list[tuple[str, str]] = []
        self._in_body = False
        self._cells: list[str] = []
        self._capture = False
        self._text: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tbody":
            self._in_body = True
        if tag == "tr" and self._in_body:
            self._cells = []
        if tag == "td" and self._in_body:
            self._capture = True
            self._text = []
        if tag == "a" and self._capture:
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append(("".join(self._link_text), self._href))
            self._href = None
        if tag == "td" and self._capture:
            self._cells.append("".join(self._text).strip())
            self._capture = False
        if tag == "tr" and self._in_body and self._cells:
            self.rows.append(self._cells)
        if tag == "tbody":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)
        if self._href is not None:
            self._link_text.append(data)


def _transaction(
    transaction_id: str,
    merchant: str,
    amount: str,
    *,
    direction: TransactionDirection = TransactionDirection.OUTGOING,
    posted: date = _POSTED,
) -> Transaction:
    return Transaction.model_validate(
        {
            "id": transaction_id,
            "posted_date": posted,
            "direction": direction,
            "amount": Decimal(amount),
            "currency": "EUR",
            "description": merchant,
            "merchant_raw": merchant,
            "source_file": _STATEMENT,
        }
    )


def _document(path: Path, merchant: str, amount: str) -> Document:
    path.write_bytes(b"original-invoice")
    return Document.model_validate(
        {
            "id": path.stem,
            "filepath": path,
            "document_type": DocumentType.PDF,
            "merchant_raw": merchant,
            "amount": Decimal(amount),
            "currency": "EUR",
            "issued_date": _POSTED,
        }
    )


def _confirmed(transaction: Transaction, documents: tuple[Document, ...]) -> ReconciledTransaction:
    return ReconciledTransaction(
        transaction=transaction,
        match=Match(
            transaction_id=transaction.id,
            status=MatchStatus.CONFIRMED,
            score=load_matching_settings().confirmed_threshold,
            documents=tuple(
                MatchedDocument(document_id=document.id, amount_exact=True)
                for document in documents
            ),
            group_amount_exact=len(documents) > 1,
        ),
        documents=documents,
    )


def _probable(transaction: Transaction, document: Document) -> ReconciledTransaction:
    return ReconciledTransaction(
        transaction=transaction,
        match=Match(
            transaction_id=transaction.id,
            status=MatchStatus.PROBABLE,
            score=0.7,
            documents=(MatchedDocument(document_id=document.id, amount_exact=True),),
        ),
        documents=(document,),
    )


def _missing(transaction: Transaction) -> ReconciledTransaction:
    return ReconciledTransaction(
        transaction=transaction,
        match=Match(
            transaction_id=transaction.id,
            status=MatchStatus.MISSING,
            score=0,
            reason="No supporting document found with sufficient evidence.",
        ),
    )


def test_html_report_shows_status_and_document_links(tmp_path: Path) -> None:
    identified = _transaction("txn-rd", "RD ELECTRONICS", "477.99")
    combined = _transaction("txn-cloud", "DIGITALOCEAN.COM", "29.49", posted=date(2026, 9, 2))
    unknown = _transaction("txn-bank", "SEB banka", "8.00", posted=date(2026, 9, 4))
    missing = _transaction("txn-wave", "WAVESHARE", "52.31", posted=date(2026, 9, 2))
    incoming = _transaction(
        "txn-in",
        "CLIENT",
        "100.00",
        direction=TransactionDirection.INCOMING,
        posted=date(2026, 9, 3),
    )
    invoice = _document(tmp_path / "invoice_001.pdf", "RD ELECTRONICS", "477.99")
    part_a = _document(tmp_path / "invoice_002.pdf", "DIGITALOCEAN.COM", "20.00")
    part_b = _document(tmp_path / "invoice_003.pdf", "DIGITALOCEAN.COM", "9.49")
    probable_doc = _document(tmp_path / "maybe.pdf", "SEB banka", "8.00")
    original = (tmp_path / "invoice_001.pdf").read_bytes()
    result = build_reconciliation_result(
        (
            _confirmed(identified, (invoice,)),
            _confirmed(combined, (part_a, part_b)),
            _probable(unknown, probable_doc),
            _missing(missing),
        ),
        (invoice, part_a, part_b, probable_doc),
    )
    report = write_html_report(
        (identified, missing, incoming, unknown, combined),
        result,
        tmp_path / "report.html",
    )
    parsed = _Table()
    parsed.feed(report.read_text(encoding="utf-8"))
    rows = {row[1]: row for row in parsed.rows}

    assert [row[1] for row in parsed.rows] == [
        "RD ELECTRONICS",
        "WAVESHARE",
        "CLIENT",
        "SEB banka",
        "DIGITALOCEAN.COM",
    ]
    assert rows["RD ELECTRONICS"][2] == "477.99"
    assert rows["RD ELECTRONICS"][3] == "EUR"
    assert rows["RD ELECTRONICS"][4] == "IDENTIFIED"
    assert rows["RD ELECTRONICS"][5] == "invoice_001.pdf"
    assert rows["WAVESHARE"][4] == "NOT IDENTIFIED"
    assert rows["WAVESHARE"][5] == "—"
    assert rows["SEB banka"][4] == "UNKNOWN"
    assert rows["SEB banka"][5] == "—"
    assert rows["CLIENT"][4] == "UNKNOWN"
    assert rows["DIGITALOCEAN.COM"][4] == "IDENTIFIED"
    assert "invoice_002.pdf" in rows["DIGITALOCEAN.COM"][5]
    assert "invoice_003.pdf" in rows["DIGITALOCEAN.COM"][5]
    assert parsed.links == [
        ("invoice_001.pdf", "invoice_001.pdf"),
        ("invoice_002.pdf", "invoice_002.pdf"),
        ("invoice_003.pdf", "invoice_003.pdf"),
    ]
    assert (tmp_path / "invoice_001.pdf").read_bytes() == original
    assert invoice.filename == "invoice_001.pdf"
