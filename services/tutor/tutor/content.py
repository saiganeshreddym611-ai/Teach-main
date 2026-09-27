"""Versioned content-pack loader."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import settings
from .contracts.content import PackManifest
from .curriculum import Curriculum
from .models import Tree

PACKS_DIR = Path(__file__).resolve().parents[3] / "content" / "packs"


class ContentPackError(RuntimeError):
    """A content pack is missing or invalid."""


@dataclass(frozen=True)
class ContentPack:
    pack_id: str
    root: Path
    manifest: PackManifest
    curriculum: Curriculum
    content_hash: str

    @property
    def concept_map_path(self) -> Path:
        return self.root / "concept_map.json"

    @property
    def reviews_path(self) -> Path:
        return self.root / "reviews.json"

    @property
    def releases_path(self) -> Path:
        return self.root / "releases.json"

    @property
    def sources_path(self) -> Path:
        return self.root / "sources" / "sources.json"

    @property
    def corpus_dir(self) -> Path:
        return self.root / "corpus"


def available_packs(packs_dir: Path | None = None) -> list[str]:
    directory = packs_dir or PACKS_DIR
    if not directory.exists():
        return []
    return sorted(
        child.name
        for child in directory.iterdir()
        if child.is_dir() and (child / "manifest.json").is_file()
    )


def _pack_error(pack_id: str, packs_dir: Path) -> ContentPackError:
    available = ", ".join(available_packs(packs_dir))
    return ContentPackError(f"Unknown CONTENT_PACK '{pack_id}'. Available: {available}")


def compute_content_hash(manifest: PackManifest, tree: Tree) -> str:
    payload = json.dumps(
        {
            "manifest": manifest.model_dump(mode="json"),
            "concept_map": tree.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPackError(f"{path}: {exc}") from exc


def _load_pack(pack_id: str, packs_dir: Path) -> ContentPack:
    root = packs_dir / pack_id
    manifest_path = root / "manifest.json"
    concept_map_path = root / "concept_map.json"
    if not root.is_dir() or not manifest_path.is_file():
        raise _pack_error(pack_id, packs_dir)

    try:
        manifest = PackManifest.model_validate(_read_json(manifest_path, "manifest"))
    except Exception as exc:
        raise ContentPackError(f"{manifest_path}: {exc}") from exc
    if manifest.pack_id != pack_id:
        raise ContentPackError(
            f"{manifest_path}: manifest pack_id '{manifest.pack_id}' differs from folder '{pack_id}'"
        )
    try:
        tree = Tree.model_validate(_read_json(concept_map_path, "concept map"))
    except Exception as exc:
        raise ContentPackError(f"{concept_map_path}: {exc}") from exc
    if tree.topic_id not in manifest.topics:
        raise ContentPackError(
            f"{concept_map_path}: topic ID '{tree.topic_id}' is not in manifest.topics"
        )
    node_ids = [node.id for node in tree.nodes]
    duplicates = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicates:
        raise ContentPackError(f"{concept_map_path}: duplicate node IDs: {', '.join(duplicates)}")
    node_id_set = set(node_ids)
    invalid_parents = sorted(
        {node.parent for node in tree.nodes if node.parent is not None and node.parent not in node_id_set}
    )
    if invalid_parents:
        raise ContentPackError(
            f"{concept_map_path}: parent IDs are not node IDs: {', '.join(invalid_parents)}"
        )
    curriculum = Curriculum(tree)
    return ContentPack(
        pack_id=pack_id,
        root=root,
        manifest=manifest,
        curriculum=curriculum,
        content_hash=compute_content_hash(manifest, tree),
    )


@lru_cache(maxsize=8)
def _cached_load_pack(pack_id: str, packs_dir: Path) -> ContentPack:
    return _load_pack(pack_id, packs_dir)


def load_pack(pack_id: str | None = None, packs_dir: Path | None = None) -> ContentPack:
    selected_id = pack_id or settings.content_pack
    selected_dir = packs_dir or PACKS_DIR
    return _cached_load_pack(selected_id, selected_dir.resolve())


def clear_pack_cache() -> None:
    _cached_load_pack.cache_clear()
