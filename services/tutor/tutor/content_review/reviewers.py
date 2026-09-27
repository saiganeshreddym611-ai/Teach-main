"""Reviewers answer evidence packets. Only Claude reviews content (D6): code refuses Ollama models."""
from __future__ import annotations

from typing import Protocol

from anthropic import Anthropic

from ..config import settings
from ..contracts.content import ReviewerInfo
from .evidence import render_packet
from .models import Answer, Answers, Packet

REVIEW_INSTRUCTIONS = """You check syllabus content against official sources. Judge each claim from the passages in the packet only, never from memory.

- supported: a passage states the claim or directly implies it. Quote the words that support it.
- contradicted: a passage states the opposite or a different rule. Quote the words that contradict it.
- not_found: no passage settles the claim, or the claim adds a condition, exception, number or example detail that no passage states. A claim that is partly supported but adds something unstated is not_found.

`passage_id` is the ID of the one passage you quote. `quote` is copied word for word from that passage, at least 3 words; leave both empty for not_found.

Then answer the coverage question in `coverage_gaps`: one short entry per requirement the [linked] passages state for this concept that no rubric claim covers. Leave it empty when the rubric covers them all."""

OLLAMA_HINTS = ("ollama", "gemma", "llama", "qwen", "nemotron", "mistral", "deepseek", "phi")


class ReviewerRefused(RuntimeError):
    """The configured reviewer may not review content (D6)."""


class Reviewer(Protocol):
    # None marks a reviewer whose runs are never recorded (the mock).
    info: ReviewerInfo | None

    def review(self, packet: Packet) -> Answers | None:
        """Answers now, or None when the answers come later (session mode)."""
        ...


class SessionReviewer:
    """Claude in the Claude Code session answers the written packets; `--ingest` applies them."""

    info = ReviewerInfo(mode="session", model="claude-code-session")

    def review(self, packet: Packet) -> Answers | None:
        return None


class ClaudeApiReviewer:
    def __init__(self, model: str, client: Anthropic | None = None) -> None:
        self.info = ReviewerInfo(mode="claude-api", model=model)
        self.client = client or Anthropic()

    def review(self, packet: Packet) -> Answers:
        response = self.client.messages.parse(
            model=self.info.model,
            max_tokens=8000,
            temperature=0,
            system=REVIEW_INSTRUCTIONS,
            messages=[{"role": "user", "content": render_packet(packet)}],
            output_format=Answers,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"reviewer refused {packet.item_id}")
        parsed: Answers | None = response.parsed_output
        if parsed is None:
            raise RuntimeError(f"reviewer returned no parsed output for {packet.item_id} (stop_reason={response.stop_reason})")
        return parsed.model_copy(update={"item_id": packet.item_id})


class ScriptedReviewer:
    """Fixed answers per item, for tests."""

    def __init__(self, answers: dict[str, Answers], info: ReviewerInfo | None = None) -> None:
        self.answers = answers
        self.info = info or ReviewerInfo(mode="session", model="scripted")

    def review(self, packet: Packet) -> Answers:
        return self.answers[packet.item_id]


class MockReviewer:
    """MOCK_LLM=1: finds nothing, so every item would need an expert. Its runs are never recorded."""

    info = None

    def review(self, packet: Packet) -> Answers:
        return Answers(item_id=packet.item_id, answers=[Answer(claim_id=c.claim_id, verdict="not_found") for c in packet.claims])


def _refuse_ollama(value: str) -> None:
    lowered = value.lower()
    if ":" in lowered or any(hint in lowered for hint in OLLAMA_HINTS):
        raise ReviewerRefused(f"{value!r} looks like an Ollama model; only Claude reviews content (D6)")


def get_reviewer(name: str | None = None, model: str | None = None, client: Anthropic | None = None) -> Reviewer:
    name = (name or settings.reviewer).lower()
    model = model or settings.reviewer_model
    _refuse_ollama(name)
    _refuse_ollama(model)
    if name not in {"session", "claude-api"}:
        raise ReviewerRefused(f"unknown reviewer {name!r}: use session or claude-api")
    if name == "claude-api" and not model.startswith("claude-"):
        raise ReviewerRefused(f"REVIEWER_MODEL {model!r} is not a Claude model (D6)")
    if settings.mock_llm:
        return MockReviewer()
    if name == "session":
        return SessionReviewer()
    return ClaudeApiReviewer(model, client)
