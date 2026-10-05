"""SEB ``Konta pārskats`` parser.

The sample ``data/samples/bank/kontaparskats.pdf`` is the layout this module
reads. It is an 8-page A4 statement produced by Apache FOP for AS "SEB banka".
Later statements from this bank use the same template. This is not a
multi-bank parser.

Text encoding
    The embedded fonts are Identity-H Arial subsets without a ToUnicode map.
    Characters are recovered by ``encoding.GlyphDecoder`` (glyph outlines
    compared with Windows Arial). Ordinary ``page.get_text()`` is not used.
    OCR is not used.

Columns, measured from ``get_texttrace`` boxes on the sample (origin top-left,
points). See ``SebStatementLayout``.

Rows
    A transaction starts on a line that has a ``DD.MM.YYYY`` date in the date
    column and a signed amount in the amount column. Later lines with no date
    are continuation lines (reference and narrative) and belong to that
    transaction. There is no separate value date. Card timestamps inside the
    narrative are not the posted date.

    The amount is in the account currency (EUR on the sample), printed with a
    leading ``+`` for money in and a leading ``-`` for money out. Direction
    comes from that sign. Foreign currency codes inside a card narrative are
    not the transaction currency.

    These rows are not transactions: ``Sākuma atlikums``, ``Beigu atlikums``,
    ``Kopā izskaitīts``, ``Kopā ieskaitīts``, the overdraft line, column
    titles, the account header, page numbers, and the legal footer.

Balance check
    The statement prints an opening balance, incoming and outgoing totals, and
    a closing balance. Parsed movements must satisfy

    ``opening + incoming - outgoing = closing``

    and must match the printed totals and parenthetical counts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_auditor.bank.encoding import GlyphDecoder, embedded_fonts
from expense_auditor.bank.errors import BankStatementFormatError
from expense_auditor.bank.pdf_access import PdfDocument, PdfPage, open_document
from expense_auditor.identity import transaction_id
from expense_auditor.models.transaction import Transaction, TransactionDirection
from expense_auditor.normalization.amount import AmountParseError, parse_amount
from expense_auditor.normalization.date import DateParseError, parse_date

_TITLE = "KONTA PĀRSKATS"
_OPENING = "Sākuma atlikums"
_CLOSING = "Beigu atlikums"
_DEBITED = "Kopā izskaitīts"
_CREDITED = "Kopā ieskaitīts"
_HEADER_MARKERS = (
    _TITLE,
    "Darījuma reģ",
    "Darījuma reference",
    "Dokuments ir sagatavots",
    "Paldies par sadarbību",
)
_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_AMOUNT_WORD = re.compile(r"^(?:[A-Z]{3})?[+\-–—−]\d+\.\d{2}(?:[A-Z]{3})?$")
_CURRENCY_WORD = re.compile(r"\b([A-Z]{3})\b")
_COUNT = re.compile(r"\((\d+)\)")
_MINUS = frozenset("-–—−")
_PAGE_TOLERANCE = 1.5


class SebStatementLayout:
    """Column boxes for an SEB Konta pārskats page.

    Measured on ``data/samples/bank/kontaparskats.pdf`` with
    ``page.get_texttrace()``. The page is A4 (595 by 842). Coordinates use
    PyMuPDF's top-left origin.

    The reference column starts at x=62.4 and its glyphs stay left of x=156.
    The posted date starts at x=161.6. Partner and narrative text starts at
    x=218.3 and stays left of x=398. The signed amount starts at x=401 or
    further right and ends near x=561. Page numbers and the legal footer are
    at y>=815, so everything at y>=800 is page furniture.
    """

    PAGE_WIDTH = 595.0
    PAGE_HEIGHT = 842.0
    REFERENCE_X0 = 40.0
    REFERENCE_X1 = 156.0
    DATE_X0 = 156.0
    DATE_X1 = 212.0
    DESCRIPTION_X0 = 212.0
    DESCRIPTION_X1 = 398.0
    AMOUNT_X0 = 398.0
    AMOUNT_X1 = 580.0
    FOOTER_Y = 800.0
    SAME_LINE_Y = 1.0
    WORD_GAP = 0.8


@dataclass(frozen=True)
class _Placed:
    font: str
    glyph_id: int
    x0: float
    x1: float
    y0: float
    page: int


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float


@dataclass(frozen=True)
class _Line:
    page: int
    y0: float
    reference: str
    date_text: str
    details: str
    amount_text: str

    @property
    def text(self) -> str:
        return " ".join(
            part
            for part in (self.reference, self.date_text, self.details, self.amount_text)
            if part
        )


@dataclass
class _OpenTransaction:
    page: int
    posted: date
    sign: str
    amount: Decimal
    reference_lines: list[str]
    detail_lines: list[str]


@dataclass(frozen=True)
class _ParsedStatement:
    page_count: int
    transaction_pages: tuple[int, ...]
    transactions: tuple[Transaction, ...]
    opening: Decimal
    closing: Decimal
    currency: str


class SebBankStatementParser:
    """Read one SEB Konta pārskats PDF into transactions.

    ``parse`` returns incoming and outgoing rows. Opening and closing balances,
    totals, headers, and footers are left out. Each id comes from
    ``transaction_id`` for that row.
    """

    def parse(self, source_file: Path) -> list[Transaction]:
        """Return the classified transactions in ``source_file``."""
        return list(_read_statement(source_file).transactions)


def parse(path: Path) -> list[Transaction]:
    """Return the transactions in one SEB Konta pārskats PDF."""
    return SebBankStatementParser().parse(path)


def inspect_statement(path: Path) -> str:
    """Return a short structural summary of one SEB statement."""
    statement = _read_statement(path)
    outgoing = sum(
        1
        for transaction in statement.transactions
        if transaction.direction is TransactionDirection.OUTGOING
    )
    incoming = len(statement.transactions) - outgoing
    samples = _sample_lines(statement.transactions[:3])
    return "\n".join(
        (
            "Bank statement format: RECOGNIZED",
            "",
            f"Pages: {statement.page_count}",
            f"Transaction pages: {_format_pages(statement.transaction_pages)}",
            "",
            f"Transactions detected: {len(statement.transactions)}",
            f"Outgoing: {outgoing}",
            f"Incoming: {incoming}",
            "",
            f"Opening balance: {_money(statement.opening)} {statement.currency}",
            f"Closing balance: {_money(statement.closing)} {statement.currency}",
            "",
            "Sample transactions:",
            *samples,
            "",
            "Parser:",
            "  Bank-specific PDF parser",
            "  Positional extraction: YES",
            "  OCR: NO",
        )
    )


def _read_statement(path: Path) -> _ParsedStatement:
    document = _open_pdf(path)
    try:
        page_count = int(document.page_count)
        _require_page_geometry(document)
        decoder = GlyphDecoder(embedded_fonts(document))
        lines = _extract_lines(document, decoder)
    finally:
        document.close()
    if not any(_TITLE in line.text for line in lines):
        raise BankStatementFormatError(
            "not an SEB Konta pārskats statement: the title "
            f"{_TITLE!r} was not found"
        )
    return _assemble(path, document_page_count=page_count, lines=lines)


def _open_pdf(path: Path) -> PdfDocument:
    if not path.is_file():
        raise BankStatementFormatError(f"statement file was not found: {path}")
    try:
        document = open_document(path)
    except BankStatementFormatError:
        raise
    except Exception as exc:
        raise BankStatementFormatError(f"could not open {path} as a PDF") from exc
    if document.needs_pass:
        document.close()
        raise BankStatementFormatError(f"{path} is encrypted and cannot be parsed")
    if document.page_count < 1:
        document.close()
        raise BankStatementFormatError(f"{path} has no pages")
    return document


def _require_page_geometry(document: PdfDocument) -> None:
    for index, page in enumerate(document, start=1):
        width = float(page.rect.width)
        height = float(page.rect.height)
        if abs(width - SebStatementLayout.PAGE_WIDTH) > _PAGE_TOLERANCE:
            raise BankStatementFormatError(
                f"page {index} width {width:.1f} is not the SEB A4 layout"
            )
        if abs(height - SebStatementLayout.PAGE_HEIGHT) > _PAGE_TOLERANCE:
            raise BankStatementFormatError(
                f"page {index} height {height:.1f} is not the SEB A4 layout"
            )


def _extract_lines(document: PdfDocument, decoder: GlyphDecoder) -> list[_Line]:
    placed: list[_Placed] = []
    for page_number, page in enumerate(document, start=1):
        for font_name, glyph_id, x0, y0, x1 in _trace_glyphs(page):
            if y0 >= SebStatementLayout.FOOTER_Y:
                continue
            placed.append(
                _Placed(
                    font=font_name,
                    glyph_id=glyph_id,
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    page=page_number,
                )
            )
    placed.sort(key=lambda glyph: (glyph.page, glyph.y0, glyph.x0))
    return [_line_from_glyphs(group, decoder) for group in _cluster_lines(placed)]


def _trace_glyphs(page: PdfPage) -> list[tuple[str, int, float, float, float]]:
    traced: list[tuple[str, int, float, float, float]] = []
    for span in page.get_texttrace():
        font_name = span.get("font")
        chars = span.get("chars")
        if not isinstance(font_name, str) or not isinstance(chars, Sequence):
            raise BankStatementFormatError("the statement text trace is incomplete")
        for item in chars:
            if not isinstance(item, Sequence) or len(item) < 4:
                raise BankStatementFormatError("the statement text trace is incomplete")
            bbox = item[3]
            if not isinstance(bbox, Sequence) or len(bbox) < 4:
                raise BankStatementFormatError("the statement text trace is incomplete")
            traced.append(
                (font_name, int(item[1]), float(bbox[0]), float(bbox[1]), float(bbox[2]))
            )
    return traced


def _cluster_lines(placed: Sequence[_Placed]) -> list[list[_Placed]]:
    groups: list[list[_Placed]] = []
    current: list[_Placed] = []
    anchor = 0.0
    for glyph in placed:
        if (
            not current
            or glyph.page != current[-1].page
            or abs(glyph.y0 - anchor) > SebStatementLayout.SAME_LINE_Y
        ):
            if current:
                groups.append(current)
            current = [glyph]
            anchor = glyph.y0
        else:
            current.append(glyph)
    if current:
        groups.append(current)
    return groups


def _line_from_glyphs(glyphs: Sequence[_Placed], decoder: GlyphDecoder) -> _Line:
    ordered = sorted(glyphs, key=lambda glyph: glyph.x0)
    prior = ""
    words: list[_Word] = []
    previous_x1: float | None = None
    for glyph in ordered:
        character = decoder.decode(glyph.font, glyph.glyph_id, prior)
        prior += character
        if (
            words
            and previous_x1 is not None
            and glyph.x0 - previous_x1 <= SebStatementLayout.WORD_GAP
        ):
            previous = words[-1]
            words[-1] = _Word(text=previous.text + character, x0=previous.x0)
        else:
            words.append(_Word(text=character, x0=glyph.x0))
        previous_x1 = glyph.x1
    amount = _amount_word(words)
    reference: list[str] = []
    date_words: list[str] = []
    details: list[str] = []
    layout = SebStatementLayout
    for word in words:
        if amount is not None and word is amount:
            continue
        if word.x0 < layout.DATE_X0:
            reference.append(word.text)
        elif word.x0 < layout.DATE_X1:
            date_words.append(word.text)
        elif word.x0 < layout.AMOUNT_X1:
            details.append(word.text)
        else:
            raise BankStatementFormatError(
                f"a word {word.text!r} at x={word.x0:.1f} does not fall in a SEB statement column"
            )
    return _Line(
        page=ordered[0].page,
        y0=ordered[0].y0,
        reference=" ".join(reference).strip(),
        date_text="".join(date_words).strip(),
        details=" ".join(details).strip(),
        amount_text="" if amount is None else amount.text,
    )


def _amount_word(words: Sequence[_Word]) -> _Word | None:
    """Return the rightmost signed account-currency amount on a line.

    Narrative text can extend past the description column. The amount is the
    right-aligned token with a leading sign, not every glyph to the right of
    ``AMOUNT_X0``.
    """
    found: _Word | None = None
    for word in words:
        if word.x0 < SebStatementLayout.AMOUNT_X0:
            continue
        if _AMOUNT_WORD.fullmatch(word.text):
            found = word
    return found


def _assemble(path: Path, *, document_page_count: int, lines: Sequence[_Line]) -> _ParsedStatement:
    opening: Decimal | None = None
    closing: Decimal | None = None
    debited: Decimal | None = None
    credited: Decimal | None = None
    debited_count: int | None = None
    credited_count: int | None = None
    currency: str | None = None
    transactions: list[Transaction] = []
    current: _OpenTransaction | None = None

    def close_current() -> None:
        nonlocal current
        if current is None:
            return
        transactions.append(_transaction(path, len(transactions) + 1, current, currency))
        current = None

    for line in lines:
        if _is_header(line):
            continue
        kind = _summary_kind(line)
        if kind == "limit":
            close_current()
            continue
        if kind is not None:
            close_current()
            signed, row_currency = _signed_amount(line.amount_text, line.page)
            if row_currency is None:
                row_currency = _line_currency(line)
            if row_currency is None:
                raise BankStatementFormatError(
                    f"page {line.page} balance row has no account currency: {line.text!r}"
                )
            currency = _same_currency(currency, row_currency)
            if kind == "opening":
                opening = _one_balance(opening, signed, _OPENING)
            elif kind == "closing":
                closing = _one_balance(closing, signed, _CLOSING)
            elif kind == "debited":
                debited = _one_balance(debited, signed, _DEBITED)
                debited_count = _parenthetical_count(line.text, _DEBITED)
            elif kind == "credited":
                credited = _one_balance(credited, signed, _CREDITED)
                credited_count = _parenthetical_count(line.text, _CREDITED)
            continue
        if line.date_text:
            if not _DATE.fullmatch(line.date_text):
                raise BankStatementFormatError(
                    f"page {line.page} has an unrecognized date {line.date_text!r}"
                )
            if not _is_amount(line.amount_text):
                raise BankStatementFormatError(
                    f"page {line.page} date {line.date_text} has no amount"
                )
            close_current()
            signed, _row_currency = _signed_amount(line.amount_text, line.page)
            if currency is None:
                raise BankStatementFormatError(
                    "a transaction appears before the statement currency"
                )
            try:
                posted = parse_date(line.date_text)
            except DateParseError as exc:
                raise BankStatementFormatError(
                    f"page {line.page} date {line.date_text!r} is not a calendar date"
                ) from exc
            current = _OpenTransaction(
                page=line.page,
                posted=posted,
                sign="-" if signed < 0 else "+",
                amount=abs(signed),
                reference_lines=_nonempty(line.reference),
                detail_lines=_nonempty(line.details),
            )
            continue
        if _is_amount(line.amount_text):
            raise BankStatementFormatError(
                f"page {line.page} has an amount that is not a transaction or a "
                f"balance row: {line.text!r}"
            )
        if current is not None and (line.reference or line.details):
            if line.reference:
                current.reference_lines.append(line.reference)
            if line.details:
                current.detail_lines.append(line.details)
    close_current()

    if currency is None or opening is None or closing is None:
        raise BankStatementFormatError(
            "SEB statement is missing the EUR opening balance, closing balance, "
            "or account currency"
        )
    if not transactions:
        raise BankStatementFormatError("SEB statement contains no transactions")
    _check_balance(
        opening=opening,
        closing=closing,
        debited=debited,
        credited=credited,
        debited_count=debited_count,
        credited_count=credited_count,
        transactions=transactions,
    )
    pages = tuple(
        sorted(
            {
                transaction.source_page
                for transaction in transactions
                if transaction.source_page is not None
            }
        )
    )
    return _ParsedStatement(
        page_count=document_page_count,
        transaction_pages=pages,
        transactions=tuple(transactions),
        opening=opening,
        closing=closing,
        currency=currency,
    )


def _transaction(
    path: Path,
    source_row: int,
    current: _OpenTransaction,
    currency: str | None,
) -> Transaction:
    if currency is None:
        raise BankStatementFormatError("transaction amount has no account currency")
    if not current.detail_lines:
        raise BankStatementFormatError(
            f"page {current.page} transaction on {current.posted.isoformat()} has no description"
        )
    description = "\n".join(
        [*current.reference_lines, *current.detail_lines]
    ).strip()
    direction = (
        TransactionDirection.OUTGOING if current.sign == "-" else TransactionDirection.INCOMING
    )
    merchant = current.detail_lines[0]
    return Transaction(
        id=transaction_id(
            source_file=path,
            posted_date=current.posted,
            direction=direction,
            amount=current.amount,
            currency=currency,
            description=description,
            source_page=current.page,
            source_row=source_row,
        ),
        posted_date=current.posted,
        direction=direction,
        amount=current.amount,
        currency=currency,
        description=description,
        merchant_raw=merchant,
        source_file=path,
        source_page=current.page,
        source_row=source_row,
    )


def _is_header(line: _Line) -> bool:
    return any(marker in line.text for marker in _HEADER_MARKERS)


def _summary_kind(line: _Line) -> str | None:
    text = line.details or line.text
    if _OPENING in text:
        return "opening"
    if _DEBITED in text:
        return "debited"
    if _CREDITED in text:
        return "credited"
    if _CLOSING in text:
        return "closing"
    if "Kredītlimits" in text or "Overdrafta" in text:
        return "limit"
    return None


def _is_amount(amount_text: str) -> bool:
    return _AMOUNT_WORD.fullmatch(amount_text.replace(" ", "")) is not None


def _line_currency(line: _Line) -> str | None:
    codes = list(dict.fromkeys(_CURRENCY_WORD.findall(line.text)))
    if len(codes) > 1:
        raise BankStatementFormatError(
            f"page {line.page} balance row names more than one currency: {line.text!r}"
        )
    if not codes:
        return None
    code = codes[0]
    if not isinstance(code, str):
        raise BankStatementFormatError("balance row currency could not be read")
    return code


def _signed_amount(amount_text: str, page: int) -> tuple[Decimal, str | None]:
    compact = amount_text.replace(" ", "")
    currency: str | None = None
    if len(compact) > 3 and compact[:3].isalpha() and compact[:3].isupper():
        currency = compact[:3]
        compact = compact[3:]
    elif len(compact) > 3 and compact[-3:].isalpha() and compact[-3:].isupper():
        currency = compact[-3:]
        compact = compact[:-3]
    if not compact or (compact[0] not in _MINUS and compact[0] != "+"):
        raise BankStatementFormatError(
            f"page {page} amount {amount_text!r} has no SEB debit or credit sign"
        )
    sign = -1 if compact[0] in _MINUS else 1
    try:
        parsed = parse_amount(compact[1:])
    except AmountParseError as exc:
        raise BankStatementFormatError(
            f"page {page} amount {amount_text!r} is not a decimal amount"
        ) from exc
    if parsed.currency is not None and currency is not None and parsed.currency != currency:
        raise BankStatementFormatError(
            f"page {page} amount mixes currencies {parsed.currency} and {currency}"
        )
    return sign * parsed.amount, currency or parsed.currency


def _same_currency(current: str | None, found: str) -> str:
    if current is not None and current != found:
        raise BankStatementFormatError(
            f"statement mixes account currencies {current} and {found}"
        )
    return found


def _one_balance(current: Decimal | None, value: Decimal, label: str) -> Decimal:
    if current is not None:
        raise BankStatementFormatError(f"the statement repeats {label}")
    return value


def _parenthetical_count(text: str, label: str) -> int:
    found = _COUNT.search(text)
    if found is None:
        raise BankStatementFormatError(f"{label} is missing its transaction count")
    return int(found.group(1))


def _nonempty(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    return [stripped]


def _check_balance(
    *,
    opening: Decimal,
    closing: Decimal,
    debited: Decimal | None,
    credited: Decimal | None,
    debited_count: int | None,
    credited_count: int | None,
    transactions: Sequence[Transaction],
) -> None:
    outgoing = [item for item in transactions if item.direction is TransactionDirection.OUTGOING]
    incoming = [item for item in transactions if item.direction is TransactionDirection.INCOMING]
    outgoing_sum = sum((item.amount for item in outgoing), Decimal("0"))
    incoming_sum = sum((item.amount for item in incoming), Decimal("0"))
    if opening + incoming_sum - outgoing_sum != closing:
        raise BankStatementFormatError(
            "balance check failed: "
            f"opening {_money(opening)} + incoming {_money(incoming_sum)} "
            f"- outgoing {_money(outgoing_sum)} != closing {_money(closing)}"
        )
    if debited is None or credited is None:
        raise BankStatementFormatError(
            "SEB statement is missing Kopā izskaitīts or Kopā ieskaitīts"
        )
    if debited != -outgoing_sum:
        raise BankStatementFormatError(
            f"Kopā izskaitīts {_money(debited)} does not match "
            f"outgoing transactions {_money(outgoing_sum)}"
        )
    if credited != incoming_sum:
        raise BankStatementFormatError(
            f"Kopā ieskaitīts {_money(credited)} does not match "
            f"incoming transactions {_money(incoming_sum)}"
        )
    if debited_count != len(outgoing):
        raise BankStatementFormatError(
            f"Kopā izskaitīts count {debited_count} does not match {len(outgoing)} outgoing rows"
        )
    if credited_count != len(incoming):
        raise BankStatementFormatError(
            f"Kopā ieskaitīts count {credited_count} does not match {len(incoming)} incoming rows"
        )


def _sample_lines(transactions: Sequence[Transaction]) -> tuple[str, ...]:
    lines: list[str] = []
    for index, transaction in enumerate(transactions, start=1):
        sign = "-" if transaction.direction is TransactionDirection.OUTGOING else "+"
        merchant = transaction.merchant_raw or transaction.description.split("\n", 1)[0]
        lines.append(
            f"{index}. {transaction.posted_date.isoformat()} {merchant} "
            f"{sign}{_money(transaction.amount)} {transaction.currency}"
        )
    return tuple(lines)


def _format_pages(pages: Sequence[int]) -> str:
    if not pages:
        return "none"
    ranges: list[str] = []
    start = pages[0]
    previous = pages[0]
    for page in list(pages)[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(_one_range(start, previous))
        start = page
        previous = page
    ranges.append(_one_range(start, previous))
    return ", ".join(ranges)


def _one_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _money(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'))}"
