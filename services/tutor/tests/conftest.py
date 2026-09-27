import pytest

from tutor.curriculum import load_curriculum
from tutor.contracts.grading import GraderOutput, NodeVerdictV2
from tutor.grader import MockGrader
from tutor.grader_audit import grade_memo
from tutor.models import NodeStatus, Session
from tutor.prompts import TEACH_BACK_SENTINEL
from tutor.store import ledger_store
from tutor.tutor_voice import MockTutor


@pytest.fixture
def curriculum():
    return load_curriculum("ind_as_115")


@pytest.fixture
def session():
    return Session(student_id="s1", topic_id="ind_as_115")


@pytest.fixture(autouse=True)
def isolate_grader_audit(tmp_path):
    """Point capture dir to tmp_path and clear memo before each test."""
    from tutor.config import settings
    original_capture_dir = settings.grader_capture_dir
    settings.grader_capture_dir = tmp_path
    grade_memo.clear()
    ledger_store.clear()
    yield
    settings.grader_capture_dir = original_capture_dir
    grade_memo.clear()
    ledger_store.clear()


class ScriptedGrader:
    """Returns the next scripted GraderOutput on each call and records calls."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def grade(self, curriculum, transcript, *, focus_node_id, prior_context, session_id, student_id: str = "", call_id: str | None = None):
        self.calls.append({"transcript": transcript, "focus": focus_node_id, "prior": prior_context, "student_id": student_id, "call_id": call_id})
        return self.results.pop(0)


class ScriptedTutor:
    """Yields scripted text (optionally with the sentinel) and records directives."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.directives = []

    async def stream(self, curriculum, session, directive):
        self.directives.append(directive)
        text = self.scripts.pop(0)
        for i in range(0, len(text), 7):
            yield text[i : i + 7]


def verdict(node_id, status, conf=0.9, evidence="said it"):
    return NodeVerdictV2(node_id=node_id, status=NodeStatus(status), confidence=conf, evidence=evidence)


def result(*verdicts, summary="ok"):
    return GraderOutput(verdicts=list(verdicts), summary=summary)


SENT = TEACH_BACK_SENTINEL
