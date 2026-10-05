"""A single HTML table of bank transactions and their document matches.

Statuses come from the existing reconciliation result:

* confirmed → IDENTIFIED
* missing → NOT IDENTIFIED
* probable, incoming, or unknown direction → UNKNOWN
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from expense_auditor.bank.errors import BankStatementFormatError
from expense_auditor.bank.pdf_parser import parse
from expense_auditor.documents.fields import document_from_path
from expense_auditor.documents.parser import read_document_text
from expense_auditor.documents.scanner import scan_documents
from expense_auditor.matching.matcher import match_transactions
from expense_auditor.models.document import Document, DocumentType, ExtractionMethod
from expense_auditor.models.match import MatchStatus
from expense_auditor.models.reconciliation import ReconciledTransaction, ReconciliationResult
from expense_auditor.models.transaction import Transaction, TransactionDirection

_IDENTIFIED = "IDENTIFIED"
_NOT_IDENTIFIED = "NOT IDENTIFIED"
_UNKNOWN = "UNKNOWN"
_STATEMENT_NAME = re.compile(r"(?i)(kontaparskats|parskats|pārskats|statement)")


def write_html_report(
    transactions: Sequence[Transaction],
    result: ReconciliationResult,
    output_path: Path,
) -> Path:
    """Write ``report.html`` for ``transactions`` and return its path.

    Document links point at the original files. Those files are not copied.
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_render(transactions, result, destination), encoding="utf-8")
    return destination


def write_folder_statement_report(folder: Path) -> Path | None:
    """Parse a statement in ``folder``, match the other files, and write ``report.html``.

    Returns ``None`` when the folder has no statement-named PDF. A filename
    contains ``statement`` or ``parskats``.
    """
    root = Path(folder)
    candidates = [
        item.filepath
        for item in scan_documents(root)
        if item.document_type is DocumentType.PDF and _STATEMENT_NAME.search(item.filepath.name)
    ]
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise BankStatementFormatError(f"several bank statements found: {names}")
    statement = candidates[0]
    transactions = parse(statement)
    documents = _supporting_documents(root, statement)
    result = match_transactions(transactions, documents)
    return write_html_report(transactions, result, root / "report.html")


def _supporting_documents(folder: Path, statement: Path) -> tuple[Document, ...]:
    statement_path = statement.resolve()
    documents: list[Document] = []
    for scanned in scan_documents(folder):
        if scanned.filepath.resolve() == statement_path:
            continue
        method = (
            ExtractionMethod.PDF_TEXT
            if scanned.document_type is DocumentType.PDF
            else ExtractionMethod.OCR
        )
        documents.append(
            document_from_path(
                scanned.filepath,
                extracted_text=read_document_text(scanned.filepath),
                extraction_method=method,
                document_type=scanned.document_type,
            )
        )
    return tuple(documents)


def _render(
    transactions: Sequence[Transaction],
    result: ReconciliationResult,
    report_path: Path,
) -> str:
    matched = {row.transaction.id: row for row in result.reconciled}
    body = "\n".join(
        _row(transaction, matched.get(transaction.id), report_path) for transaction in transactions
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bank statement</title>
<style>
body {{ font-family: "Segoe UI", sans-serif; margin: 24px; color: #1a1a1a; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: 8px 12px; border-bottom: 1px solid #d9e2ef; vertical-align: top; }}
th {{ position: sticky; top: 0; background: #1f4e79; color: #fff; text-align: left; }}
td.amount {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr:nth-child(even) td {{ background: #f7f9fc; }}
.identified {{ color: #006100; font-weight: 650; }}
.not-identified {{ color: #9c0006; font-weight: 650; }}
.unknown {{ color: #9c5700; font-weight: 650; }}
a {{ color: #0b57d0; }}
</style>
</head>
<body>
<table>
<thead>
<tr>
<th>Date</th><th>Description</th><th>Amount</th><th>Currency</th><th>Status</th><th>Document</th>
</tr>
</thead>
<tbody>
{body}
</tbody>
</table>
</body>
</html>
"""


def _row(
    transaction: Transaction,
    reconciled: ReconciledTransaction | None,
    report_path: Path,
) -> str:
    status, documents = _status_and_documents(transaction, reconciled)
    css = status.lower().replace(" ", "-")
    return (
        "<tr>"
        f"<td>{html.escape(transaction.posted_date.isoformat())}</td>"
        f"<td>{html.escape(_description(transaction))}</td>"
        f'<td class="amount">{html.escape(_amount(transaction.amount))}</td>'
        f"<td>{html.escape(transaction.currency)}</td>"
        f'<td class="{css}">{html.escape(status)}</td>'
        f"<td>{_documents(documents, report_path)}</td>"
        "</tr>"
    )


def _status_and_documents(
    transaction: Transaction,
    reconciled: ReconciledTransaction | None,
) -> tuple[str, tuple[Document, ...]]:
    if transaction.direction is not TransactionDirection.OUTGOING or reconciled is None:
        return _UNKNOWN, ()
    if reconciled.match.status is MatchStatus.CONFIRMED:
        return _IDENTIFIED, reconciled.documents
    if reconciled.match.status is MatchStatus.MISSING:
        return _NOT_IDENTIFIED, ()
    return _UNKNOWN, ()


def _documents(documents: Sequence[Document], report_path: Path) -> str:
    if not documents:
        return "—"
    links = []
    for document in documents:
        href = html.escape(_href(report_path, document.filepath), quote=True)
        label = html.escape(document.filename)
        links.append(f'<a href="{href}">{label}</a>')
    return "<br>\n".join(links)


def _href(report_path: Path, source: Path) -> str:
    resolved = source.resolve()
    try:
        relative = resolved.relative_to(report_path.parent.resolve())
    except ValueError:
        return resolved.as_uri()
    return quote(relative.as_posix())


def _description(transaction: Transaction) -> str:
    if transaction.merchant_raw:
        return transaction.merchant_raw
    return transaction.description.splitlines()[0]


def _amount(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01')):,.2f}"
