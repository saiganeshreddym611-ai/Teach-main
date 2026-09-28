"""Drive run_turn with scripted grader/tutor and assert the transitions in
the plan's §4.3 table. No network."""
import pytest

from tutor.config import settings
from tutor.ledger import project_status
from tutor.models import NodeStatus, Phase
from tutor.state_machine import run_turn
from tests.conftest import SENT, ScriptedGrader, ScriptedTutor, result, verdict


async def drive(session, curriculum, grader, tutor, transcript):
    events = []
    async for ev in run_turn(session, transcript, curriculum, grader, tutor):
        events.append(ev)
    return events


def kinds(events):
    return [e.kind for e in events]


def spoken(events):
    return "".join(e.payload["delta"] for e in events if e.kind == "text")


# --------------------------------------------------------------------------- #
# DIAGNOSTIC -> INSTRUCT
# --------------------------------------------------------------------------- #
async def test_diagnostic_grades_writes_ledger_and_targets_deepest_missing(session, curriculum):
    grader = ScriptedGrader([
        result(
            verdict("ind_as_115.step_1", "VERIFIED"),
            verdict("ind_as_115.step_2", "VERIFIED"),
            verdict("ind_as_115.step_3", "PARTIAL"),
            summary="Knows steps 1-2, shaky on 3.",
        )
    ])
    tutor = ScriptedTutor(["Nice start. Let's look at transaction price. What is it?"])

    events = await drive(session, curriculum, grader, tutor, "step one identify contract step two obligations step three price maybe")

    assert kinds(events) == ["grade", "text", "text", "text", "text", "text", "text", "text", "text", "done"][: len(events)]
    assert events[0].kind == "grade" and events[-1].kind == "done"
    assert grader.calls[0]["focus"] is None
    # Ledger has the three evidence-bearing verdicts, each pointing at the student turn.
    student_turn_id = events[-1].payload["student_turn_id"]
    assert [e.evidence_turn_id for e in session.ledger] == [student_turn_id] * 3
    assert project_status(session)["ind_as_115.step_3"] == NodeStatus.PARTIAL
    # Steps 4, 5 and cross-cutting were never touched, so this is LEARN mode: the node selector
    # (code, not the LLM) goes depth-first into step 1's details before the next heading.
    assert session.study_mode == "learn"
    assert "STUDY_MODE=LEARN" in tutor.directives[0]
    assert session.phase == Phase.INSTRUCT
    assert session.target_node == "ind_as_115.step_1.criteria"
    assert "ACTION=PROBE" in tutor.directives[0]
    assert "ind_as_115.step_1.criteria" in tutor.directives[0]
    assert session.student_level_summary == "Knows steps 1-2, shaky on 3."
    assert events[-1].payload["phase"] == "INSTRUCT"
    assert len(events[-1].payload["ledger_delta"]) == 3
    # Transcript recorded: student turn + tutor turn.
    assert [t.role for t in session.turns] == ["student", "tutor"]
    assert session.turns[-1].text == "Nice start. Let's look at transaction price. What is it?"


# --------------------------------------------------------------------------- #
# INSTRUCT: no grading; sentinel flips to TEACH_BACK; forced after N turns
# --------------------------------------------------------------------------- #
async def test_instruct_turn_does_not_grade_and_sentinel_moves_to_teach_back(session, curriculum):
    session.phase = Phase.INSTRUCT
    session.target_node = "ind_as_115.step_4"
    grader = ScriptedGrader([])  # any call would IndexError
    tutor = ScriptedTutor(["Right. Now explain allocation back to me with an example. " + SENT])

    events = await drive(session, curriculum, grader, tutor, "so it's based on standalone prices?")

    assert "grade" not in kinds(events)
    assert grader.calls == []
    assert "ACTION=CONTINUE" in tutor.directives[0]
    assert SENT not in spoken(events)
    assert session.turns[-1].text == "Right. Now explain allocation back to me with an example."
    assert session.phase == Phase.TEACH_BACK
    assert session.instruct_turns_on_node == 1


async def test_instruct_without_sentinel_stays_in_instruct(session, curriculum):
    session.phase = Phase.INSTRUCT
    session.target_node = "ind_as_115.step_4"
    tutor = ScriptedTutor(["Not quite. SSP means... Does that help?"])

    await drive(session, curriculum, ScriptedGrader([]), tutor, "is it cost based?")

    assert session.phase == Phase.INSTRUCT


async def test_teach_back_is_forced_after_max_instruct_turns(session, curriculum, monkeypatch):
    monkeypatch.setattr(settings, "max_instruct_turns_per_node", 2)
    session.phase = Phase.INSTRUCT
    session.target_node = "ind_as_115.step_4"
    tutor = ScriptedTutor(["Keep going. Question?", "Ok, explain it back. " + SENT])

    await drive(session, curriculum, ScriptedGrader([]), tutor, "hmm")
    assert "ACTION=CONTINUE" in tutor.directives[0]
    assert session.phase == Phase.INSTRUCT

    await drive(session, curriculum, ScriptedGrader([]), tutor, "ok")
    assert "ACTION=REQUEST_TEACH_BACK" in tutor.directives[1]
    assert session.phase == Phase.TEACH_BACK


# --------------------------------------------------------------------------- #
# TEACH_BACK: verified -> ledger + next node; failed -> retry; twice -> park
# --------------------------------------------------------------------------- #
async def test_teach_back_verified_writes_ledger_and_advances(session, curriculum):
    session.study_mode = "revision"  # heading by heading
    session.phase = Phase.TEACH_BACK
    session.target_node = "ind_as_115.step_1"
    session.turns.append(__import__("tutor.models", fromlist=["Turn"]).Turn(role="tutor", text="Explain step 1 back.", phase=Phase.INSTRUCT))
    grader = ScriptedGrader([result(verdict("ind_as_115.step_1", "VERIFIED", evidence="a contract is an enforceable agreement"))])
    tutor = ScriptedTutor(["Exactly right. Next, performance obligations. What is one?"])

    events = await drive(session, curriculum, grader, tutor, "a contract is an agreement with enforceable rights, oral or written")

    assert grader.calls[0]["focus"] == "ind_as_115.step_1"
    assert grader.calls[0]["prior"] == "Tutor asked: Explain step 1 back."
    assert project_status(session)["ind_as_115.step_1"] == NodeStatus.VERIFIED
    assert session.ledger[-1].phase == Phase.TEACH_BACK
    assert session.phase == Phase.INSTRUCT
    assert session.target_node == "ind_as_115.step_2"
    assert "is now VERIFIED" in tutor.directives[0]
    assert "ACTION=PROBE" in tutor.directives[0]


async def test_teach_back_failed_retries_then_parks(session, curriculum, monkeypatch):
    monkeypatch.setattr(settings, "max_teach_back_attempts", 2)
    session.study_mode = "learn"  # a parked heading's subtopics wait too
    session.phase = Phase.TEACH_BACK
    session.target_node = "ind_as_115.step_1"
    grader = ScriptedGrader([
        result(verdict("ind_as_115.step_1", "PARTIAL", evidence="it's the first step")),
        result(verdict("ind_as_115.step_1", "GAP", evidence="must be written")),
    ])
    tutor = ScriptedTutor([
        "Close. A contract can be oral too. Try again. " + SENT,
        "We'll come back to that. Next, performance obligations. What is one?",
    ])

    # Attempt 1: fail -> back to INSTRUCT on same node, tutor asks again -> TEACH_BACK
    await drive(session, curriculum, grader, tutor, "it's the first step")
    assert "ACTION=TEACH_BACK_FAILED" in tutor.directives[0]
    assert "Attempt 1 of 2" in tutor.directives[0]
    assert session.target_node == "ind_as_115.step_1"
    assert session.phase == Phase.TEACH_BACK  # sentinel re-requested teach-back
    assert session.teach_back_attempts["ind_as_115.step_1"] == 1

    # Attempt 2: fail -> park, move on
    await drive(session, curriculum, grader, tutor, "a contract must be written")
    assert session.parked_nodes == ["ind_as_115.step_1"]
    assert "is parked after 2 attempts" in tutor.directives[1]
    assert session.phase == Phase.INSTRUCT
    assert session.target_node == "ind_as_115.step_2"
    assert project_status(session)["ind_as_115.step_1"] == NodeStatus.GAP


# --------------------------------------------------------------------------- #
# COMPLETE
# --------------------------------------------------------------------------- #
async def test_all_verified_goes_complete(session, curriculum):
    session.phase = Phase.DIAGNOSTIC
    grader = ScriptedGrader([result(*[verdict(n.id, "VERIFIED") for n in curriculum.tree.nodes], summary="Expert.")])
    tutor = ScriptedTutor(["You've mastered all of it. What next?"])

    events = await drive(session, curriculum, grader, tutor, "(a perfect monologue)")

    assert session.phase == Phase.COMPLETE
    assert session.target_node is None
    assert "PHASE=COMPLETE" in tutor.directives[0]
    assert events[-1].payload["phase"] == "COMPLETE"


async def test_complete_phase_keeps_chatting_without_grading(session, curriculum):
    session.phase = Phase.COMPLETE
    tutor = ScriptedTutor(["Ind AS 116 next then. Ready?"])
    events = await drive(session, curriculum, ScriptedGrader([]), tutor, "what next?")
    assert "grade" not in kinds(events)
    assert session.phase == Phase.COMPLETE


async def test_diagnostic_touching_every_heading_chooses_revision(session, curriculum):
    heads = [n.id for n in curriculum.tree.nodes if n.level == 1]
    grader = ScriptedGrader([result(*[verdict(h, "VERIFIED") for h in heads[:-1]], verdict(heads[-1], "PARTIAL"))])
    tutor = ScriptedTutor(["You know the outline. Let's check each heading."])
    await drive(session, curriculum, grader, tutor, "everything, briefly")
    assert session.study_mode == "revision"
    assert "STUDY_MODE=REVISION" in tutor.directives[0]
    assert session.target_node == heads[-1]  # breadth-first: the one heading not yet verified


async def test_learn_mode_details_a_heading_before_the_next(session, curriculum):
    session.study_mode = "learn"
    session.phase = Phase.TEACH_BACK
    session.target_node = "ind_as_115.step_1"
    grader = ScriptedGrader([result(verdict("ind_as_115.step_1", "VERIFIED"))])
    tutor = ScriptedTutor(["Good. Now the criteria in detail."])
    await drive(session, curriculum, grader, tutor, "a contract creates enforceable rights and obligations")
    assert session.target_node == curriculum.children("ind_as_115.step_1")[0].id


# --------------------------------------------------------------------------- #
# T40: probe first, then explain, then the teach-back (code gates the sentinel)
# --------------------------------------------------------------------------- #
SSP = "ind_as_115.step_4.ssp"


def probing(session, node_id=SSP):
    """A session whose tutor has just asked the probe question on `node_id`."""
    session.phase, session.target_node, session.instruct_step = Phase.INSTRUCT, node_id, "PROBE"
    return session


def probe_verdict(status, **kw):
    from tutor.contracts.grading import NodeVerdictV2
    return NodeVerdictV2(node_id=SSP, status=NodeStatus(status), confidence=0.8, evidence="said it", **kw)


async def test_first_turn_on_new_node_is_probe(session, curriculum):
    tutor = ScriptedTutor(["What do you think?"])
    await drive(session, curriculum, ScriptedGrader([result()]), tutor, "I know nothing yet")
    node = curriculum.node(session.target_node)
    assert session.instruct_step == "PROBE"
    assert "ACTION=PROBE" in tutor.directives[0]
    assert node.canonical_explanation not in tutor.directives[0]


async def test_probe_verified_advances(session, curriculum):
    grader = ScriptedGrader([result(probe_verdict("VERIFIED"))])
    tutor = ScriptedTutor(["Well done. Next question?"])
    events = await drive(probing(session), curriculum, grader, tutor, "SSP is the separate selling price...")
    assert grader.calls[0]["focus"] == SSP
    assert [(e.node_id, e.source) for e in session.ledger] == [(SSP, "probe")]
    assert session.target_node != SSP and session.instruct_step == "PROBE"
    assert "grade" in kinds(events) and "ACTION=PROBE" in tutor.directives[0]


async def test_probe_partial_explains_missing_items_only(session, curriculum):
    rubric = curriculum.node(SSP).rubric
    grader = ScriptedGrader([result(probe_verdict("PARTIAL", rubric_items_met=[0]))])
    tutor = ScriptedTutor(["Let me explain the rest."])
    await drive(probing(session), curriculum, grader, tutor, "it's the price you'd sell it for alone")
    directive = tutor.directives[0]
    assert session.instruct_step == "EXPLAIN" and session.target_node == SSP
    assert "ACTION=EXPLAIN" in directive
    assert rubric[0] not in directive and rubric[1] in directive and rubric[2] in directive


async def test_probe_gap_explains_and_corrects(session, curriculum):
    misconception = curriculum.node(SSP).misconceptions[0]
    grader = ScriptedGrader([result(probe_verdict("GAP", misconception_ids=[0]))])
    tutor = ScriptedTutor(["Not quite. Here is how it works."])
    await drive(probing(session), curriculum, grader, tutor, "just use the list price")
    assert session.instruct_step == "EXPLAIN"
    assert "ACTION=EXPLAIN" in tutor.directives[0] and misconception in tutor.directives[0]


async def test_sentinel_ignored_during_probe(session, curriculum):
    tutor = ScriptedTutor(["Explain it back to me. " + SENT])
    events = await drive(session, curriculum, ScriptedGrader([result()]), tutor, "I know nothing yet")
    assert session.instruct_step == "PROBE" and session.phase == Phase.INSTRUCT
    assert "<<" not in spoken(events)


async def test_sentinel_ignored_on_first_explain(session, curriculum):
    grader = ScriptedGrader([result(probe_verdict("GAP"))])
    tutor = ScriptedTutor(["Here is the rule. Now explain it back. " + SENT])
    events = await drive(probing(session), curriculum, grader, tutor, "no idea")
    assert session.instruct_step == "EXPLAIN" and session.phase == Phase.INSTRUCT
    assert "<<" not in spoken(events)


async def test_sentinel_honoured_in_continue(session, curriculum):
    probing(session).instruct_step = "EXPLAIN"  # the tutor has explained; the student replies
    tutor = ScriptedTutor(["Good. Explain it back with an example. " + SENT])
    await drive(session, curriculum, ScriptedGrader([]), tutor, "that makes sense")
    assert session.instruct_step == "CONTINUE" and session.phase == Phase.TEACH_BACK


async def test_teach_back_retry_allows_sentinel(session, curriculum):
    session.phase, session.target_node, session.instruct_step = Phase.TEACH_BACK, SSP, "CONTINUE"
    grader = ScriptedGrader([result(probe_verdict("PARTIAL"))])
    tutor = ScriptedTutor(["Close. The missing point is proportional allocation. Try again. " + SENT])
    await drive(session, curriculum, grader, tutor, "SSP is the price alone")
    assert session.teach_back_attempts[SSP] == 1
    assert session.instruct_step == "CONTINUE" and session.phase == Phase.TEACH_BACK
