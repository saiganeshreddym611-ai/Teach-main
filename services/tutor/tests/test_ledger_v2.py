"""Ledger v2 tests (T31)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tutor import main
from tutor.contracts.api import StudentLedger, LedgerTrace
from tutor.curriculum import load_curriculum
from tutor.grader import MockGrader
from tutor.ledger import (
    append_verdicts,
    export_ledger,
    mastery_view,
    project_confidence,
    project_status,
    student_events,
)
from tutor.models import NodeStatus, Phase, Session
from tutor.retrieval.corpus import load_corpus
from tutor.state_machine import run_turn
from tutor.store import ledger_store
from tutor.tutor_voice import MockTutor
from tests.conftest import ScriptedGrader, ScriptedTutor, result, verdict


@pytest.fixture(autouse=True)
def use_mocks(monkeypatch):
    monkeypatch.setattr(main, "get_grader", lambda: MockGrader())
    monkeypatch.setattr(main, "get_tutor", lambda: MockTutor())


# --------------------------------------------------------------------------- #
# Cross-session projection
# --------------------------------------------------------------------------- #
def test_cross_session_projection(session, curriculum):
    # Student s1 verifies a node in session A
    session_a = Session(student_id="s1", topic_id="ind_as_115")
    append_verdicts(session_a, [verdict("ind_as_115.step_1", "VERIFIED")], "t1", Phase.DIAGNOSTIC)

    # In a new session B (same student): project_status(B) shows VERIFIED
    session_b = Session(student_id="s1", topic_id="ind_as_115")
    assert project_status(session_b)["ind_as_115.step_1"] == NodeStatus.VERIFIED

    # B.ledger == [] (session ledger is empty)
    assert session_b.ledger == []

    # mastery_view(B) shows VERIFIED
    view = mastery_view(session_b, curriculum)
    assert next(m for m in view if m.node_id == "ind_as_115.step_1").status == NodeStatus.VERIFIED


# --------------------------------------------------------------------------- #
# Student isolation
# --------------------------------------------------------------------------- #
def test_students_are_isolated(session, curriculum):
    append_verdicts(session, [verdict("ind_as_115.step_1", "VERIFIED")], "t1", Phase.DIAGNOSTIC)

    # Student s2 sees nothing from s1
    session_s2 = Session(student_id="s2", topic_id="ind_as_115")
    assert project_status(session_s2).get("ind_as_115.step_1", NodeStatus.NOT_MENTIONED) == NodeStatus.NOT_MENTIONED
    assert student_events(session_s2) == []


# --------------------------------------------------------------------------- #
# Returning student not re-taught
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_returning_student_not_retaught(curriculum):
    from tutor.node_selector import select_next_node

    # First assert that select_next_node on an empty status picks node X
    empty_status = {}
    first_node = select_next_node(curriculum, empty_status, [], depth_first=True)
    assert first_node is not None

    # Record X as VERIFIED for s1 in session A
    session_a = Session(student_id="s1", topic_id="ind_as_115")
    append_verdicts(session_a, [verdict(first_node, "VERIFIED")], "t1", Phase.DIAGNOSTIC)

    # Then run a real run_turn diagnostic in a new session B
    # (ScriptedGrader returning a GraderOutput with no verdicts, ScriptedTutor)
    session_b = Session(student_id="s1", topic_id="ind_as_115")
    grader = ScriptedGrader([result()])  # No verdicts
    tutor = ScriptedTutor(["Let's begin."])

    events = []
    async for ev in run_turn(session_b, "I know nothing", curriculum, grader, tutor):
        events.append(ev)

    # Assert B.target_node is not X
    done_event = next(e for e in events if e.kind == "done")
    assert done_event.payload["target_node"] != first_node


# --------------------------------------------------------------------------- #
# Incidental downgrade blocked across sessions
# --------------------------------------------------------------------------- #
def test_incidental_downgrade_blocked_across_sessions(session, curriculum):
    # VERIFIED in session A
    session_a = Session(student_id="s1", topic_id="ind_as_115")
    append_verdicts(session_a, [verdict("ind_as_115.step_1", "VERIFIED")], "t1", Phase.DIAGNOSTIC)

    # PARTIAL on a diagnostic in session B (not focused): nothing written
    session_b = Session(student_id="s1", topic_id="ind_as_115")
    written = append_verdicts(session_b, [verdict("ind_as_115.step_1", "PARTIAL")], "t2", Phase.DIAGNOSTIC)
    assert written == []
    assert project_status(session_b)["ind_as_115.step_1"] == NodeStatus.VERIFIED


# --------------------------------------------------------------------------- #
# Focused downgrade recorded
# --------------------------------------------------------------------------- #
def test_focused_downgrade_recorded(session, curriculum):
    # VERIFIED in session A
    session_a = Session(student_id="s1", topic_id="ind_as_115")
    append_verdicts(session_a, [verdict("ind_as_115.step_1", "VERIFIED")], "t1", Phase.DIAGNOSTIC)

    # GAP on a focused teach-back in session B with grader_call_id="g1"
    session_b = Session(student_id="s1", topic_id="ind_as_115")
    written = append_verdicts(
        session_b,
        [verdict("ind_as_115.step_1", "GAP")],
        "t2",
        Phase.TEACH_BACK,
        focus_node_ids={"ind_as_115.step_1"},
        grader_call_id="g1",
    )

    # One event with source="teach_back", session_id=B.id, the evidence and "g1"; the status is GAP
    assert len(written) == 1
    ev = written[0]
    assert ev.source == "teach_back"
    assert ev.session_id == session_b.id
    assert ev.evidence_turn_id == "t2"
    assert ev.grader_call_id == "g1"
    assert ev.status == NodeStatus.GAP
    assert project_status(session_b)["ind_as_115.step_1"] == NodeStatus.GAP


# --------------------------------------------------------------------------- #
# Event fields filled
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_event_fields_filled(curriculum):
    session = Session(student_id="s1", topic_id="ind_as_115")
    grader = ScriptedGrader([result(verdict("ind_as_115.step_1", "VERIFIED"))])
    tutor = ScriptedTutor(["Let's continue."])

    events = []
    async for ev in run_turn(session, "I know about contracts", curriculum, grader, tutor):
        events.append(ev)

    # Find the ledger delta in the done event
    done_event = next(e for e in events if e.kind == "done")
    ledger_delta = done_event.payload["ledger_delta"]

    assert len(ledger_delta) >= 1
    for ld in ledger_delta:
        assert ld["source"] == "diagnostic"
        assert ld["content_version"] == curriculum.content_hash
        assert ld["session_id"] == session.id
        assert ld["grader_call_id"] == grader.calls[0]["call_id"]


# --------------------------------------------------------------------------- #
# Export status mapping
# --------------------------------------------------------------------------- #
def test_export_status_mapping(session, curriculum):
    # We'll test without corpus first (citations will be empty)
    append_verdicts(session, [verdict("ind_as_115.step_1", "VERIFIED", conf=0.9)], "t1", Phase.DIAGNOSTIC)
    append_verdicts(session, [verdict("ind_as_115.step_2", "GAP", conf=0.6)], "t2", Phase.TEACH_BACK, focus_node_ids={"ind_as_115.step_2"})
    append_verdicts(session, [verdict("ind_as_115.step_3", "PARTIAL", conf=0.7)], "t3", Phase.TEACH_BACK, focus_node_ids={"ind_as_115.step_3"})

    events = student_events(session)
    exported = export_ledger("s1", curriculum, events, None)

    # Check every node has an entry
    assert len(exported.nodes) == len(curriculum.tree.nodes)

    # Check status mapping
    by_id = {n.concept_id: n for n in exported.nodes}
    assert by_id["ind_as_115.step_1"].status == "MASTERED"
    assert by_id["ind_as_115.step_2"].status == "GAP_IDENTIFIED"
    assert by_id["ind_as_115.step_3"].status == "PARTIAL"
    assert by_id["ind_as_115.step_4"].status == "NOT_ASSESSED"

    # Check confidence and last_verified from latest event
    assert by_id["ind_as_115.step_1"].confidence_score == 0.9
    assert by_id["ind_as_115.step_2"].confidence_score == 0.6
    assert by_id["ind_as_115.step_3"].confidence_score == 0.7

    # Check last_verified equals the ts of each node's latest event
    for ev in events:
        node_export = by_id[ev.node_id]
        assert node_export.last_verified == ev.ts

    # Check one entry per node
    assert len(exported.events) == 3


# --------------------------------------------------------------------------- #
# Ledger endpoint
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ledger_endpoint():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session
        r = await client.post("/session", json={"student_id": "s1", "topic_id": "ind_as_115"})
        assert r.status_code == 200
        sid = r.json()["session_id"]

        # One diagnostic turn (use transcript that MockGrader recognizes)
        r = await client.post(
            f"/session/{sid}/turn",
            json={
                "transcript": (
                    "the first step of the five step model is identifying the contract with the customer, "
                    "an agreement creating enforceable rights and obligations, written oral or implied"
                )
            },
        )
        assert r.status_code == 200

        # Get ledger
        r = await client.get("/students/s1/ledger")
        assert r.status_code == 200
        ledger = StudentLedger.model_validate(r.json())

        # Has every node
        curriculum = load_curriculum("ind_as_115")
        assert len(ledger.nodes) == len(curriculum.tree.nodes)

        # Has raw events
        assert len(ledger.events) >= 1


# --------------------------------------------------------------------------- #
# Trace returns exact turn text
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_trace_returns_exact_turn_text():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/session", json={"student_id": "s1", "topic_id": "ind_as_115"})
        sid = r.json()["session_id"]

        transcript = (
            "the first step of the five step model is identifying the contract with the customer, "
            "an agreement creating enforceable rights and obligations, written oral or implied"
        )
        r = await client.post(f"/session/{sid}/turn", json={"transcript": transcript})
        assert r.status_code == 200

        # Get the first event ID from the ledger
        r = await client.get("/students/s1/ledger")
        ledger = StudentLedger.model_validate(r.json())
        assert len(ledger.events) >= 1
        event_id = ledger.events[0].id

        # Get trace
        r = await client.get(f"/students/s1/ledger/{event_id}/trace")
        assert r.status_code == 200
        trace = LedgerTrace.model_validate(r.json())

        assert trace.student_turn == transcript
        assert trace.grader_call_id is not None


# --------------------------------------------------------------------------- #
# Trace 404 for other student
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_trace_404_for_other_student():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/session", json={"student_id": "s1", "topic_id": "ind_as_115"})
        sid = r.json()["session_id"]

        transcript = (
            "the first step of the five step model is identifying the contract with the customer, "
            "an agreement creating enforceable rights and obligations, written oral or implied"
        )
        r = await client.post(f"/session/{sid}/turn", json={"transcript": transcript})

        r = await client.get("/students/s1/ledger")
        ledger = StudentLedger.model_validate(r.json())
        assert len(ledger.events) >= 1
        event_id = ledger.events[0].id

        # Same event ID under /students/other/... returns 404
        r = await client.get(f"/students/other/ledger/{event_id}/trace")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Delete student
# --------------------------------------------------------------------------- #
def test_delete_student(session):
    # Add some events for s1
    append_verdicts(session, [verdict("ind_as_115.step_1", "VERIFIED")], "t1", Phase.DIAGNOSTIC)
    append_verdicts(session, [verdict("ind_as_115.step_2", "GAP")], "t2", Phase.TEACH_BACK, focus_node_ids={"ind_as_115.step_2"})

    # Add events for s2
    session_s2 = Session(student_id="s2", topic_id="ind_as_115")
    append_verdicts(session_s2, [verdict("ind_as_115.step_1", "PARTIAL")], "t3", Phase.DIAGNOSTIC)

    # Delete s1
    count = ledger_store.delete_student("s1")
    assert count == 2

    # s1 events gone
    assert student_events(Session(student_id="s1", topic_id="ind_as_115")) == []

    # s2 events remain
    assert len(student_events(session_s2)) == 1
