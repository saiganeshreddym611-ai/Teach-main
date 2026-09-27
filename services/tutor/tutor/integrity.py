"""Integrity layer (Phase 2). Stub interface so the real speaker-verification
implementation (pyannote / SpeechBrain / vendor API) drops in without touching
the orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .config import settings


@dataclass(frozen=True)
class VerificationResult:
    match: bool
    score: float
    method: str


class SpeakerVerifier:
    async def enroll(self, student_id: str, audio: bytes) -> None: ...
    async def verify(self, student_id: str, audio: bytes) -> VerificationResult: ...


class StubVerifier(SpeakerVerifier):
    async def enroll(self, student_id: str, audio: bytes) -> None:
        return None

    async def verify(self, student_id: str, audio: bytes) -> VerificationResult:
        return VerificationResult(match=True, score=1.0, method="stub")


VERIFIERS: dict[str, type[SpeakerVerifier]] = {"stub": StubVerifier}


class UnknownVerifierError(ValueError):
    """SPEAKER_VERIFIER names no registered verifier. Message lists the valid names."""


@lru_cache(maxsize=1)
def get_verifier() -> SpeakerVerifier:
    """Instance for settings.speaker_verifier. Raises UnknownVerifierError for unknown names."""
    verifier_cls = VERIFIERS.get(settings.speaker_verifier)
    if verifier_cls is None:
        names = ", ".join(sorted(VERIFIERS))
        raise UnknownVerifierError(f"Unknown speaker verifier '{settings.speaker_verifier}'. Valid names: {names}.")
    return verifier_cls()


def describe_verifier() -> str:
    """The configured verifier name, e.g. "stub"."""
    return settings.speaker_verifier
