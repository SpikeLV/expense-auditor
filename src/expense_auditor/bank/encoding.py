"""Recover Unicode from the embedded Arial subsets in an SEB statement.

SEB exports ``Konta pārskats`` with Apache FOP. The embedded fonts are
Identity-H subsets of Arial and Arial Bold. They have no ToUnicode map and no
cmap, so ``page.get_text()`` returns U+FFFD. The content stream stores glyph
ids. Those ids are assigned per file, so they cannot be hard-coded.

Each used glyph is drawn on its own and matched to the same character drawn
from the Windows Arial font that the statement was built from. Matching uses
the ink bounding box at a fixed size and baseline. Comma-below letters in the
subset (ļ, ņ, ķ, Ķ, and the same family) differ slightly in the comma itself;
their letter body, above the baseline, still matches Arial, and ink below the
baseline selects the cedilla form. This is outline comparison, not OCR.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from expense_auditor.bank.errors import BankStatementFormatError
from expense_auditor.bank.pdf_access import (
    PdfDocument,
    blank_document,
    face_from_buffer,
    face_from_file,
)

_SIZE = 64
_PAGE_WIDTH = 140
_PAGE_HEIGHT = 180
_BASELINE = 110
_DARK = 180
_INK = tuple[int, int, int, int, int]

# Characters a Latvian SEB statement uses. Exact ink matches in this set are
# unique except Arial Bold "I" and "l", which share one outline.
_REFERENCE_CHARACTERS = (
    " !\"#$%&'()*+,-./0123456789:;<=>?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~"
    "ĀČĒĢĪĶĻŅŠŪŽāčēģīķļņšūž"
    "„“”«»–—•·€£"
)
_CASE_TWINS = frozenset({"I", "l"})

_GlyphValue = str | frozenset[str]
_reference_cache: dict[str, _ReferenceFont] = {}
_subset_cache: dict[str, dict[int, _GlyphValue]] = {}


class _ReferenceFont:
    """Ink signatures for one installed Arial face."""

    def __init__(
        self,
        exact: dict[_INK, tuple[str, ...]],
        upper: dict[_INK, tuple[str, ...]],
        below: dict[str, int],
    ) -> None:
        self.exact = exact
        self.upper = upper
        self.below = below


class GlyphDecoder:
    """Decode glyph ids for the fonts embedded in one statement."""

    def __init__(self, fonts: dict[str, bytes]) -> None:
        self._maps: dict[str, dict[int, _GlyphValue]] = {}
        for name, font_bytes in fonts.items():
            if not font_bytes or name == "Helvetica":
                continue
            bold = "Bold" in name
            self._maps[name] = _subset_map(font_bytes, bold=bold)

    def decode(self, font_name: str, glyph_id: int, prior: str) -> str:
        """Return the character for ``glyph_id`` in ``font_name``.

        ``prior`` is the text already decoded on the same line. It is used
        only when Arial Bold draws "I" and "l" with the same outline.
        """
        mapping = self._maps.get(font_name)
        if mapping is None:
            raise BankStatementFormatError(
                f"unexpected font {font_name!r}; this parser reads SEB Arial subsets only"
            )
        value = mapping.get(glyph_id)
        if value is None:
            raise BankStatementFormatError(
                f"could not identify glyph {glyph_id} in font {font_name}"
            )
        if isinstance(value, str):
            return value
        return _resolve_case_twin(value, prior)


def embedded_fonts(document: PdfDocument) -> dict[str, bytes]:
    """Return the embedded font bytes keyed by the PDF font name."""
    fonts: dict[str, bytes] = {}
    for page in document:
        for item in page.get_fonts():
            name = str(item[3])
            if name in fonts or name == "Helvetica":
                continue
            xref = item[0]
            if isinstance(xref, bool) or not isinstance(xref, int):
                raise BankStatementFormatError("the statement font table is incomplete")
            extracted = document.extract_font(xref)
            buffer = extracted[3]
            if isinstance(buffer, bytes | bytearray) and buffer:
                fonts[name] = bytes(buffer)
    if not fonts:
        raise BankStatementFormatError("the PDF has no embedded SEB statement fonts")
    return fonts


def _subset_map(font_bytes: bytes, *, bold: bool) -> dict[int, _GlyphValue]:
    digest = hashlib.sha256(font_bytes).hexdigest()
    cache_key = f"{'bold' if bold else 'regular'}:{digest}"
    cached = _subset_cache.get(cache_key)
    if cached is not None:
        return cached
    reference = _reference_font(_arial_path(bold=bold))
    font = face_from_buffer(font_bytes)
    glyph_ids = [(gid, str(gid)) for gid in range(font.glyph_count)]
    rendered = _render_signatures(font_bytes, None, glyph_ids)
    mapping: dict[int, _GlyphValue] = {}
    for gid in range(font.glyph_count):
        measured = rendered.get(str(gid))
        if measured is None:
            continue
        full, upper, below = measured
        identified = _identify(full, upper, below, reference)
        if identified is not None:
            mapping[gid] = identified
    _subset_cache[cache_key] = mapping
    return mapping


def _identify(
    full: _INK,
    upper: _INK | None,
    below: int,
    reference: _ReferenceFont,
) -> _GlyphValue | None:
    exact = reference.exact.get(full)
    if exact is not None:
        if len(exact) == 1:
            return exact[0]
        if frozenset(exact) == _CASE_TWINS:
            return _CASE_TWINS
        raise BankStatementFormatError(
            f"Arial ink signature {_format_chars(exact)} is shared by more than one character"
        )
    if upper is None:
        return None
    candidates = reference.upper.get(upper)
    if not candidates:
        return None
    if below > 0:
        chosen = tuple(char for char in candidates if reference.below[char] > 0)
    else:
        chosen = tuple(char for char in candidates if reference.below[char] == 0)
    if len(chosen) == 1:
        return chosen[0]
    return None


def _resolve_case_twin(options: frozenset[str], prior: str) -> str:
    if options != _CASE_TWINS:
        raise BankStatementFormatError(
            f"ambiguous glyph {_format_chars(tuple(sorted(options)))} has no resolution rule"
        )
    for char in reversed(prior):
        if char.isalpha():
            return "l" if char.islower() else "I"
    return "I"


def _reference_font(path: Path) -> _ReferenceFont:
    cache_key = str(path)
    cached = _reference_cache.get(cache_key)
    if cached is not None:
        return cached
    font = face_from_file(str(path))
    specs: list[tuple[int, str]] = []
    seen: set[int] = set()
    for char in _REFERENCE_CHARACTERS:
        glyph_id = font.has_glyph(ord(char))
        if not isinstance(glyph_id, int) or glyph_id <= 0 or glyph_id in seen:
            continue
        seen.add(glyph_id)
        specs.append((glyph_id, char))
    rendered = _render_signatures(None, str(path), specs)
    exact: dict[_INK, list[str]] = {}
    upper: dict[_INK, list[str]] = {}
    below: dict[str, int] = {}
    for char in _REFERENCE_CHARACTERS:
        measured = rendered.get(char)
        if measured is None:
            continue
        full, upper_ink, below_count = measured
        exact.setdefault(full, []).append(char)
        if upper_ink is not None:
            upper.setdefault(upper_ink, []).append(char)
        below[char] = below_count
    compiled = _ReferenceFont(
        exact={signature: tuple(chars) for signature, chars in exact.items()},
        upper={signature: tuple(chars) for signature, chars in upper.items()},
        below=below,
    )
    _reference_cache[cache_key] = compiled
    return compiled


def _arial_path(*, bold: bool) -> Path:
    windows = os.environ.get("WINDIR", r"C:\Windows")
    path = Path(windows) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf")
    if not path.is_file():
        raise BankStatementFormatError(
            "SEB statement text is recovered by comparing embedded Arial subsets "
            f"with the Windows Arial font, which was not found at {path}"
        )
    return path


def _render_signatures(
    font_bytes: bytes | None,
    font_file: str | None,
    specs: list[tuple[int, str]],
) -> dict[str, tuple[_INK, _INK | None, int]]:
    document = blank_document()
    try:
        page = document.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        page.insert_text((1, 1), ".", fontname="helv", fontsize=1, color=(1, 1, 1))
        if font_bytes is not None:
            page.insert_font(fontname="face", fontbuffer=font_bytes)
        else:
            if font_file is None:
                raise BankStatementFormatError("glyph comparison has no reference font")
            page.insert_font(fontname="face", fontfile=font_file)
        contents = page.get_contents()
        xref = int(contents[0])
        base = document.xref_stream(xref)
        baseline = _PAGE_HEIGHT - _BASELINE
        rendered: dict[str, tuple[_INK, _INK | None, int]] = {}
        for glyph_id, key in specs:
            command = f"\nBT /face {_SIZE} Tf 8 {baseline} Td <{glyph_id:04X}> Tj ET\n"
            document.update_stream(xref, base + command.encode("ascii"))
            pixmap = page.get_pixmap(alpha=False)
            measured = _measure(bytes(pixmap.samples), pixmap.width, pixmap.height, pixmap.n)
            if measured is not None:
                rendered[key] = measured
        return rendered
    finally:
        document.close()


def _measure(
    samples: bytes,
    width: int,
    height: int,
    channels: int,
) -> tuple[_INK, _INK | None, int] | None:
    full_x0, full_y0, full_x1, full_y1 = width, height, 0, 0
    upper_x0, upper_y0, upper_x1, upper_y1 = width, height, 0, 0
    full_count = 0
    upper_count = 0
    below = 0
    for y in range(height):
        row = y * width * channels
        for x in range(width):
            if samples[row + x * channels] >= _DARK:
                continue
            full_count += 1
            if x < full_x0:
                full_x0 = x
            if y < full_y0:
                full_y0 = y
            if x + 1 > full_x1:
                full_x1 = x + 1
            if y + 1 > full_y1:
                full_y1 = y + 1
            if y >= _BASELINE:
                below += 1
                continue
            upper_count += 1
            if x < upper_x0:
                upper_x0 = x
            if y < upper_y0:
                upper_y0 = y
            if x + 1 > upper_x1:
                upper_x1 = x + 1
            if y + 1 > upper_y1:
                upper_y1 = y + 1
    if full_count == 0:
        return None
    full = (full_x0, full_y0, full_x1, full_y1, full_count)
    upper = None
    if upper_count:
        upper = (upper_x0, upper_y0, upper_x1, upper_y1, upper_count)
    return full, upper, below


def _format_chars(chars: tuple[str, ...]) -> str:
    return ", ".join(repr(char) for char in chars)
