"""T23a: grounded review of concept nodes - claims, packets, quote check, decisions, runs."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tutor.config import settings
from tutor.content import clear_pack_cache, load_pack
from tutor.content_review.claims import sentences, split_node
from tutor.content_review.decide import check_answers, verify_quote
from tutor.content_review.evidence import build_packet
from tutor.content_review.models import Answer, Answers, Claim
from tutor.content_review.pipeline import ContentReviewError, build_self_test_pack, ingest_run, review_pack
from tutor.content_review.reviewers import (
    ClaudeApiReviewer,
    MockReviewer,
    ReviewerRefused,
    ScriptedReviewer,
    SessionReviewer,
    get_reviewer,
)
from tutor.contracts.content import ReviewerInfo
from tutor.retrieval import get_retriever
from tutor.review import ReviewGateError, item_hashes, load_reviews, record_claude_review, status_table

FIXTURES = Path(__file__).parent / "fixtures" / "packs"

# What an honest reviewer answers where a claim is not word for word in one passage.
# (node, claim) -> (verdict, passage_id, quote)
HONEST = {
    ("p01", "c4"): ("supported", "IndAS115.para.B30", "has no effect outside this fixture"),
    ("p01", "c5"): ("contradicted", "IndAS115.para.B29", "paints a green stripe on the wooden token"),
    ("p02", "c2"): ("contradicted", "IndAS37.para.67", "A fictional bell rings when the cabinet is opened"),
    ("p02", "c3"): ("supported", "IndAS37.para.68", "bell sound is represented by a paper star"),
    ("p02", "c5"): ("supported", "IndAS37.para.66", "keeps a pretend orange widget in a glass cabinet"),
    ("p03", "c3"): ("supported", "IndAS115.para.22", "Fixture Co groups its imaginary widget notes"),
    ("p04", "c4"): ("supported", "IndAS115.para.B29", "paints a green stripe on the wooden token"),
    ("p05", "c2"): ("supported", "IndAS115.para.27A", "label identifies a purple widget"),
    ("p06", "c3"): ("supported", "IndAS37.para.68", "bell sound is represented by a paper star"),
    ("p06", "c5"): ("supported", "IndAS37.para.67", "bell rings when the cabinet is opened"),
    ("p06", "c6"): ("contradicted", "IndAS37.para.69", "stores that star in an imaginary drawer"),
    ("p07", "c3"): ("supported", "IndAS37.para.68", "bell sound is represented by a paper star"),
    ("p07", "c5"): ("supported", "IndAS37.para.67", "bell rings when the cabinet is opened"),
    ("p08", "c3"): ("contradicted", "IndAS115.para.B30", "has no effect outside this fixture"),
    ("p08", "c4"): ("supported", "IndAS115.para.B29", "paints a green stripe on the wooden token"),
    ("p09", "c2"): ("supported", "IndAS37.para.67", "A fictional bell rings"),
    ("p10", "c3"): ("supported", "IndAS37.para.66", "keeps a pretend orange widget in a glass cabinet"),
}
GAPS = {
    "p03": ["(b): the second note describes a pretend paper widget"],
    "p05": ["IE3: Fixture Co stores an invented widget in a cardboard moon"],
    "p09": ["66: Fixture Co keeps a pretend orange widget in a glass cabinet"],
    "p10": ["68: a paper star represents the bell sound", "69: the star is stored in an imaginary drawer"],
}
EXPECTED_REASON = {
    "reversed_rule": "contradicted by",
    "invented_exception": "not found in the sources",
    "wrong_paragraph": "outside the node's source_refs",
    "missing_rubric_item": "coverage gap",
}


def honest_answers(packet) -> Answers:
    short = packet.item_id.rsplit(".", 1)[1]
    answers = []
    for claim in packet.claims:
        if (short, claim.claim_id) in HONEST:
            verdict, passage_id, quote = HONEST[(short, claim.claim_id)]
        else:
            body = claim.text.rstrip(".")
            hit = next((p for p in packet.passages if body in p.text), None)
            verdict, passage_id, quote = ("supported", hit.passage_id, body) if hit else ("not_found", None, "")
        answers.append(Answer(claim_id=claim.claim_id, verdict=verdict, passage_id=passage_id, quote=quote))
    return Answers(item_id=packet.item_id, answers=answers, coverage_gaps=GAPS.get(short, []))


class HonestReviewer:
    info = ReviewerInfo(mode="session", model="scripted")

    def review(self, packet):
        return honest_answers(packet)


@pytest.fixture
def selftest(tmp_path):
    clear_pack_cache()
    source = load_pack("fixture_115", packs_dir=FIXTURES)
    pack, expectations = build_self_test_pack(source, tmp_path / "packs")
    yield pack, expectations
    clear_pack_cache()


def _packet(pack, node_id, claims=None):
    node = pack.curriculum.node(node_id)
    return build_packet("r", node, claims or split_node(node), get_retriever(pack), item_hashes(pack)[node_id])


def test_split_node_claims(selftest):
    pack, _ = selftest
    claims = split_node(pack.curriculum.node("fixture_115.p06"))
    assert [c.claim_id for c in claims] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert [c.kind for c in claims] == ["rubric"] * 4 + ["explanation", "misconception"]
    assert [c.expect for c in claims] == ["supported"] * 5 + ["contradicted"]
    assert sentences("Revenue is recognised, e.g. on delivery. It is measured at Rs. 500. Then stop.") == [
        "Revenue is recognised, e.g. on delivery.",
        "It is measured at Rs. 500.",
        "Then stop.",
    ]


def test_packet_prefers_node_links(selftest):
    pack, _ = selftest
    packet = _packet(pack, "fixture_115.p09")
    assert packet.passages[0].passage_id == "IndAS37.para.66" and packet.passages[0].linked
    assert all(not p.linked for p in packet.passages[1:])
    assert "IndAS37.para.67" in [p.passage_id for p in packet.passages]
    # The node cites only standards, so study material and RTP text never enter its packet.
    probe = Claim(claim_id="c1", item_id="fixture_115.p09", kind="explanation",
                  text="Fixture Co stores a pretend widget.", expect="supported")
    ids = [p.passage_id for p in _packet(pack, "fixture_115.p09", [probe]).passages]
    assert not any(i.startswith(("ICAI.", "RTP.")) for i in ids)


def test_quote_check(selftest):
    text = "B30 [TEST FIXTURE]  The imaginary stripe has\nno effect   outside this fixture."
    assert verify_quote("has no effect outside this fixture", text)
    assert verify_quote("has  no\neffect outside", text)
    assert not verify_quote("has no effect anywhere", text)
    assert not verify_quote("no effect", text)  # too short to prove anything
    pack, _ = selftest
    packet = _packet(pack, "fixture_115.p01")
    fabricated = Answers(item_id=packet.item_id, answers=[
        Answer(claim_id="c3", verdict="supported", passage_id="IndAS115.para.B30", quote="the stripe matters a lot"),
    ])
    c3 = next(c for c in check_answers(packet, fabricated) if c.claim.claim_id == "c3")
    assert c3.verdict == "not_found" and not c3.quote_verified
    assert "quote not found word for word" in c3.problem


def test_clean_node_becomes_claude_reviewed(selftest, tmp_path):
    pack, _ = selftest
    packet = _packet(pack, "fixture_115.p01")
    reviewer = ScriptedReviewer({"fixture_115.p01": honest_answers(packet)})
    run = review_pack(pack, ["fixture_115.p01"], reviewer=reviewer, run_id="t1", review_dir=tmp_path / "reviews")
    assert run.state == "done"
    assert [(r.item_id, r.status, r.reasons) for r in run.results] == [("fixture_115.p01", "claude_reviewed", [])]
    meta = load_reviews(pack)["fixture_115.p01"]
    assert meta.status == "claude_reviewed" and meta.report_id == "t1"
    assert meta.reviewer == ReviewerInfo(mode="session", model="scripted")
    assert all(c.quote_verified for c in meta.claims)
    assert Path(run.report_path).is_file()


def test_planted_errors_need_expert(selftest, tmp_path):
    pack, expectations = selftest
    run = review_pack(pack, reviewer=HonestReviewer(), run_id="t2", review_dir=tmp_path / "reviews", self_test=expectations)
    assert run.score.caught == run.score.planted == 8
    assert run.score.clean_passed == run.score.clean == 2
    results = {r.item_id: r for r in run.results}
    for item_id, planted in expectations.items():
        if planted:
            assert results[item_id].status == "needs_expert"
            assert any(EXPECTED_REASON[planted] in reason for reason in results[item_id].reasons), (item_id, results[item_id].reasons)
    assert "caught 8/8" in Path(run.report_path).read_text(encoding="utf-8")


def test_session_round_trip(selftest, tmp_path):
    pack, _ = selftest
    review_dir = tmp_path / "reviews"
    items = ["fixture_115.p01", "fixture_115.p05"]
    run = review_pack(pack, items, reviewer=SessionReviewer(), run_id="t3", review_dir=review_dir)
    assert run.state == "pending" and not pack.reviews_path.exists()
    run_dir = review_dir / "runs" / "t3"
    markdown = (run_dir / "fixture_115.p01.md").read_text(encoding="utf-8")
    assert "[linked] IndAS115.para.B28" in markdown and "expect" not in markdown
    with pytest.raises(ContentReviewError, match="not filled in"):
        ingest_run("t3", review_dir)
    for item_id in items:
        packet = _packet(pack, item_id)
        (run_dir / f"{item_id}.answers.json").write_text(honest_answers(packet).model_dump_json(), encoding="utf-8")
    done = ingest_run("t3", review_dir)
    assert {r.item_id: r.status for r in done.results} == {
        "fixture_115.p01": "claude_reviewed", "fixture_115.p05": "needs_expert"}
    assert load_reviews(pack)["fixture_115.p05"].status == "needs_expert"
    with pytest.raises(ContentReviewError, match="already ingested"):
        ingest_run("t3", review_dir)


def test_ollama_reviewer_refused(monkeypatch):
    monkeypatch.setattr(settings, "mock_llm", False)
    with pytest.raises(ReviewerRefused):
        get_reviewer("ollama")
    with pytest.raises(ReviewerRefused):
        get_reviewer("claude-api", model="gemma4:31b-cloud")
    with pytest.raises(ReviewerRefused):
        get_reviewer("claude-api", model="gpt-5")
    monkeypatch.setattr(settings, "reviewer", "ollama")
    with pytest.raises(ReviewerRefused):
        get_reviewer()
    assert isinstance(get_reviewer("session", model="claude-opus-5"), SessionReviewer)


def test_mock_reviewer_runs(monkeypatch, selftest, tmp_path):
    monkeypatch.setattr(settings, "mock_llm", True)
    pack, _ = selftest
    reviewer = get_reviewer("session", model="claude-opus-5")
    assert isinstance(reviewer, MockReviewer)
    run = review_pack(pack, reviewer=reviewer, run_id="t4", review_dir=tmp_path / "reviews")
    assert run.state == "done" and all(r.status == "needs_expert" for r in run.results)
    assert not pack.reviews_path.exists()
    assert "nothing was recorded" in Path(run.report_path).read_text(encoding="utf-8")


def test_edit_resets_review(selftest, tmp_path):
    pack, _ = selftest
    packet = _packet(pack, "fixture_115.p01")
    review_pack(pack, ["fixture_115.p01"], reviewer=ScriptedReviewer({"fixture_115.p01": honest_answers(packet)}),
                run_id="t5", review_dir=tmp_path / "reviews")
    assert status_table(pack)["fixture_115.p01"] == ("node", "claude_reviewed")
    data = json.loads(pack.concept_map_path.read_text(encoding="utf-8"))
    data["nodes"][0]["canonical_explanation"] = "The stripe is edited."
    pack.concept_map_path.write_text(json.dumps(data), encoding="utf-8")
    clear_pack_cache()
    edited = load_pack(pack.pack_id, pack.root.parent)
    assert status_table(edited)["fixture_115.p01"] == ("node", "draft")
    with pytest.raises(ReviewGateError, match="changed since"):
        record_claude_review(edited, "fixture_115.p01", "claude_reviewed", [], ReviewerInfo(mode="session"), "t5",
                             expected_sha256=packet.content_sha256)


def test_claude_api_reviewer_call(selftest):
    pack, _ = selftest
    packet = _packet(pack, "fixture_115.p01")
    calls = []

    class FakeMessages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(stop_reason="end_turn", parsed_output=Answers(item_id="wrong", answers=[]))

    reviewer = ClaudeApiReviewer("claude-opus-5", client=SimpleNamespace(messages=FakeMessages()))
    out = reviewer.review(packet)
    assert out.item_id == "fixture_115.p01"
    assert calls[0]["temperature"] == 0 and calls[0]["output_format"] is Answers
    assert "IndAS115.para.B28" in calls[0]["messages"][0]["content"]
