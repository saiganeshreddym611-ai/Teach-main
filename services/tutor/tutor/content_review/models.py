"""Data shapes for the grounded content review (T23): claims, evidence packets, answers, runs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..contracts.content import ClaimVerdict, ReviewClaim, ReviewerInfo, ReviewStatus

ClaimKind = Literal["rubric", "explanation", "example", "misconception"]
Expectation = Literal["supported", "contradicted"]


class Claim(BaseModel):
    claim_id: str
    item_id: str
    kind: ClaimKind
    text: str
    # A misconception is a wrong belief, so the sources must contradict it.
    expect: Expectation


class PacketPassage(BaseModel):
    passage_id: str
    label: str
    text: str
    # True for passages reached through the node's own source_refs; False for search hits.
    linked: bool
    superseded_by: list[str] = []


class Packet(BaseModel):
    run_id: str
    item_id: str
    title: str
    content_sha256: str
    source_refs: list[str]
    unresolved_refs: list[str] = []
    claims: list[Claim]
    passages: list[PacketPassage]
    coverage_question: str


class Answer(BaseModel):
    claim_id: str
    verdict: ClaimVerdict
    passage_id: str | None = None
    quote: str = ""


class Answers(BaseModel):
    item_id: str
    answers: list[Answer]
    coverage_gaps: list[str] = []


class ItemResult(BaseModel):
    item_id: str
    status: ReviewStatus
    reasons: list[str]
    claims: list[ReviewClaim]


class SelfTestScore(BaseModel):
    planted: int
    caught: int
    clean: int
    clean_passed: int
    missed: list[str] = []
    false_alarms: list[str] = []

    @property
    def catch_rate(self) -> float:
        return self.caught / self.planted if self.planted else 1.0


class ReviewRun(BaseModel):
    run_id: str
    pack_id: str
    packs_dir: str
    # None for the mock reviewer, whose runs are never recorded.
    reviewer: ReviewerInfo | None
    state: Literal["pending", "done"] = "pending"
    items: list[str]
    results: list[ItemResult] = []
    # Self-test only: item ID -> planted error type, or None for a clean node.
    self_test: dict[str, str | None] | None = None
    score: SelfTestScore | None = None
    report_path: str | None = None
    notes: list[str] = Field(default_factory=list)
