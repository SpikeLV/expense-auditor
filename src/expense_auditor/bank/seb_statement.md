# SEB Konta pārskats

`SebBankStatementParser` reads one statement layout: AS "SEB banka", title `KONTA PĀRSKATS`, produced by Apache FOP. The sample is `data/samples/bank/kontaparskats.pdf`. Later statements from this bank use the same template. This is not a multi-bank parser.

## Text encoding

The embedded fonts are Identity-H subsets of Arial and Arial Bold. They have no ToUnicode map, so plain `page.get_text()` is not usable. The content stream stores glyph ids, and those ids change from file to file.

Each used glyph is drawn and matched to the same character in the Windows Arial font by its ink box at a fixed size and baseline. Comma-below letters (ļ, ņ, ķ, Ķ, and the same family) use the letter body above the baseline, then ink below the baseline selects the cedilla form. Arial Bold `I` and `l` share one outline; the surrounding letters pick the case. This is outline comparison, not OCR.

## Columns

Measured with `page.get_texttrace()` on the sample. A4, origin at the top-left, units in points. The constants live on `SebStatementLayout`.

| Region | x |
| --- | --- |
| Reference | 40–156, text starts at 62.4 |
| Posted date | 156–212, text starts at 161.6 |
| Partner and narrative | from 212, text starts at 218.3 |
| Signed amount | right-aligned token at x ≥ 398, ending near 561 |

Page numbers sit at about y=824. The legal footer is recognized by its sentence, not by a y cut, because the last transaction page can still have narrative above that sentence.

## Rows

A transaction starts on a line with `DD.MM.YYYY` in the date column and a signed amount. Later lines with no date are continuation lines and stay with that transaction. There is no separate value date. Card timestamps inside the narrative are not the posted date.

The amount is in the account currency printed beside the balances (`EUR` on the sample). A leading `+` is money in. A leading `-` is money out. A currency code inside a card narrative is not the transaction currency.

These rows are not transactions: `Sākuma atlikums`, `Beigu atlikums`, `Kopā izskaitīts`, `Kopā ieskaitīts`, the overdraft line, column titles, the account header, and the footer.

## Balance check

`opening + incoming - outgoing = closing`. The parsed rows must also match the printed totals and the counts in parentheses. A mismatch raises `BankStatementFormatError`.
