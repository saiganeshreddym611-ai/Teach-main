"""T30: claim-level grading with citations - _finalise(), omissions, passages block, mock grader."""
from __future__ import annotations

from pathlib import Path

import pytest

from tutor.content import load_pack
from tutor.contracts.grading import Claim, ClaimJudgment, GraderOutput, NodeVerdictV2
from tutor.grader import MockGrader, _finalise, omissions
from tutor.grading_links import NodeLinks, passages_block
from tutor.models import NodeStatus
from tutor.retrieval import get_retriever

FIXTURES = Path(__file__).parent / "fixtures" / "packs"


@pytest.fixture
def pack():
    return load_pack("fixture_115", packs_dir=FIXTURES)


@pytest.fixture
def links(pack):
    retriever = get_retriever(pack)
    return NodeLinks({n.id: retriever.for_node(n.id) for n in pack.curriculum.tree.nodes}, retriever.corpus)


def v(node_id, status="VERIFIED", **kw):
    return NodeVerdictV2(node_id=node_id, status=NodeStatus(status), confidence=0.9, evidence="said it", **kw)


def test_finalise_drops_unknown_nodes(pack, links):
    out, fixes = _finalise(pack.curriculum, GraderOutput(verdicts=[v("fixture_115.one"), v("not.a.node")], summary="s"), links)
    assert [x.node_id for x in out.verdicts] == ["fixture_115.one"]
    assert fixes["unknown_node"] == 1


def test_finalise_drops_foreign_passages(pack, links):
    raw = GraderOutput(
        verdicts=[v("fixture_115.one", passage_ids=["IndAS115.para.10", "IndAS37.para.66", "nope", "IndAS115.para.10"])],
        claims=[Claim(claim_id="x", quote="q", node_id="fixture_115.two", judgment=ClaimJudgment.ACCURATE,
                      passage_ids=["IndAS115.para.B29", "IndAS115.para.9"])],
        summary="s",
    )
    out, fixes = _finalise(pack.curriculum, raw, links)
    assert out.verdicts[0].passage_ids == ["IndAS115.para.10"]
    assert out.verdicts[0].citation_origin == "model"
    assert out.claims[0].passage_ids == ["IndAS115.para.B29"]
    assert out.claims[0].claim_id == "c1"
    assert fixes["dropped_passage"] == 4  # para 37.66, "nope", the duplicate, and para 9 on the claim


def test_finalise_adds_node_link_citation(pack, links):
    raw = GraderOutput(verdicts=[v("fixture_115.two", "PARTIAL"), v("fixture_115.three", "NOT_MENTIONED")], summary="s")
    out, fixes = _finalise(pack.curriculum, raw, links)
    graded, not_mentioned = out.verdicts
    assert graded.passage_ids == ["IndAS115.para.B28"]
    assert graded.citation_origin == "node_link"
    assert not_mentioned.passage_ids == []
    assert fixes["node_link_added"] == 1


def test_finalise_drops_bad_indexes(pack, links):
    raw = GraderOutput(verdicts=[v("fixture_115.one", rubric_items_met=[0, 1, -1, 0], misconception_ids=[0])], summary="s")
    out, fixes = _finalise(pack.curriculum, raw, links)
    assert out.verdicts[0].rubric_items_met == [0]
    assert out.verdicts[0].misconception_ids == []
    assert fixes["dropped_rubric_index"] == 3
    assert fixes["dropped_misconception_index"] == 1


def test_finalise_keeps_off_syllabus_claims_ungraded(pack, links):
    raw = GraderOutput(
        verdicts=[],
        claims=[Claim(claim_id="z", quote="GST is 18%", node_id="made.up", judgment=ClaimJudgment.OFF_SYLLABUS)],
        summary="s",
    )
    out, fixes = _finalise(pack.curriculum, raw, links)
    assert out.claims[0].node_id is None
    assert out.claims[0].judgment == ClaimJudgment.OFF_SYLLABUS
    assert fixes["unknown_claim_node"] == 1


def test_omissions_list_unevidenced_level1_nodes_with_citations(pack, links):
    out = GraderOutput(verdicts=[v("fixture_115.one"), v("fixture_115.two", "NOT_MENTIONED")], summary="s")
    missing = omissions(pack.curriculum, out, links)
    assert [o.node_id for o in missing] == ["fixture_115.two", "fixture_115.three", "fixture_115.four"]
    assert missing[0].citations[0].label == "Ind AS 115, para B28"
    assert missing[1].citations[0].label == "Ind AS 37, para 66"


def test_passages_block_stable(pack, links):
    first = passages_block(pack.curriculum, links)
    second = passages_block(pack.curriculum, links)
    assert first == second
    text = first["text"]
    assert first["cache_control"] == {"type": "ephemeral"}
    ids = [line.split('"')[1] for line in text.splitlines() if line.startswith("<passage id=")]
    assert ids[:4] == ["IndAS115.para.9", "IndAS115.para.10", "IndAS115.para.11", "IndAS115.para.22"]
    assert len(ids) == len(set(ids))
    assert passages_block(pack.curriculum, NodeLinks()) is None


def test_passages_block_focus_only_when_too_big(pack, links, monkeypatch):
    monkeypatch.setattr("tutor.grading_links.PASSAGES_BLOCK_TOKEN_LIMIT", 10)
    focused = passages_block(pack.curriculum, links, focus_node_id="fixture_115.three")
    assert "IndAS37.para.66" in focused["text"] and "IndAS115.para.9" not in focused["text"]
    full = passages_block(pack.curriculum, links)  # diagnostic: no focus, full block
    assert "IndAS115.para.9" in full["text"]


async def test_mock_grader_v2(monkeypatch, pack, links):
    monkeypatch.setattr("tutor.grader.node_links", lambda curriculum: links)
    out = await MockGrader().grade(pack.curriculum, "fixture three test", focus_node_id=None,
                                   prior_context="", session_id="t")
    by_node = {c.node_id: c for c in out.claims}
    assert by_node["fixture_115.three"].passage_ids == ["IndAS37.para.66"]
    assert all(c.judgment == ClaimJudgment.ACCURATE for c in out.claims)
    three = next(x for x in out.verdicts if x.node_id == "fixture_115.three")
    assert three.passage_ids == ["IndAS37.para.66"] and three.citation_origin == "node_link"
    assert [c.claim_id for c in out.claims] == [f"c{i}" for i in range(1, len(out.claims) + 1)]
