"""Errors raised while reading and splitting source documents."""
from __future__ import annotations


class IngestError(RuntimeError):
    """A source document or corpus cannot be ingested."""
