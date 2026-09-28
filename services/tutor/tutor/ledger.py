"""Append-only mastery ledger and its projection.

Events are never edited. The current mastery of a node is the *latest* event
for that node; nodes with no event are NOT_MENTIONED. Every event points at
the student turn that produced it, which is the audit trail the pitch needs.
"""
from __future__ import annotations

from datetime import datetime

from .contracts.api import StudentLedger, LedgerNodeExport
from .curriculum import Curriculum
from .contracts.grading import NodeVerdictV2
from .models import LedgerEvent, LedgerSource, MasteryEntry, NodeStatus, Phase, Session
from .retrieval.corpus import Corpus
from .store import LedgerStore, ledger_store


SOURCE_BY_PHASE = {
    Phase.DIAGNOSTIC: "diagnostic",
    Phase.TEACH_BACK: "teach_back",
}

EXPORT_STATUS = {
    NodeStatus.VERIFIED: "MASTERED",
    NodeStatus.GAP: "GAP_IDENTIFIED",
    NodeStatus.PARTIAL: "PARTIAL",
}  # no event: "NOT_ASSESSED"


def append_verdicts(
    session: Session,
    verdicts: list[NodeVerdictV2],
    evidence_turn_id: str,
    phase: Phase,
    *,
    focus_node_ids: set[str] | None = None,
    grader_call_id: str | None = None,
    content_version: str | None = None,
    source: LedgerSource | None = None,
    store: LedgerStore | None = None,
) -> list[LedgerEvent]:
    """Write one event per verdict that carries evidence (NOT_MENTIONED is skipped).

    A node already VERIFIED is not downgraded by an incidental later verdict;
    only a verdict on a *focused* node (the teach-back target) may overwrite
    it. That keeps the ledger monotone for the demo; a real product would model
    REVOKED explicitly.

    Downgrade rules (extended for v2):
    - a downgrade is explicit, from a focused verdict only (teach-back today;
      later probe, review, task remediation);
    - it is evidence-linked through evidence_turn_id, grader_call_id and
      passage_ids;
    - it is never incidental.
    """
    focus = focus_node_ids or set()
    current = project_status(session, store)
    written: list[LedgerEvent] = []
    target_store = store or ledger_store
    for v in verdicts:
        if v.status == NodeStatus.NOT_MENTIONED:
            continue
        if current.get(v.node_id) == NodeStatus.VERIFIED and v.node_id not in focus:
            continue
        ev = LedgerEvent(
            student_id=session.student_id,
            node_id=v.node_id,
            status=v.status,
            confidence=v.confidence,
            evidence_turn_id=evidence_turn_id,
            phase=phase,
            session_id=session.id,
            evidence=v.evidence,
            passage_ids=list(v.passage_ids),
            grader_call_id=grader_call_id,
            content_version=content_version,
            source=source if source is not None else SOURCE_BY_PHASE.get(phase),
            rubric_items_met=v.rubric_items_met,
            misconception_ids=v.misconception_ids,
        )
        session.ledger.append(ev)
        target_store.append([ev])
        written.append(ev)
    return written


def student_events(session: Session, store: LedgerStore | None = None) -> list[LedgerEvent]:
    """All events for this student from the ledger store (append order)."""
    target_store = store or ledger_store
    return target_store.events_for(session.student_id)


def project_status(session: Session, store: LedgerStore | None = None) -> dict[str, NodeStatus]:
    """Current status for each node from the student's full event history."""
    status: dict[str, NodeStatus] = {}
    for ev in student_events(session, store):
        status[ev.node_id] = ev.status
    return status


def project_confidence(session: Session, store: LedgerStore | None = None) -> dict[str, float]:
    """Current confidence for each node from the student's full event history."""
    conf: dict[str, float] = {}
    for ev in student_events(session, store):
        conf[ev.node_id] = ev.confidence
    return conf


def mastery_view(session: Session, curriculum: Curriculum, store: LedgerStore | None = None) -> list[MasteryEntry]:
    status = project_status(session, store)
    conf = project_confidence(session, store)
    return [
        MasteryEntry(
            node_id=n.id,
            title=n.title,
            level=n.level,
            parent=n.parent,
            status=status.get(n.id, NodeStatus.NOT_MENTIONED),
            confidence=conf.get(n.id),
        )
        for n in curriculum.tree.nodes
    ]


def export_ledger(
    student_id: str,
    curriculum: Curriculum,
    events: list[LedgerEvent],
    corpus: Corpus | None,
) -> StudentLedger:
    """Build the exportable student ledger for the API.

    - Every node of the curriculum gets one entry, in tree order.
    - Each entry comes from the latest event for that node.
    - Citation labels come from cite_passage. Skip passage IDs the corpus
      does not hold.
    """
    from .retrieval.refs import cite_passage

    # Build latest event per node
    latest_by_node: dict[str, LedgerEvent] = {}
    for ev in events:
        latest_by_node[ev.node_id] = ev

    nodes: list[LedgerNodeExport] = []
    for n in curriculum.tree.nodes:
        ev = latest_by_node.get(n.id)
        status = "NOT_ASSESSED"
        confidence_score: float | None = None
        last_verified: datetime | None = None
        evidence_turn_id: str | None = None
        citations: list[str] = []
        if ev is not None:
            status = EXPORT_STATUS.get(ev.status, "NOT_ASSESSED")
            confidence_score = ev.confidence
            last_verified = ev.ts
            evidence_turn_id = ev.evidence_turn_id
            if corpus is not None:
                for pid in ev.passage_ids:
                    if pid in corpus.by_id:
                        citations.append(cite_passage(corpus.by_id[pid], corpus).label)
        nodes.append(
            LedgerNodeExport(
                concept_id=n.id,
                title=n.title,
                status=status,
                confidence_score=confidence_score,
                last_verified=last_verified,
                evidence_turn_id=evidence_turn_id,
                citations=citations,
            )
        )

    return StudentLedger(
        student_id=student_id,
        topic_id=curriculum.tree.topic_id,
        subject=curriculum.tree.subject,
        standard=curriculum.tree.standard,
        nodes=nodes,
        events=events,
    )
