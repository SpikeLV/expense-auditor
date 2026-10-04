"""Recursive discovery of supporting documents."""

from __future__ import annotations

from pathlib import Path

from expense_auditor.models.base import DomainModel
from expense_auditor.models.document import DocumentKind
from expense_auditor.models.fields import RequiredPath

_SUFFIX_TO_KIND: dict[str, DocumentKind] = {
    ".pdf": DocumentKind.PDF,
    ".jpg": DocumentKind.JPG,
    ".jpeg": DocumentKind.JPEG,
    ".png": DocumentKind.PNG,
}

SUPPORTED_SUFFIXES: frozenset[str] = frozenset(_SUFFIX_TO_KIND)


class ScannedDocument(DomainModel):
    """A supporting file found on disk. Its contents have not been read."""

    path: RequiredPath
    kind: DocumentKind


def scan_documents(root: Path) -> tuple[ScannedDocument, ...]:
    """Return supported documents under ``root`` in deterministic order.

    The walk is recursive. ``.pdf``, ``.jpg``, ``.jpeg``, and ``.png`` match
    without regard to case. Every other file and every directory is ignored.
    Results are sorted by relative POSIX path, using Unicode code point order.
    File contents are not opened or modified.
    """
    if not root.exists():
        raise FileNotFoundError(f"document directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"document path is not a directory: {root}")

    discovered: list[ScannedDocument] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        kind = _SUFFIX_TO_KIND.get(path.suffix.lower())
        if kind is None:
            continue
        discovered.append(ScannedDocument(path=path, kind=kind))

    def sort_key(item: ScannedDocument) -> str:
        return item.path.relative_to(root).as_posix()

    discovered.sort(key=sort_key)
    return tuple(discovered)
