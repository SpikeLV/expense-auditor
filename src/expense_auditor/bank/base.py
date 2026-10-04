"""Bank statement parser contract.

A parser returns every classified statement row. Reconciliation keeps only
outgoing rows. Generic PDF text extraction is a separate step and is not a
bank-table parser.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from expense_auditor.models.transaction import Transaction, TransactionDirection


class BankStatementParser(Protocol):
    """Read one statement file into transactions.

    ``parse`` returns every classified row, including incoming and unknown
    rows. Each transaction stores this ``source_file``. Each ``id`` is
    ``transaction_id`` for that row's stable attributes, so parsing the same
    statement again produces the same ids.

    ``direction`` is ``OUTGOING``, ``INCOMING``, or ``UNKNOWN``. A row that is
    not clearly outgoing or incoming is ``UNKNOWN``. It is not marked outgoing.
    """

    def parse(self, source_file: Path) -> list[Transaction]:
        """Return the classified rows of ``source_file``."""


def reconciliation_transactions(
    transactions: Sequence[Transaction],
) -> tuple[Transaction, ...]:
    """Return only outgoing transactions.

    Incoming and unknown rows are left out. Unknown rows are not reclassified.
    """
    return tuple(
        transaction
        for transaction in transactions
        if transaction.direction is TransactionDirection.OUTGOING
    )
