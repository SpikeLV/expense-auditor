"""Errors raised while reading a bank statement."""


class BankStatementFormatError(ValueError):
    """The file is not this bank's statement, or extraction is incomplete.

    The SEB parser is specific to one statement layout. A different PDF, a
    broken text layer, or a balance that does not add up raises this error
    instead of returning an empty transaction list.
    """
