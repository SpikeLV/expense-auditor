# expense-auditor

Local application that reconciles outgoing bank transactions against receipts and invoices.

V0.1 stays on this machine. It does not call cloud services, and it does not modify source documents.

## Requirements

- Python 3.12
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed locally when image OCR is used

## Setup

```powershell
uv python install 3.12
uv venv --python 3.12
uv pip install -e ".[dev]"
```

## Tests

```powershell
uv run pytest
```

Bank statements and supporting documents belong under `data/`. Generated reports belong under `reports/`.
