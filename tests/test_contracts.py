"""Seams introduced for the V0.1 contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from expense_auditor.bank.base import BankStatementParser, reconciliation_transactions
from expense_auditor.config import ConfigError, load_app_config, load_matching_settings
from expense_auditor.documents.fields import (
    document_from_content,
    document_from_path,
    extract_document_fields,
)
from expense_auditor.documents.scanner import ScannedDocument
from expense_auditor.identity import document_id, transaction_id
from expense_auditor.matching.validation import (
    MatchValidationError,
    currency_safe_amount_equal,
    ensure_confirmed,
)
from expense_auditor.models import (
    Document,
    DocumentType,
    ExtractionMethod,
    Match,
    MatchedDocument,
    MatchStatus,
    ReconciledTransaction,
    Transaction,
    TransactionDirection,
    build_reconciliation_result,
)
from expense_auditor.models.document import normalize_document
from expense_auditor.models.transaction import normalize_transaction
from expense_auditor.normalization.amount import AmountParseError, parse_amount
from expense_auditor.normalization.date import DateParseError, parse_date
from expense_auditor.pipeline import v01_pipeline

_PROJECT = Path(__file__).resolve().parents[1]
_STATEMENT = Path("data/bank/statement.pdf")


def _document(document_id_value: str, **overrides: object) -> Document:
    payload: dict[str, object] = {
        "id": document_id_value,
        "filepath": Path(f"{document_id_value}.pdf"),
        "document_type": DocumentType.PDF,
    }
    payload.update(overrides)
    return Document.model_validate(payload)


def _transaction(
    direction: TransactionDirection = TransactionDirection.OUTGOING,
    **overrides: object,
) -> Transaction:
    payload: dict[str, object] = {
        "id": f"txn-{direction.value}",
        "posted_date": date(2026, 10, 4),
        "direction": direction,
        "amount": Decimal("10.00"),
        "currency": "EUR",
        "description": "CARD PAYMENT",
        "source_file": _STATEMENT,
    }
    payload.update(overrides)
    return Transaction.model_validate(payload)


def test_multiline_text_yields_field_candidates() -> None:
    text = "\n".join(
        (
            "Supplier: Rimi Latvia SIA",
            "Invoice: INV-9",
            "Issued 04.10.2026",
            "Subtotal 10.00 EUR",
            "Total 12.50 EUR",
        )
    )
    with pytest.raises(AmountParseError):
        parse_amount(text)
    with pytest.raises(DateParseError):
        parse_date(text)

    fields = extract_document_fields(text)
    document = document_from_content(
        filepath=Path("receipt.pdf"),
        content=b"receipt-bytes",
        document_type=DocumentType.PDF,
        extracted_text=text,
        extraction_method=ExtractionMethod.PDF_TEXT,
    )

    assert fields.issued_date == date(2026, 10, 4)
    assert fields.amount == Decimal("12.50")
    assert fields.currency == "EUR"
    assert fields.merchant_raw == "Rimi Latvia SIA"
    assert fields.invoice_number == "INV-9"
    assert document.issued_date == fields.issued_date
    assert document.amount == fields.amount
    assert document.currency == fields.currency
    assert document.merchant_raw == fields.merchant_raw
    assert document.merchant_normalized == "RIMI LATVIA"
    assert document.invoice_number == fields.invoice_number
    assert document.extracted_text == text
    assert document.extraction_method is ExtractionMethod.PDF_TEXT


def test_missing_document_fields_stay_absent() -> None:
    fields = extract_document_fields("Thank you for visiting\nINV-9\n")

    assert fields.issued_date is None
    assert fields.amount is None
    assert fields.currency is None
    assert fields.merchant_raw is None
    assert fields.invoice_number is None


def test_conflicting_dates_and_unlabeled_amounts_are_not_chosen() -> None:
    dated = extract_document_fields("04.10.2026\n05.10.2026\n")
    priced = extract_document_fields("10.00 EUR\n12.00 EUR\n")
    unlabeled_name = extract_document_fields("Rimi Latvia SIA\nTotal 10.00 EUR\n")
    bare_total = extract_document_fields("Total 43.21\n")

    assert dated.issued_date is None
    assert priced.amount is None
    assert priced.currency is None
    assert unlabeled_name.merchant_raw is None
    assert unlabeled_name.amount == Decimal("10.00")
    assert unlabeled_name.currency == "EUR"
    assert bare_total.amount == Decimal("43.21")
    assert bare_total.currency is None


def test_same_file_bytes_produce_the_same_document_id(tmp_path: Path) -> None:
    payload = b"%PDF-1.4 same-bytes"
    path = tmp_path / "receipt.pdf"
    path.write_bytes(payload)
    modified_at = path.stat().st_mtime_ns
    text = "Total 10.00 EUR"
    first = document_from_path(
        path,
        extracted_text=text,
        extraction_method=ExtractionMethod.PDF_TEXT,
        document_type=DocumentType.PDF,
    )
    second = document_from_path(
        path,
        extracted_text=text,
        extraction_method=ExtractionMethod.PDF_TEXT,
        document_type=DocumentType.PDF,
    )
    copy = tmp_path / "copy.pdf"
    copy.write_bytes(payload)
    copied = document_from_path(
        copy,
        extracted_text="different text does not change the content id",
        extraction_method=ExtractionMethod.OCR,
        document_type=DocumentType.PDF,
    )
    changed = document_from_content(
        filepath=path,
        content=payload + b"x",
        document_type=DocumentType.PDF,
        extracted_text=text,
        extraction_method=ExtractionMethod.PDF_TEXT,
    )

    assert first.id == second.id == copied.id == document_id(payload)
    assert first.file_hash == first.id
    assert changed.id != first.id
    assert path.read_bytes() == payload
    assert path.stat().st_mtime_ns == modified_at
    assert "id" not in ScannedDocument.model_fields


def _sample_transaction_id(amount: Decimal) -> str:
    return transaction_id(
        source_file=_STATEMENT,
        posted_date=date(2026, 10, 4),
        direction=TransactionDirection.OUTGOING,
        amount=amount,
        currency="eur",
        description=" CARD PAYMENT ",
        source_page=1,
        source_row=4,
    )


def test_transaction_id_is_stable_for_the_same_row() -> None:
    assert _sample_transaction_id(Decimal("19.90")) == _sample_transaction_id(Decimal("19.9"))
    assert _sample_transaction_id(Decimal("19.91")) != _sample_transaction_id(Decimal("19.90"))


def test_reconciliation_keeps_only_outgoing_transactions() -> None:
    class _Rows:
        def parse(self, source_file: Path) -> list[Transaction]:
            rows: list[Transaction] = []
            samples = (
                (TransactionDirection.OUTGOING, "CARD", 1),
                (TransactionDirection.INCOMING, "SALARY", 2),
                (TransactionDirection.UNKNOWN, "UNCLASSIFIED", 3),
            )
            for direction, description, row_number in samples:
                amount = Decimal("10.00")
                posted = date(2026, 10, 4)
                rows.append(
                    Transaction(
                        id=transaction_id(
                            source_file=source_file,
                            posted_date=posted,
                            direction=direction,
                            amount=amount,
                            currency="EUR",
                            description=description,
                            source_page=1,
                            source_row=row_number,
                        ),
                        posted_date=posted,
                        direction=direction,
                        amount=amount,
                        currency="EUR",
                        description=description,
                        source_file=source_file,
                        source_page=1,
                        source_row=row_number,
                    )
                )
            return rows

    parser: BankStatementParser = _Rows()
    first = parser.parse(_STATEMENT)
    second = parser.parse(_STATEMENT)

    assert [item.id for item in first] == [item.id for item in second]
    assert {item.source_file for item in first} == {_STATEMENT}
    assert first[2].direction is TransactionDirection.UNKNOWN
    assert [item.direction for item in reconciliation_transactions(first)] == [
        TransactionDirection.OUTGOING
    ]


def test_currency_safe_amount_match_requires_the_same_currency() -> None:
    tolerance = load_matching_settings().amount_tolerance

    assert (
        currency_safe_amount_equal(
            Decimal("10.00"),
            "EUR",
            Decimal("10.00"),
            "GBP",
            tolerance=tolerance,
        )
        is False
    )
    assert (
        currency_safe_amount_equal(
            Decimal("10.00"),
            "EUR",
            Decimal("10.00"),
            None,
            tolerance=tolerance,
        )
        is None
    )
    assert (
        currency_safe_amount_equal(
            Decimal("10.00"),
            None,
            Decimal("10.00"),
            "EUR",
            tolerance=tolerance,
        )
        is None
    )
    assert (
        currency_safe_amount_equal(
            Decimal("10.00"),
            "EUR",
            Decimal("10.00"),
            "EUR",
            tolerance=tolerance,
        )
        is True
    )


def test_confirmed_match_rejects_weak_evidence() -> None:
    settings = load_matching_settings()
    low_score = settings.confirmed_threshold / 2

    with pytest.raises(MatchValidationError, match="currency-safe"):
        ensure_confirmed(
            score=settings.confirmed_threshold,
            amount_exact=(False,),
            settings=settings,
        )
    with pytest.raises(ValidationError, match="currency-safe"):
        Match(
            transaction_id="txn-1",
            status=MatchStatus.CONFIRMED,
            score=settings.confirmed_threshold,
            documents=(MatchedDocument(document_id="doc-1", amount_exact=None),),
        )
    with pytest.raises(ValidationError, match="threshold"):
        Match(
            transaction_id="txn-1",
            status=MatchStatus.CONFIRMED,
            score=low_score,
            documents=(MatchedDocument(document_id="doc-1", amount_exact=True),),
        )


def test_normalized_merchant_is_ready_before_matching() -> None:
    transaction = _transaction(
        description="CARD  RIMI LATVIA",
        merchant_raw=" Rimi Latvia SIA ",
    )
    document = _document("doc-1", merchant_raw=" Rimi Latvia SIA ")
    constructed = Transaction.model_construct(
        id="txn-raw",
        posted_date=date(2026, 10, 4),
        direction=TransactionDirection.OUTGOING,
        amount=Decimal("10.00"),
        currency="EUR",
        description="CARD  RIMI LATVIA",
        merchant_raw="Rimi Latvia SIA",
        merchant_normalized=None,
        source_file=_STATEMENT,
        source_page=None,
        source_row=None,
    )
    prepared = normalize_transaction(constructed)

    assert transaction.merchant_raw == "Rimi Latvia SIA"
    assert transaction.merchant_normalized == "RIMI LATVIA"
    assert transaction.description == "CARD  RIMI LATVIA"
    assert document.merchant_raw == "Rimi Latvia SIA"
    assert document.merchant_normalized == "RIMI LATVIA"
    assert prepared.merchant_normalized == "RIMI LATVIA"
    assert prepared.description == "CARD  RIMI LATVIA"
    assert normalize_document(document) == document
    with pytest.raises(ValidationError, match="merchant_normalized"):
        _document("doc-2", merchant_raw="Acme Ltd", merchant_normalized="ACME LTD")


def test_reconciliation_result_keeps_document_links() -> None:
    settings = load_matching_settings()
    outgoing = _transaction(id="txn-out", description="CARD ACME")
    first = _document("doc-a", invoice_number="A")
    second = _document("doc-b", invoice_number="B")
    unused = _document("doc-c", invoice_number="C")
    match = Match(
        transaction_id=outgoing.id,
        status=MatchStatus.CONFIRMED,
        score=settings.confirmed_threshold,
        documents=(
            MatchedDocument(document_id=first.id, amount_exact=True),
            MatchedDocument(document_id=second.id, amount_exact=True),
        ),
    )
    row = ReconciledTransaction(transaction=outgoing, match=match, documents=(first, second))
    result = build_reconciliation_result((row,), (first, second, unused))

    assert [item.invoice_number for item in result.reconciled[0].documents] == ["A", "B"]
    assert [item.invoice_number for item in result.unmatched_documents()] == ["C"]
    assert result.document_references[0].transactions[0].description == "CARD ACME"
    assert result.document_references[1].transactions[0].description == "CARD ACME"
    assert result.document_references[2].transactions == ()
    summary = result.summary()
    assert summary.outgoing_count == 1
    assert summary.confirmed_count == 1
    assert summary.probable_count == 0
    assert summary.missing_count == 0
    assert summary.unmatched_document_count == 1
    with pytest.raises(ValidationError, match="outgoing"):
        ReconciledTransaction(
            transaction=_transaction(TransactionDirection.INCOMING),
            match=Match(
                transaction_id="txn-incoming",
                status=MatchStatus.MISSING,
            ),
            documents=(),
        )


def test_matching_thresholds_are_loaded_from_config() -> None:
    settings = load_matching_settings()
    app_config = load_app_config()

    assert settings.confirmed_threshold == 0.85
    assert settings.probable_threshold == 0.60
    assert settings.date_tolerance_days == 5
    assert settings.amount_tolerance == Decimal("0.00")
    assert app_config.paths.data_root == Path("data")
    assert app_config.paths.reports_root == Path("reports")
    assert app_config.ocr.language == "eng+lav"
    for relative in (
        "src/expense_auditor/matching/matcher.py",
        "src/expense_auditor/matching/scoring.py",
        "src/expense_auditor/matching/validation.py",
    ):
        source = (_PROJECT / relative).read_text(encoding="utf-8")
        assert "0.85" not in source
        assert "0.60" not in source
    validation_path = _PROJECT / "src/expense_auditor/matching/validation.py"
    assert "confirmed_threshold" in validation_path.read_text(encoding="utf-8")
    bank_parser = _PROJECT / "src/expense_auditor/bank/base.py"
    assert "extract_pdf_text" not in bank_parser.read_text(encoding="utf-8")
    pdf_text = _PROJECT / "src/expense_auditor/documents/pdf_parser.py"
    assert "extract_document_fields" not in pdf_text.read_text(encoding="utf-8")


def test_amount_tolerance_must_not_be_a_float(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            (
                "matching:",
                "  confirmed_threshold: 0.85",
                "  probable_threshold: 0.60",
                "  date_tolerance_days: 5",
                "  amount_tolerance: 0.00",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_matching_settings(path)


def test_v01_pipeline_names_each_boundary() -> None:
    stages = v01_pipeline()

    assert [stage.name for stage in stages] == [
        "scan_documents",
        "extract_document_content",
        "extract_document_fields",
        "normalize_document_fields",
        "parse_bank_statement",
        "normalize_transactions",
        "match_transactions",
        "build_reconciliation_result",
        "render_reports",
    ]
    assert [stage.order for stage in stages] == list(range(1, 10))
    assert [stage.implemented for stage in stages] == [
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
    ]
