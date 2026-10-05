"""Command-line entry point for the contract invoice check."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from expense_auditor.checking.checker import check_folder, format_invoice_check


def main(argv: Sequence[str] | None = None) -> int:
    """Run the invoice check command and return a process status."""
    parser = argparse.ArgumentParser(prog="expense-auditor")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check-folder",
        help="List invoices required by the contract that are missing from the folder.",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
