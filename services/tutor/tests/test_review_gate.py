from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tutor.config import settings
from tutor.content import clear_pack_cache, load_pack
from tutor.main import app
from tutor import review as review_module
from tutor.review import (
    ReviewGateError,
    current_release,
    item_hashes,
    load_reviews,
    record_error,
    record_pass,
    record_release,
    review_counts,
    sample_for_signoff,
    save_reviews,
    status_table,
)
from tutor.contracts.content import ReviewMeta

from .pack_builder import write_pack


@pytest.fixture
def fixture_pack(tmp_path, monkeypatch):
    packs_dir = tmp_path / "packs"
    write_pack(packs_dir)
    monkeypatch.setattr("tutor.content.PACKS_DIR", packs_dir)
    monkeypatch.setattr("tutor.review.REGRESSIONS_PATH", tmp_path / "regressions.jsonl")
    monkeypatch.setattr(settings, "content_pack", "fx")
    clear_pack_cache()
    yield packs_dir
    clear_pack_cache()


def _review_all(pack, status="claude_reviewed"):
    hashes = item_hashes(pack)
    return {
        item_id: ReviewMeta(status=status, content_sha256=content_hash)
        for item_id, content_hash in hashes.items()
    }


def test_new_pack_is_all_draft(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    table = status_table(pack)
    assert all(status == "draft" for _, status in table.values())
    counts = review_counts(pack)
    assert counts == {
        "nodes": {"draft": 3, "claude_reviewed": 0, "needs_expert": 0, "signed_off": 0},
        "tasks": {"draft": 0, "claude_reviewed": 0, "needs_expert": 0, "signed_off": 0},
        "practice": {"draft": 0, "claude_reviewed": 0, "needs_expert": 0, "signed_off": 0},
    }


def test_review_valid_while_hash_matches(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    reviews = _review_all(pack)
    save_reviews(pack, reviews)
    assert all(status == "claude_reviewed" for _, status in status_table(pack).values())


def test_edit_invalidates_review(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    save_reviews(pack, _review_all(pack))
    concept_map = pack.concept_map_path
    data = json.loads(concept_map.read_text(encoding="utf-8"))
    data["nodes"][0]["rubric"][0] += " edited"
    concept_map.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_pack_cache()
    edited = load_pack("fx", fixture_pack)
    assert status_table(edited)[data["nodes"][0]["id"]][1] == "draft"
    assert all(status == "claude_reviewed" for item_id, (_, status) in status_table(edited).items() if item_id != data["nodes"][0]["id"])


def test_recording_review_keeps_content_hash(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    before = pack.content_hash
    save_reviews(pack, _review_all(pack))
    record_release(pack, "Owner")
    assert pack.content_hash == before


async def _post_session(monkeypatch, fixture_pack, strict):
    monkeypatch.setattr(settings, "require_reviewed_content", strict)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/session", json={"student_id": "student", "topic_id": "fx_topic"})


async def test_strict_refuses_draft(monkeypatch, fixture_pack):
    response = await _post_session(monkeypatch, fixture_pack, True)
    assert response.status_code == 409
    assert len(response.json()["detail"]["problems"]) == 4


async def test_strict_refuses_needs_expert(monkeypatch, fixture_pack):
    pack = load_pack("fx", fixture_pack)
    reviews = _review_all(pack)
    save_reviews(pack, reviews)
    record_release(pack, "Owner")
    first = next(iter(reviews))
    reviews[first] = ReviewMeta(status="needs_expert", content_sha256=item_hashes(pack)[first])
    save_reviews(pack, reviews)
    response = await _post_session(monkeypatch, fixture_pack, True)
    assert response.status_code == 409
    assert response.json()["detail"]["problems"][0]["item_id"] == first


async def test_strict_refuses_without_release(monkeypatch, fixture_pack):
    pack = load_pack("fx", fixture_pack)
    save_reviews(pack, _review_all(pack))
    response = await _post_session(monkeypatch, fixture_pack, True)
    assert response.status_code == 409
    assert response.json()["detail"]["problems"] == [{"item_id": "<release>", "kind": "release", "status": "missing"}]


async def test_strict_allows_reviewed_and_released(monkeypatch, fixture_pack):
    pack = load_pack("fx", fixture_pack)
    save_reviews(pack, _review_all(pack))
    record_release(pack, "Owner")
    response = await _post_session(monkeypatch, fixture_pack, True)
    assert response.status_code == 200


def test_release_bound_to_content(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    save_reviews(pack, _review_all(pack))
    record_release(pack, "Owner")
    assert current_release(pack) is not None
    data = json.loads(pack.concept_map_path.read_text(encoding="utf-8"))
    data["nodes"][0]["rubric"][0] += " edited"
    pack.concept_map_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_pack_cache()
    assert current_release(load_pack("fx", fixture_pack)) is None


async def test_dev_mode_allows_drafts(monkeypatch, fixture_pack):
    response = await _post_session(monkeypatch, fixture_pack, False)
    assert response.status_code == 200


def test_sample_size_and_reproducibility(tmp_path):
    for count, expected in ((30, 10), (150, 15), (4, 4)):
        packs_dir = tmp_path / str(count)
        write_pack(packs_dir, n_nodes=count)
        pack = load_pack("fx", packs_dir)
        save_reviews(pack, _review_all(pack))
        seed, first = sample_for_signoff(pack, 7)
        assert len(first) == expected
        assert sample_for_signoff(pack, seed)[1] == first


def test_record_pass(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    item_id = next(iter(item_hashes(pack)))
    save_reviews(pack, _review_all(pack))
    record_pass(pack, [item_id], "Owner", "checked")
    review = load_reviews(pack)[item_id]
    assert review.status == "signed_off"
    assert review.signed_off_by == "Owner"
    assert review.signed_off_at is not None


def test_record_pass_refuses_draft(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    before = pack.reviews_path.read_bytes() if pack.reviews_path.exists() else None
    with pytest.raises(ReviewGateError):
        record_pass(pack, [next(iter(item_hashes(pack)))], "Owner")
    assert (pack.reviews_path.read_bytes() if pack.reviews_path.exists() else None) == before


def test_record_error(fixture_pack, monkeypatch):
    pack = load_pack("fx", fixture_pack)
    item_id = next(iter(item_hashes(pack)))
    record_error(pack, [item_id], "Owner", "incorrect")
    assert load_reviews(pack)[item_id].status == "draft"
    assert "audit error" in load_reviews(pack)[item_id].notes
    line = Path(review_module.REGRESSIONS_PATH).read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(line)["item"]["id"] == item_id


def test_release_refuses_unusable(fixture_pack):
    pack = load_pack("fx", fixture_pack)
    with pytest.raises(ReviewGateError, match="fx_topic.n0"):
        record_release(pack, "Owner")


def _load_script(name):
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_sheet_order_and_determinism(fixture_pack, tmp_path):
    pack = load_pack("fx", fixture_pack)
    reviews = _review_all(pack)
    first = next(iter(reviews))
    reviews[first] = ReviewMeta(status="needs_expert", content_sha256=item_hashes(pack)[first])
    save_reviews(pack, reviews)
    module = _load_script("review_sheet.py")
    out1 = tmp_path / "one.md"
    out2 = tmp_path / "two.md"
    assert module.main(["--pack", "fx", "--packs-dir", str(fixture_pack), "--seed", "1", "--out", str(out1)]) == 0
    assert module.main(["--pack", "fx", "--packs-dir", str(fixture_pack), "--seed", "1", "--out", str(out2)]) == 0
    assert out1.read_bytes() == out2.read_bytes()
    report = out1.read_text(encoding="utf-8")
    assert report.index("### fx_topic.n0") < report.index("## Sample for sign-off")


def test_record_audit_cli_exit_code(fixture_pack):
    module = _load_script("record_audit.py")
    item_id = next(iter(item_hashes(load_pack("fx", fixture_pack))))
    assert module.main(["--pack", "fx", "--packs-dir", str(fixture_pack), "--by", "Owner", "--pass", item_id]) == 1
