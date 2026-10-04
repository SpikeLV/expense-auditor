"""Recursive discovery of supporting documents."""

from __future__ import annotations

from pathlib import Path

from expense_auditor.models.base import DomainModel
from expense_auditor.models.document import DocumentType
from expense_auditor.models.fields import RequiredPath

_SUFFIX_TO_TYPE: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".jpg": DocumentType.JPG,
    ".jpeg": DocumentType.JPEG,
    ".png": DocumentType.PNG,
}

SUPPORTED_SUFFIXES: frozenset[str] = frozenset(_SUFFIX_TO_TYPE)


class ScannedDocument(DomainModel):
    """A supporting file found on disk.

    Its contents have not been read, so it has no document id. The id is the
    hash of those bytes and is assigned when the file is read.
    """

    filepath: RequiredPath
    document_type: DocumentType


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
        document_type = _SUFFIX_TO_TYPE.get(path.suffix.lower())
        if document_type is None:
            continue
        discovered.append(ScannedDocument(filepath=path, document_type=document_type))

    def sort_key(item: ScannedDocument) -> str:
        return item.filepath.relative_to(root).as_posix()

    discovered.sort(key=sort_key)
    return tuple(discovered)
