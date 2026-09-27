"""Session store. In-memory for the MVP; the interface is what Supabase/Postgres
will implement later (sessions + turns + ledger_events tables)."""
from __future__ import annotations

from typing import Protocol

from .models import LedgerEvent, Session


class SessionStore(Protocol):
    async def get(self, session_id: str) -> Session | None: ...
    async def save(self, session: Session) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def save(self, session: Session) -> None:
        self._sessions[session.id] = session


store = InMemorySessionStore()


# --------------------------------------------------------------------------- #
# Ledger store
# --------------------------------------------------------------------------- #
class LedgerStore(Protocol):
    def append(self, events: list[LedgerEvent]) -> None: ...
    def events_for(self, student_id: str) -> list[LedgerEvent]: ...   # append order
    def event(self, student_id: str, event_id: str) -> LedgerEvent | None: ...
    def delete_student(self, student_id: str) -> int: ...             # events removed


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._events: dict[str, list[LedgerEvent]] = {}

    def append(self, events: list[LedgerEvent]) -> None:
        for ev in events:
            self._events.setdefault(ev.student_id, []).append(ev)

    def events_for(self, student_id: str) -> list[LedgerEvent]:
        return list(self._events.get(student_id, []))

    def event(self, student_id: str, event_id: str) -> LedgerEvent | None:
        for ev in self._events.get(student_id, []):
            if ev.id == event_id:
                return ev
        return None

    def delete_student(self, student_id: str) -> int:
        removed = len(self._events.get(student_id, []))
        self._events.pop(student_id, None)
        return removed

    def clear(self) -> None:
        """Clear all events - for tests only."""
        self._events.clear()


ledger_store = InMemoryLedgerStore()