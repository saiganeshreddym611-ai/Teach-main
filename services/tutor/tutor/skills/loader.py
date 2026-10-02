"""Load a pack's skills (`skills/*.json`) and task templates (`tasks/*.json`)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..content import ContentPack, ContentPackError
from ..contracts.skills import SkillDef, TaskTemplate

M = TypeVar("M", bound=BaseModel)


def load_skills(pack: ContentPack) -> dict[str, SkillDef]:
    return _load_dir(pack.root / "skills", SkillDef, "skill_id")


def load_tasks(pack: ContentPack) -> dict[str, TaskTemplate]:
    return _load_dir(pack.root / "tasks", TaskTemplate, "task_id")


def learning_order(skills: dict[str, SkillDef]) -> list[SkillDef]:
    """Skills in an order a student can take them: each after everything it requires, micro skills
    before capstones, then by ID. Skills caught in a requires loop come last (the validator reports them)."""
    placed: list[SkillDef] = []
    done: set[str] = set()
    waiting = sorted(skills.values(), key=lambda s: (s.level != "micro", s.skill_id))
    while waiting:
        ready = next((s for s in waiting if all(r in done or r not in skills for r in s.requires)), None)
        if ready is None:
            return placed + waiting
        placed.append(ready)
        done.add(ready.skill_id)
        waiting.remove(ready)
    return placed


def _load_dir(directory: Path, model: type[M], id_field: str) -> dict[str, M]:
    """Each file holds one item and is named after its ID, so a review diff names the item."""
    if not directory.is_dir():
        return {}
    items: dict[str, M] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            item = model.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ContentPackError(f"{path}: {exc}") from exc
        item_id = getattr(item, id_field)
        if item_id != path.stem:
            raise ContentPackError(f"{path}: {id_field} '{item_id}' does not match the file name")
        items[item_id] = item
    return items
