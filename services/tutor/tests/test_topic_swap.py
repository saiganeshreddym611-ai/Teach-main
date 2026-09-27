"""T25: a second topic pack (Ind AS 37) runs by switching CONTENT_PACK, with no code changes."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tutor import main
from tutor.config import settings
from tutor.content import clear_pack_cache, load_pack
from tutor.grader import MockGrader
from tutor.retrieval.refs import parse_ref
from tutor.tutor_voice import MockTutor


@pytest.fixture
def ind_as_37(monkeypatch):
    monkeypatch.setattr(main, "get_grader", lambda: MockGrader())
    monkeypatch.setattr(main, "get_tutor", lambda: MockTutor())
    monkeypatch.setattr(settings, "content_pack", "ind_as_37")
    clear_pack_cache()
    yield
    clear_pack_cache()


def test_ind_as_37_pack_shape():
    pack = load_pack("ind_as_37")
    nodes = pack.curriculum.tree.nodes
    assert [n.id for n in nodes if n.level == 1] == [
        "ind_as_37.recognition", "ind_as_37.contingencies", "ind_as_37.measurement",
        "ind_as_37.onerous", "ind_as_37.restructuring", "ind_as_37.reimbursements",
    ]
    assert len(nodes) == 21
    assert all(n.id.startswith("ind_as_37.") and n.rubric and n.source_refs for n in nodes)
    refs = [r for n in nodes for r in n.source_refs]
    assert all(parse_ref(r) and r.startswith("IndAS37.para.") for r in refs)


def test_ind_as_37_refs_resolve_against_mca_text():
    from tutor.retrieval import load_corpus, resolve_ref

    pack = load_pack("ind_as_37")
    corpus = load_corpus(pack)
    assert corpus is not None and corpus.doc("ind_as_37").issuer == "Ministry of Corporate Affairs"
    for node in pack.curriculum.tree.nodes:
        for ref in node.source_refs:
            assert resolve_ref(ref, corpus), (node.id, ref)
    assert corpus.passage("IndAS37.para.68A").text.startswith("68A The cost of fulfilling a contract")


async def test_session_follows_active_pack(ind_as_37):
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        info = (await client.get("/content")).json()
        assert info["topic_id"] == "ind_as_37"
        assert info["standard"].startswith("Ind AS 37")
        r = await client.post("/session", json={"student_id": "s37"})
        assert r.status_code == 200, r.text
        assert "Ind AS 37" in r.json()["opening_prompt"]
        view = (await client.get(f"/session/{r.json()['session_id']}")).json()
        assert view["topic_id"] == "ind_as_37"
        assert {m["node_id"] for m in view["mastery"]} == {n.id for n in load_pack("ind_as_37").curriculum.tree.nodes}
        # A topic from another pack is not served while Ind AS 37 is active.
        assert (await client.post("/session", json={"topic_id": "ind_as_115"})).status_code == 404
