"""Read source documents into the normalized text format used by splitters."""
from __future__ import annotations

from pathlib import Path

from .errors import IngestError


def read_source(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeError) as exc:
            raise IngestError(f"{path}: {exc}") from exc
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise IngestError('PDF support needs: pip install -e ".[ingest]"') from exc
        try:
            return "\f".join(page.extract_text() or "" for page in PdfReader(path).pages)
        except Exception as exc:
            raise IngestError(f"{path}: {exc}") from exc
    raise IngestError(f"Unsupported source extension '{path.suffix}' in {path}")
