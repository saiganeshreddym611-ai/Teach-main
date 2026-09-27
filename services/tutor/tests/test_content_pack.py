import json
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tutor.content import ContentPackError, clear_pack_cache, load_pack
from tutor.curriculum import load_curriculum
from tutor.main import app


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPO_ROOT / "content" / "packs" / "ind_as_115"
GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "ind_as_115.stable.json"


@pytest.fixture(autouse=True)
def reset_pack_cache():
    clear_pack_cache()
    yield
    clear_pack_cache()


def _copy_pack(tmp_path: Path) -> Path:
    packs_dir = tmp_path / "packs"
    shutil.copytree(PACK_ROOT, packs_dir / "ind_as_115")
    return packs_dir


def test_stable_json_matches_golden():
    expected = GOLDEN.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert load_curriculum("ind_as_115").stable_json() == expected


def test_node_ids_unchanged():
    curriculum = load_curriculum("ind_as_115")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(curriculum.tree.nodes) == 42
    assert [node.id for node in curriculum.tree.nodes] == [node["id"] for node in golden["nodes"]]


def test_chapter_not_in_prompt():
    curriculum = load_curriculum("ind_as_115")
    assert "chapter" not in curriculum.stable_json()
    assert all(node.chapter for node in curriculum.tree.nodes)


def test_load_pack_default():
    first = load_pack()
    second = load_pack()
    assert first.manifest.attempt == "2027-05"
    assert len(first.content_hash) == 64
    assert first.content_hash == first.content_hash.lower()
    assert first is second


def test_content_hash_changes_with_content(tmp_path):
    packs_dir = _copy_pack(tmp_path)
    concept_map = packs_dir / "ind_as_115" / "concept_map.json"
    data = json.loads(concept_map.read_text(encoding="utf-8"))
    data["nodes"][0]["rubric"][0] += " changed"
    concept_map.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    original = load_pack("ind_as_115")
    changed = load_pack("ind_as_115", packs_dir=packs_dir)
    assert original.content_hash != changed.content_hash


def test_unknown_pack():
    with pytest.raises(ContentPackError, match=r"Available:.*ind_as_115"):
        load_pack("nope")


@pytest.mark.parametrize(
    "problem",
    ["missing_manifest", "invalid_manifest", "invalid_concept_map", "wrong_pack_id", "wrong_topic", "duplicate_id", "invalid_parent"],
)
def test_invalid_packs(tmp_path, problem):
    packs_dir = _copy_pack(tmp_path)
    pack_dir = packs_dir / "ind_as_115"
    if problem == "missing_manifest":
        (pack_dir / "manifest.json").unlink()
    elif problem == "invalid_manifest":
        (pack_dir / "manifest.json").write_text("{", encoding="utf-8")
    elif problem == "invalid_concept_map":
        (pack_dir / "concept_map.json").write_text("{", encoding="utf-8")
    else:
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        concept_map = json.loads((pack_dir / "concept_map.json").read_text(encoding="utf-8"))
        if problem == "wrong_pack_id":
            manifest["pack_id"] = "different"
            (pack_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        elif problem == "wrong_topic":
            concept_map["topic_id"] = "not_in_manifest"
        elif problem == "duplicate_id":
            concept_map["nodes"][1]["id"] = concept_map["nodes"][0]["id"]
        elif problem == "invalid_parent":
            concept_map["nodes"][0]["parent"] = "missing"
        (pack_dir / "concept_map.json").write_text(
            json.dumps(concept_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    with pytest.raises(ContentPackError):
        load_pack("ind_as_115", packs_dir=packs_dir)


def test_unknown_topic_still_404():
    with pytest.raises(FileNotFoundError):
        load_curriculum("nope")


async def test_content_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/content")
    assert response.status_code == 200
    body = response.json()
    assert body["manifest"]["pack_id"] == "ind_as_115"
    assert body["content_hash"] == load_pack().content_hash
