from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from tutor.contracts import (
    Claim,
    ClaimJudgment,
    ContentInfo,
    CorpusManifest,
    Citation,
    DiscrepancyCheck,
    GraderOutput,
    JudgementCheck,
    LedgerEvent,
    NodeVerdictV2,
    NumericCheck,
    Omission,
    PackManifest,
    ParamSpec,
    Passage,
    PassageResponse,
    PlantedDiscrepancy,
    ReleaseSignoff,
    ReviewClaim,
    ReviewMeta,
    ReviewerInfo,
    RubricItem,
    RubricItemResult,
    ScoredPassage,
    SkillDef,
    SourceDoc,
    TaskAttemptEvent,
    TaskDocument,
    TaskTemplate,
    TaskVariant,
    VerifyRequest,
    VerifyResponse,
)
from tutor.models import LedgerSource, NodeStatus


SHA = "a" * 64
NOW = datetime.now(timezone.utc)

SOURCE = {
    "doc_id": "d1",
    "doc_code": "IndAS115",
    "title": "Ind AS 115",
    "doc_type": "standard",
    "authority_rank": 1,
    "path": "sources/raw/standard.txt",
}
PASSAGE = {
    "passage_id": "IndAS115.para.76",
    "doc_id": "d1",
    "doc_type": "standard",
    "locator": "para.76",
    "text": "Text",
    "sha256": SHA,
}
RUBRIC = {
    "id": "r1",
    "text": "Recognises revenue over time",
    "node_id": "n1",
    "check": {"type": "judgement"},
}


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ReviewerInfo, {"mode": "session"}),
        (ReviewClaim, {"claim": "claim", "verdict": "supported"}),
        (ReviewMeta, {"content_sha256": SHA}),
        (ReleaseSignoff, {
            "pack_id": "pack", "version": "1.0.0", "content_hash": SHA,
            "signed_off_by": "owner", "signed_off_at": NOW,
        }),
        (SourceDoc, SOURCE),
        (Passage, PASSAGE),
        (Citation, {"passage_id": "p1", "label": "para 76", "doc_id": "d1"}),
        (ScoredPassage, {"passage": PASSAGE, "score": 1.0, "confidence": 1.0}),
        (PackManifest, {
            "pack_id": "pack", "exam": "CA Final", "paper": "FR",
            "attempt": "2027-05", "version": "0.1.0", "topics": ["ind_as_115"],
        }),
        (CorpusManifest, {"built_from": {"d1": SHA}, "chunk_count": 1, "corpus_sha256": SHA}),
        (Claim, {
            "claim_id": "c1", "quote": "over time", "judgment": ClaimJudgment.ACCURATE,
        }),
        (NumericCheck, {"type": "numeric", "field": "revenue"}),
        (DiscrepancyCheck, {"type": "discrepancy", "discrepancy_id": "d1"}),
        (JudgementCheck, {"type": "judgement"}),
        (RubricItem, RUBRIC),
        (PlantedDiscrepancy, {
            "id": "d1", "row_id": "row1", "issue_type": "wrong_period", "node_id": "n1",
        }),
        (TaskDocument, {"doc_id": "doc1", "title": "Ledger", "columns": ["row_id"], "rows": [{"row_id": "r1"}]}),
        (TaskTemplate, {
            "task_id": "task1", "skill_id": "skill1", "title": "Task",
            "kind": "calculation", "node_ids": ["n1"], "narrative_template": "Narrative",
            "calculator": "revenue", "answer_fields": ["revenue"], "rubric": [RUBRIC],
            "pass_threshold": 0.8, "template_version": "1",
        }),
        (TaskVariant, {
            "task_id": "task1", "seed": 1, "params": {}, "narrative": "Narrative",
            "answer_key": {"revenue": "100.00"}, "answer_key_sha256": SHA,
        }),
        (SkillDef, {"skill_id": "skill1", "title": "Revenue", "task_ids": ["task1"]}),
        (RubricItemResult, {"rubric_id": "r1", "score": 1.0}),
        (TaskAttemptEvent, {
            "student_id": "s1", "session_id": "session1", "skill_id": "skill1",
            "task_id": "task1", "template_version": "1", "variant_seed": 1,
            "answer_key_sha256": SHA, "score": 1.0, "passed": True,
            "evidence_turn_id": "turn1",
        }),
        (ContentInfo, {
            "manifest": {
                "pack_id": "pack", "exam": "CA Final", "paper": "FR",
                "attempt": "2027-05", "version": "0.1.0", "topics": ["ind_as_115"],
            },
            "content_hash": SHA,
        }),
        (PassageResponse, {
            "passage": PASSAGE, "source": SOURCE,
            "citation": {"passage_id": "p1", "label": "para 76", "doc_id": "d1"},
        }),
        (VerifyRequest, {"student_id": "student_1", "audio_b64": "YQ=="}),
        (VerifyResponse, {"match": True, "score": 1.0, "method": "stub"}),
        (ParamSpec, {"type": "money", "min": "100000.00", "max": "900000.00", "step": "1000.00"}),
        (NodeVerdictV2, {
            "node_id": "n1", "status": "PARTIAL", "confidence": 0.8,
            "rubric_items_met": [0], "passage_ids": ["p1"],
        }),
        (Omission, {"node_id": "n1", "citations": [{"passage_id": "p1", "label": "para 76", "doc_id": "d1"}]}),
        (GraderOutput, {"verdicts": [], "summary": "Summary"}),
        (LedgerEvent, {
            "student_id": "s1", "node_id": "n1", "status": NodeStatus.VERIFIED,
            "confidence": 1.0, "evidence_turn_id": "turn1", "phase": "TEACH_BACK",
        }),
    ],
)
def test_example_validates(model: type[Any], payload: dict[str, Any]):
    obj = model.model_validate(payload)
    assert model.model_validate(obj.model_dump(mode="json")) == obj


def test_bad_doc_type_rejected():
    with pytest.raises(ValidationError):
        SourceDoc.model_validate({**SOURCE, "doc_type": "coaching_notes"})


def test_bad_sha_rejected():
    with pytest.raises(ValidationError):
        Passage.model_validate({**PASSAGE, "sha256": "not-a-sha256"})


def test_rubric_check_discriminator():
    assert RubricItem.model_validate(RUBRIC).check.type == "judgement"
    with pytest.raises(ValidationError):
        RubricItem.model_validate({**RUBRIC, "check": {"type": "unknown"}})


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        ScoredPassage.model_validate({"passage": PASSAGE, "score": 1.0, "confidence": 1.1})
    with pytest.raises(ValidationError):
        NodeVerdictV2.model_validate({"node_id": "n1", "status": "GAP", "confidence": 1.5})
    with pytest.raises(ValidationError):
        VerifyResponse.model_validate({"match": True, "score": -0.1, "method": "stub"})


def test_old_ledger_event_still_valid():
    event = LedgerEvent(
        student_id="s1",
        node_id="n1",
        status=NodeStatus.VERIFIED,
        confidence=1.0,
        evidence_turn_id="turn1",
        phase="TEACH_BACK",
    )
    assert event.source is None
    assert event.kind == "concept"
    assert event.passage_ids == []
    assert LedgerSource.__args__


def test_contracts_exports():
    import tutor.contracts as contracts

    expected = {
        "Claim", "ClaimJudgment", "ClaimVerdict", "ContentInfo", "CorpusManifest",
        "Citation", "DiscrepancyCheck", "DocType", "GraderOutput", "JudgementCheck",
        "LedgerEvent", "LedgerSource", "NodeVerdictV2", "NumericCheck", "Omission",
        "PackManifest", "ParamSpec", "ParamType", "Passage", "PassageResponse",
        "PlantedDiscrepancy", "ReleaseSignoff", "ReviewClaim", "ReviewMeta",
        "ReviewStatus", "ReviewerInfo", "RubricCheck", "RubricItem", "RubricItemResult",
        "ScoredPassage", "Sha256", "SkillDef", "SourceDoc", "TaskAttemptEvent",
        "TaskDocument", "TaskTemplate", "TaskVariant", "USABLE_REVIEW_STATUSES",
        "VerifyRequest", "VerifyResponse",
    }
    assert set(contracts.__all__) == expected
