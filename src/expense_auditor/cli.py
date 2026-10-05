"""Command-line entry point for the contract invoice check."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from expense_auditor.bank.errors import BankStatementFormatError
from expense_auditor.checking.checker import check_folder, format_invoice_check
from expense_auditor.reporting.html import write_folder_statement_report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the invoice check command and return a process status."""
    parser = argparse.ArgumentParser(prog="expense-auditor")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check-folder",
        help="Check the folder and write report.html when it contains a bank statement.",
    )
    check.add_argument("folder", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "check-folder":
        return 2
    try:
        result = check_folder(args.folder)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(format_invoice_check(result))
    try:
        report = write_folder_statement_report(args.folder)
    except BankStatementFormatError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if report is not None:
        print(report.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
