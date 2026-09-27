"""Code has the last word on a review: quote check, citation rules and the status decision."""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts.content import ClaimVerdict, ReviewClaim, ReviewStatus
from .models import Answers, Claim, Packet, PacketPassage

MIN_QUOTE_WORDS = 3


class AnswersError(ValueError):
    """Answers that do not fit their packet."""


def _norm(text: str) -> str:
    return " ".join(text.split())


def verify_quote(quote: str, passage_text: str) -> bool:
    """The quote, whitespace-normalised, appears word for word in the passage and has at least
    MIN_QUOTE_WORDS words (a two-word quote proves nothing)."""
    q = _norm(quote)
    return len(q.split()) >= MIN_QUOTE_WORDS and q in _norm(passage_text)


@dataclass(frozen=True)
class CheckedClaim:
    claim: Claim
    verdict: ClaimVerdict  # after the quote check
    passage: PacketPassage | None
    quote: str
    quote_verified: bool
    problem: str | None  # None when the claim passes

    def review_claim(self) -> ReviewClaim:
        return ReviewClaim(
            claim=self.claim.text,
            verdict=self.verdict,
            passage_id=self.passage.passage_id if self.passage else None,
            quote=self.quote,
            quote_verified=self.quote_verified,
        )


def validate_answers(packet: Packet, answers: Answers) -> None:
    if answers.item_id != packet.item_id:
        raise AnswersError(f"answers are for {answers.item_id}, packet is {packet.item_id}")
    known = {c.claim_id for c in packet.claims}
    ids = [a.claim_id for a in answers.answers]
    unknown = sorted(set(ids) - known)
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if unknown or duplicates:
        raise AnswersError(f"{packet.item_id}: unknown claim IDs {unknown}, duplicated {duplicates}")


def check_answers(packet: Packet, answers: Answers) -> list[CheckedClaim]:
    """Apply the rules to each claim. A failed quote check turns the verdict into not_found."""
    by_id = {a.claim_id: a for a in answers.answers}
    passages = {p.passage_id: p for p in packet.passages}
    out: list[CheckedClaim] = []
    for claim in packet.claims:
        answer = by_id.get(claim.claim_id)
        if answer is None:
            out.append(CheckedClaim(claim, "not_found", None, "", False, "no answer"))
            continue
        verdict: ClaimVerdict = answer.verdict
        passage = passages.get(answer.passage_id or "")
        verified = False
        problem: str | None = None
        if verdict != "not_found":
            if passage is None:
                verdict, problem = "not_found", f"cites {answer.passage_id or 'no passage'}, which is not in the evidence packet"
            elif not verify_quote(answer.quote, passage.text):
                verdict, problem = "not_found", f"quote not found word for word in {passage.label}"
            else:
                verified = True
        if problem is None and verdict != claim.expect:
            if verdict == "not_found":
                problem = "not found in the sources"
            elif verdict == "contradicted":
                problem = f"contradicted by {passage.label}"
            else:
                problem = f"supported by {passage.label}, but a misconception must be contradicted"
        if problem is None and passage is not None and passage.superseded_by:
            problem = f"relies on {passage.label}, superseded by {', '.join(passage.superseded_by)}"
        if problem is None and claim.kind == "rubric" and passage is not None and not passage.linked:
            # The grader may cite only the node's linked passages (T30), so a rubric item must
            # be supported by one of them.
            problem = f"supported by {passage.label}, which is outside the node's source_refs"
        out.append(CheckedClaim(claim, verdict, passage if verdict != "not_found" else None,
                                answer.quote, verified, problem))
    return out


def _short(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def decide(checked: list[CheckedClaim], gaps: list[str], unresolved_refs: list[str] = ()) -> tuple[ReviewStatus, list[str]]:
    """claude_reviewed only when every claim passes, every ref resolves and there are no coverage
    gaps; otherwise needs_expert with one reason per finding."""
    reasons = [f"source ref {ref} does not resolve" for ref in unresolved_refs]
    reasons += [
        f'{c.claim.claim_id} ({c.claim.kind}) "{_short(c.claim.text)}": {c.problem}'
        for c in checked
        if c.problem
    ]
    reasons += [f"coverage gap: {gap.strip()}" for gap in gaps if gap.strip()]
    return ("needs_expert" if reasons else "claude_reviewed"), reasons
