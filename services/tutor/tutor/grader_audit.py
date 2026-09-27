"""Grader audit: call IDs, memoisation, captures, citation diffs."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import settings
from .contracts.grading import GraderOutput


def new_call_id() -> str:
    return uuid4().hex


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def memo_key(backend: str, prompt_version: str, system_text: str, user_text: str) -> str:
    payload = json.dumps(
        [
            backend,
            prompt_version,
            sha256_text(system_text),
            sha256_text(user_text),
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GradeMemo:
    """In-memory memo cache, max 1024 entries, oldest dropped on overflow."""

    def __init__(self, max_size: int = 1024) -> None:
        self._store: OrderedDict[str, tuple[GraderOutput, str]] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> tuple[GraderOutput, str] | None:
        if key in self._store:
            self._store.move_to_end(key)
            value = self._store[key]
            return (value[0].model_copy(deep=True), value[1])
        return None

    def put(self, key: str, output: GraderOutput, call_id: str) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        elif len(self._store) >= self._max_size:
            self._store.popitem(last=False)
        self._store[key] = (output.model_copy(deep=True), call_id)

    def clear(self) -> None:
        self._store.clear()


grade_memo = GradeMemo()


def write_capture(record: dict[str, Any]) -> None:
    if not settings.capture_grader_calls:
        return
    try:
        settings.grader_capture_dir.mkdir(parents=True, exist_ok=True)
        call_id = record["grader_call_id"]
        path = settings.grader_capture_dir / f"{call_id}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def citation_diffs(runs: list[GraderOutput], node_ids: list[str]) -> list[str]:
    diffs: list[str] = []
    if len(runs) < 2:
        return diffs
    for node_id in node_ids:
        passage_sets: list[list[str]] = []
        for run in runs:
            for v in run.verdicts:
                if v.node_id == node_id:
                    passage_sets.append(v.passage_ids)
                    break
            else:
                passage_sets.append([])
        if len(set(tuple(p) for p in passage_sets)) > 1:
            diffs.append(f"  [CITE] {node_id}: {passage_sets}")
    return diffs