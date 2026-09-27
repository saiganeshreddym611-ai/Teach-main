"""Tests for grader audit log, memoisation, and determinism."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from tutor.config import settings
from tutor.grader import MockGrader
from tutor.grader_audit import (
    GradeMemo,
    citation_diffs,
    grade_memo,
    memo_key,
    new_call_id,
    sha256_text,
    write_capture,
)
from tutor.grading_links import offered_passage_ids, passages_block
from tutor.llm import get_grader
from tutor.contracts.grading import GraderOutput, NodeVerdictV2
from tutor.models import NodeStatus
from tests.conftest import ScriptedGrader, ScriptedTutor


def test_new_call_id_format():
    cid = new_call_id()
    assert len(cid) == 32  # uuid4().hex
    assert all(c in "0123456789abcdef" for c in cid)


def test_sha256_text():
    h = sha256_text("hello")
    assert len(h) == 64
    assert h == sha256_text("hello")
    assert h != sha256_text("world")


def test_memo_key_deterministic():
    k1 = memo_key("mock", "2", "sys", "user")
    k2 = memo_key("mock", "2", "sys", "user")
    assert k1 == k2
    assert len(k1) == 64
    # Different inputs give different keys
    assert memo_key("mock", "2", "sys", "user2") != k1
    assert memo_key("mock", "3", "sys", "user") != k1
    assert memo_key("ollama", "2", "sys", "user") != k1


def test_grade_memo_get_put():
    from tutor.contracts.grading import GraderOutput
    from tutor.models import NodeStatus

    memo = GradeMemo()
    output = GraderOutput(verdicts=[], summary="test")
    memo.put("key1", output, "call1")
    got = memo.get("key1")
    assert got is not None
    assert got[1] == "call1"
    assert got[0].summary == "test"
    # Miss returns None
    assert memo.get("key2") is None


def test_grade_memo_eviction():
    memo = GradeMemo(max_size=2)
    o1 = GraderOutput(verdicts=[], summary="1")
    o2 = GraderOutput(verdicts=[], summary="2")
    o3 = GraderOutput(verdicts=[], summary="3")
    memo.put("a", o1, "c1")
    memo.put("b", o2, "c2")
    assert memo.get("a") is not None
    assert memo.get("b") is not None
    memo.put("c", o3, "c3")  # should evict oldest "a"
    assert memo.get("a") is None
    assert memo.get("b") is not None
    assert memo.get("c") is not None


def test_grade_memo_clear():
    memo = GradeMemo()
    memo.put("k", GraderOutput(verdicts=[], summary="x"), "c")
    memo.clear()
    assert memo.get("k") is None


async def test_memo_hit_skips_second_call(curriculum):
    """Two identical calls: inner called once; equal outputs; 2 capture files; second has memo_hit true."""
    from tutor.grader_audit import grade_memo

    class CountingGrader:
        def __init__(self, inner):
            self.inner = inner
            self.call_count = 0

        async def grade(self, curriculum, transcript, *, focus_node_id, prior_context, session_id, student_id: str = "", call_id: str | None = None):
            self.call_count += 1
            return await self.inner.grade(
                curriculum, transcript, focus_node_id=focus_node_id, prior_context=prior_context,
                session_id=session_id, student_id=student_id, call_id=call_id
            )

    inner = CountingGrader(MockGrader())
    from tutor.grader import MemoGrader
    memo_grader = MemoGrader(inner, "mock")

    transcript = "Step 1 is identify the contract. Step 2 is identify performance obligations."
    # First call
    res1 = await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")
    # Second call - should hit memo
    res2 = await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

    # Inner grader should only have been called once
    assert inner.call_count == 1
    # Check capture files
    files = list(settings.grader_capture_dir.glob("*.json"))
    assert len(files) == 2
    # Load both files
    captures = [json.loads(f.read_text()) for f in files]
    # Find the miss and hit captures
    miss_capture = next(c for c in captures if not c["memo_hit"])
    hit_capture = next(c for c in captures if c["memo_hit"])
    # Miss capture should be first call, hit capture should reference it
    assert hit_capture["memo_of"] == miss_capture["grader_call_id"]
    # Outputs should be equal
    assert res1.summary == res2.summary
    assert [v.node_id for v in res1.verdicts] == [v.node_id for v in res2.verdicts]


async def test_memo_miss_on_changed_input(curriculum):
    """Changing the transcript, focus or prior context makes a new inner call."""
    inner = MockGrader()
    from tutor.grader import MemoGrader
    memo_grader = MemoGrader(inner, "mock")

    transcript1 = "Step 1 is identify the contract."
    transcript2 = "Step 2 is identify performance obligations."

    await memo_grader.grade(curriculum, transcript1, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")
    await memo_grader.grade(curriculum, transcript2, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

    files = list(settings.grader_capture_dir.glob("*.json"))
    assert len(files) == 2
    # Both should be memo_hit false (different inputs)
    f1 = json.loads(files[0].read_text())
    f2 = json.loads(files[1].read_text())
    assert f1["memo_hit"] is False
    assert f2["memo_hit"] is False


async def test_memo_miss_on_prompt_version(curriculum):
    """Monkeypatched PROMPT_VERSION makes a miss."""
    from tutor import prompts
    original_prompt_version = prompts.PROMPT_VERSION
    try:
        inner = MockGrader()
        from tutor.grader import MemoGrader
        memo_grader = MemoGrader(inner, "mock")

        transcript = "Step 1 is identify the contract."
        await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

        prompts.PROMPT_VERSION = "999"
        await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

        files = list(settings.grader_capture_dir.glob("*.json"))
        assert len(files) == 2
        captures = [json.loads(f.read_text()) for f in files]
        # Both should be misses (different prompt versions)
        for c in captures:
            assert c["memo_hit"] is False
        # One should have prompt_version=2, the other=999
        versions = {c["prompt_version"] for c in captures}
        assert versions == {"2", "999"}
    finally:
        prompts.PROMPT_VERSION = original_prompt_version


async def test_memo_miss_on_content_change(curriculum):
    """A curriculum with one rubric line changed makes a miss."""
    inner = MockGrader()
    from tutor.grader import MemoGrader
    memo_grader = MemoGrader(inner, "mock")

    transcript = "Step 1 is identify the contract."
    await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

    # Create a modified curriculum by changing a rubric
    from tutor.curriculum import Curriculum
    from tutor.models import Tree, Node
    modified_tree = Tree(
        topic_id=curriculum.tree.topic_id,
        subject=curriculum.tree.subject,
        standard=curriculum.tree.standard,
        opening_prompt=curriculum.tree.opening_prompt,
        nodes=[
            Node(
                id=n.id,
                level=n.level,
                parent=n.parent,
                title=n.title,
                chapter=n.chapter,
                rubric=n.rubric + ["extra rubric"] if n.id == "ind_as_115.step_1" else n.rubric,
                misconceptions=n.misconceptions,
                canonical_explanation=n.canonical_explanation,
                example=n.example,
                source_refs=n.source_refs,
            )
            for n in curriculum.tree.nodes
        ],
    )
    modified_curriculum = Curriculum(modified_tree, content_hash="modified")

    await memo_grader.grade(modified_curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

    files = list(settings.grader_capture_dir.glob("*.json"))
    assert len(files) == 2
    f1 = json.loads(files[0].read_text())
    f2 = json.loads(files[1].read_text())
    assert f1["memo_hit"] is False
    assert f2["memo_hit"] is False
    assert f1["content_hash"] != f2["content_hash"]


async def test_memo_disabled(curriculum):
    """grade_memo=False: two inner calls."""
    settings.grade_memo = False
    try:
        inner = MockGrader()
        from tutor.grader import MemoGrader
        memo_grader = MemoGrader(inner, "mock")

        transcript = "Step 1 is identify the contract."
        await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")
        await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

        files = list(settings.grader_capture_dir.glob("*.json"))
        files.sort(key=lambda p: json.loads(p.read_text())["ts"])
        assert len(files) == 2
        f1 = json.loads(files[0].read_text())
        f2 = json.loads(files[1].read_text())
        # Both should not be memo hits
        assert f1["memo_hit"] is False
        assert f2["memo_hit"] is False
    finally:
        settings.grade_memo = True


async def test_memo_returns_copy(curriculum):
    """Mutating a returned output does not change the next hit."""
    inner = MockGrader()
    from tutor.grader import MemoGrader
    memo_grader = MemoGrader(inner, "mock")

    transcript = "Step 1 is identify the contract."
    res1 = await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")
    # Mutate the returned output
    res1.summary = "MUTATED"
    res2 = await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")
    # The second hit should have the original summary
    assert res2.summary != "MUTATED"


async def test_capture_has_audit_fields(curriculum):
    """OllamaGrader with fake client writes capture with all required fields."""
    from tutor.grader import OllamaGrader
    from tutor.contracts.grading import GraderOutput

    class FakeOllama:
        def __init__(self):
            self.calls = []

        async def chat(self, **kw):
            self.calls.append(kw)
            from types import SimpleNamespace
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({
                    "verdicts": [{"node_id": "ind_as_115.step_1", "status": "VERIFIED", "confidence": 0.9, "evidence": "said it"}],
                    "summary": "ok",
                })),
                model="fake-model", prompt_eval_count=100, eval_count=50, total_duration=2_000_000_000,
            )

    fake = FakeOllama()
    grader = OllamaGrader(client=fake, model="fake-model")
    await grader.grade(curriculum, "test", focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

    files = list(settings.grader_capture_dir.glob("*.json"))
    assert len(files) == 1
    f = json.loads(files[0].read_text())
    assert f["student_id"] == "stu1"
    assert f["prompt_version"] == "2"
    assert f["content_hash"] == curriculum.content_hash
    assert len(f["system_sha256"]) == 64
    assert "offered_passage_ids" in f
    assert "corrections" in f
    assert "latency_ms" in f
    assert "phase" in f
    assert f["phase"] == "diagnostic"
    assert f["memo_hit"] is False
    assert f["memo_of"] is None


async def test_capture_disabled(curriculum):
    """No file when capture_grader_calls=False."""
    settings.capture_grader_calls = False
    try:
        inner = MockGrader()
        from tutor.grader import MemoGrader
        memo_grader = MemoGrader(inner, "mock")

        transcript = "Step 1 is identify the contract."
        await memo_grader.grade(curriculum, transcript, focus_node_id=None, prior_context="", session_id="s1", student_id="stu1")

        files = list(settings.grader_capture_dir.glob("*.json"))
        assert len(files) == 0
    finally:
        settings.capture_grader_calls = True


def _fixture_links():
    """fixture_115 has a corpus, unlike the default pack, so these tests never skip."""
    from tutor.content import load_pack
    from tutor.grading_links import NodeLinks
    from tutor.retrieval import get_retriever

    pack = load_pack("fixture_115", packs_dir=Path(__file__).parent / "fixtures" / "packs")
    retriever = get_retriever(pack)
    links = NodeLinks({n.id: retriever.for_node(n.id) for n in pack.curriculum.tree.nodes}, retriever.corpus)
    return pack.curriculum, links


def _block_ids(block) -> list[str]:
    return re.findall(r'<passage id="([^"]+)">', block["text"])


def test_offered_ids_match_block():
    """The ids from a regex over the passages_block text equal offered_passage_ids."""
    curriculum, links = _fixture_links()
    offered = offered_passage_ids(curriculum, links, focus_node_id=None)
    assert offered and _block_ids(passages_block(curriculum, links, None)) == offered


def test_offered_ids_focus_only_when_over_limit(monkeypatch):
    """Over the token limit, a teach-back block and its offered ids hold only the focus node's passages."""
    curriculum, links = _fixture_links()
    focus = next(n.id for n in curriculum.tree.nodes if links.ids(n.id))
    assert set(links.ids(focus)) < links.all_ids()  # the focus-only block is really smaller
    monkeypatch.setattr("tutor.grading_links.PASSAGES_BLOCK_TOKEN_LIMIT", 0)
    offered = offered_passage_ids(curriculum, links, focus_node_id=focus)
    assert offered == links.ids(focus)
    assert _block_ids(passages_block(curriculum, links, focus)) == offered


def test_citation_diffs():
    """Same status and different passage ids give one line naming the node; identical runs give []."""
    v1 = NodeVerdictV2(node_id="n1", status=NodeStatus.VERIFIED, confidence=0.9, evidence="e", passage_ids=["p1"])
    v2 = NodeVerdictV2(node_id="n1", status=NodeStatus.VERIFIED, confidence=0.9, evidence="e", passage_ids=["p2"])
    v3 = NodeVerdictV2(node_id="n1", status=NodeStatus.VERIFIED, confidence=0.9, evidence="e", passage_ids=["p1"])
    r1 = GraderOutput(verdicts=[v1], summary="s")
    r2 = GraderOutput(verdicts=[v2], summary="s")
    r3 = GraderOutput(verdicts=[v3], summary="s")

    diffs = citation_diffs([r1, r2], ["n1"])
    assert len(diffs) == 1
    assert "n1" in diffs[0]

    diffs = citation_diffs([r1, r3], ["n1"])
    assert diffs == []


async def test_ledger_events_carry_call_id(curriculum):
    """Diagnostic via ScriptedGrader: every event's grader_call_id equals the call_id the grader received."""
    from tutor.contracts.grading import GraderOutput, NodeVerdictV2
    from tutor.models import Session, NodeStatus
    from tutor.state_machine import run_turn
    from tutor.grader_audit import new_call_id

    grader_results = [
        GraderOutput(verdicts=[NodeVerdictV2(node_id="ind_as_115.step_1", status=NodeStatus.VERIFIED, confidence=0.9, evidence="e")], summary="ok"),
        GraderOutput(verdicts=[NodeVerdictV2(node_id="ind_as_115.step_2", status=NodeStatus.GAP, confidence=0.5, evidence="e")], summary="ok"),
    ]
    scripted_grader = ScriptedGrader(grader_results)
    scripted_tutor = ScriptedTutor(["Hello?"])

    session = Session(student_id="stu1", topic_id="ind_as_115")

    events = []
    async for ev in run_turn(session, "I know step 1", curriculum, scripted_grader, scripted_tutor):
        events.append(ev)

    # Check that ledger events have grader_call_id matching the grader's call
    done_events = [ev for ev in events if ev.kind == "done"]
    assert done_events, "Expected at least one done event"
    for ev in done_events:
        ledger_delta = ev.payload["ledger_delta"]
        assert ledger_delta, "Expected non-empty ledger_delta"
        for ledger_ev in ledger_delta:
            assert ledger_ev["grader_call_id"] is not None
            # The call_id should match the first call the grader received (diagnostic)
            assert ledger_ev["grader_call_id"] == scripted_grader.calls[0]["call_id"]


async def test_grader_usage_totals():
    """Claude, Ollama and memo-hit records sum correctly per phase."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from grader_usage import summarise

    records = [
        # Claude diagnostic
        {"phase": "diagnostic", "memo_hit": False, "usage": {"input_tokens": 100, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5, "output_tokens": 50}, "latency_ms": 100},
        # Ollama teach_back
        {"phase": "teach_back", "memo_hit": False, "usage": {"prompt_eval_count": 200, "eval_count": 80}, "latency_ms": 200},
        # Memo hit diagnostic
        {"phase": "diagnostic", "memo_hit": True, "usage": None, "latency_ms": 0},
        # Another Ollama teach_back
        {"phase": "teach_back", "memo_hit": False, "usage": {"prompt_eval_count": 150, "eval_count": 60}, "latency_ms": 150},
        # Claude with null cache fields
        {"phase": "diagnostic", "memo_hit": False, "usage": {"input_tokens": 50, "cache_read_input_tokens": None, "cache_creation_input_tokens": None, "output_tokens": 25}, "latency_ms": 50},
    ]
    summary = summarise(records)
    assert summary["diagnostic"]["calls"] == 3
    assert summary["diagnostic"]["memo_hits"] == 1
    assert summary["diagnostic"]["input"] == 150
    assert summary["diagnostic"]["cache_read"] == 10
    assert summary["diagnostic"]["cache_write"] == 5
    assert summary["diagnostic"]["output"] == 75
    assert summary["teach_back"]["calls"] == 2
    assert summary["teach_back"]["memo_hits"] == 0
    assert summary["teach_back"]["input"] == 350
    assert summary["teach_back"]["output"] == 140
