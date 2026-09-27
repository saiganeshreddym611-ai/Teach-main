"""Deterministic tokenisation and synonym normalisation for retrieval."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..content import ContentPack

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "is", "are", "was", "were", "what",
        "how", "why", "when", "which", "who", "where", "does", "do", "can",
        "could", "would", "should", "and", "or", "for", "on", "with", "from",
        "about", "this", "that", "these", "those", "it", "its", "as", "by",
        "explain", "tell", "please", "describe", "mean", "means", "meaning",
        "define", "definition", "understand", "know", "give", "help", "want",
        "need", "example", "examples",
    }
)


class Normaliser:
    """Rewrite configured synonym variants to canonical token sequences."""

    def __init__(self, synonyms: dict[str, list[str]]) -> None:
        self.synonyms = synonyms
        replacements: list[tuple[list[str], list[str]]] = []
        for canonical, variants in synonyms.items():
            canonical_tokens = TOKEN_RE.findall(canonical.lower())
            for variant in variants:
                variant_tokens = TOKEN_RE.findall(variant.lower())
                if variant_tokens:
                    replacements.append((variant_tokens, canonical_tokens))
        self._replacements = sorted(replacements, key=lambda item: (-len(item[0]), item[0]))

    def tokens(self, text: str) -> list[str]:
        raw = TOKEN_RE.findall(text.lower())
        out: list[str] = []
        index = 0
        while index < len(raw):
            match: list[str] | None = None
            replacement: list[str] | None = None
            for variant, canonical in self._replacements:
                if raw[index : index + len(variant)] == variant:
                    match, replacement = variant, canonical
                    break
            if match is None:
                out.append(raw[index])
                index += 1
            else:
                out.extend(replacement or [])
                index += len(match)
        return [token for token in out if token not in STOPWORDS]

    @property
    def sha256(self) -> str:
        payload = json.dumps(
            self.synonyms, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def load_synonyms(pack: ContentPack) -> dict[str, list[str]]:
    path = pack.root / "synonyms.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, list) and all(isinstance(item, str) for item in value)
        for key, value in raw.items()
    ):
        raise ValueError(f"{path}: expected an object of string lists")
    return raw
