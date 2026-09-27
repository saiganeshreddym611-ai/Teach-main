from datetime import datetime, timezone

from tutor.contracts import (
    Citation,
    Claim,
    CreateSessionRequest,
    GraderOutput,
    LedgerEvent,
    Omission,
    ParamSpec,
    Passage,
    ReleaseSignoff,
    ReviewMeta,
    ScoredPassage,
    SkillDef,
    SourceDoc,
    TaskAttemptEvent,
    TaskTemplate,
    TurnRequest,
)
from tutor.prompts import PROMPT_VERSION


def test_content_contracts_validate_examples():
    source = SourceDoc(
        doc_id="d1", doc_code="IndAS115", title="Ind AS 115", doc_type="standard",
        issuer="Issuer", authority_rank=1, attempt="2027-05", version="1",
        path="sources/standard.txt", sha256="abc",
    )
    passage = Passage(
        passage_id="IndAS115.para.76", doc_id="d1", doc_type="standard",
        paper="Financial Reporting", chapter="Revenue", section="Allocation",
        locator="para.76", attempt="2027-05", version="1", text="Text", sha256="def",
    )
    assert source.doc_code == "IndAS115"
    assert ScoredPassage(passage=passage, score=1, confidence=0.9).confidence == 0.9
    assert Citation(passage_id=passage.passage_id, label="para 76", doc_id="d1").doc_id == "d1"
    assert ReviewMeta(status="draft", content_sha256="hash").status == "draft"
    assert ReleaseSignoff(
        pack_id="p", version="1", content_hash="hash", signed_off_by="owner", signed_off_at="today"
    ).pack_id == "p"


def test_grading_contracts_validate_examples():
    claim = Claim(
        claim_id="c1", quote="revenue over time", node_id="n1",
        judgment="ACCURATE", passage_ids=["p1"],
    )
    output = GraderOutput(
        claims=[claim],
        verdicts=[{
            "node_id": "n1", "status": "VERIFIED", "confidence": 0.9,
            "rubric_items_met": [0], "passage_ids": ["p1"],
        }],
        summary="Good.",
    )
    assert output.claims[0].judgment == "ACCURATE"
    assert Omission(node_id="n2", citations=["p2"]).node_id == "n2"


def test_ledger_skill_api_contracts_validate_examples():
    now = datetime.now(timezone.utc)
    event = LedgerEvent(
        id="e1", student_id="s1", node_id="n1", status="VERIFIED",
        confidence=0.9, evidence_turn_id="t1", source="teach_back",
        phase="TEACH_BACK", ts=now,
    )
    task_event = TaskAttemptEvent(
        id="e2", student_id="s1", session_id="sess", skill_id="skill",
        task_id="task", template_version="1", variant_seed=1,
        answer_key_sha256="hash", score=1, passed=True, evidence_turn_id="t1", ts=now,
    )
    task = TaskTemplate(
        task_id="task", skill_id="skill", title="Task", description="Brief",
        template_version="1", parameters={"amount": ParamSpec(type="money")},
    )
    assert event.kind == "concept"
    assert task_event.passed is True
    assert SkillDef(
        skill_id="skill", title="Skill", description="Description", task_ids=["task"]
    ).unlock_rule == "all_tasks_passed"
    assert task.task_id == "task"


def test_api_contracts_and_prompt_version():
    assert CreateSessionRequest().topic_id == "ind_as_115"
    assert TurnRequest(transcript="hello").transcript == "hello"
    assert PROMPT_VERSION == "1"
