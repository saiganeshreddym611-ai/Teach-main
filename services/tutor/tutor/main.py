"""FastAPI app: session routes (one SSE) plus server-side TTS."""
from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from .config import settings
from .content import load_pack
from .contracts.api import ContentInfo, LedgerTrace, PassageResponse, StudentLedger, TracePassage, VerifyRequest, VerifyResponse
from .curriculum import load_curriculum
from .integrity import UnknownVerifierError, describe_verifier, get_verifier
from .ledger import export_ledger, mastery_view, student_events
from .store import ledger_store, store
from .llm import describe_grader, describe_tutor, get_grader, get_tutor
from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    Phase,
    Session,
    SessionView,
    TTSRequest,
    Turn,
    TurnRequest,
)
from .state_machine import TurnEvent, run_turn
from .tts import describe_tts, get_tts, prepare_tts, wav_bytes
from .review import current_release, review_counts, strict_problems
from .retrieval.corpus import load_corpus
from .retrieval.refs import cite_passage

@asynccontextmanager
async def lifespan(_: FastAPI):
    load_pack()
    # Off the event loop: fetch the Piper voice on a fresh clone, then warm it, so the API is up at
    # once and the kiosk uses the browser voice until Piper is ready.
    asyncio.get_running_loop().run_in_executor(None, prepare_tts)
    yield


app = FastAPI(title="Socratic Tutor", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/content", response_model=ContentInfo)
async def content() -> ContentInfo:
    pack = load_pack()
    return ContentInfo(
        manifest=pack.manifest,
        content_hash=pack.content_hash,
        review_counts=review_counts(pack),
        topic_id=pack.curriculum.tree.topic_id,
        standard=pack.curriculum.tree.standard,
    )


@app.get("/passages/{passage_id}", response_model=PassageResponse)
async def get_passage(passage_id: str) -> PassageResponse:
    corpus = load_corpus(load_pack())
    if corpus is None or passage_id not in corpus.by_id:
        raise HTTPException(404, "passage not found")
    passage = corpus.passage(passage_id)
    return PassageResponse(passage=passage, source=corpus.doc(passage.doc_id), citation=cite_passage(passage, corpus))


@app.get("/health")
async def health() -> dict:
    pack = load_pack()
    return {
        "ok": True,
        "mock_llm": settings.mock_llm,
        "grader": describe_grader(),
        "tutor": describe_tutor(),
        "tts": describe_tts(),
        "verifier": describe_verifier(),
        "content": {
            "pack_id": pack.pack_id,
            "version": pack.manifest.version,
            "content_hash": pack.content_hash,
            "review_counts": review_counts(pack),
            "release_signed_off": current_release(pack) is not None,
            "strict": settings.require_reviewed_content,
        },
    }


@app.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest) -> VerifyResponse:
    try:
        audio = base64.b64decode(req.audio_b64, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "audio_b64 is not valid base64")
    if not audio:
        raise HTTPException(422, "audio_b64 decodes to empty audio")
    try:
        result = await get_verifier().verify(req.student_id, audio)
    except UnknownVerifierError as exc:
        raise HTTPException(500, str(exc)) from exc
    finally:
        del audio
    return VerifyResponse(match=result.match, score=result.score, method=result.method)


@app.get("/tts/info")
async def tts_info() -> dict:
    return describe_tts()


@app.post("/tts")
async def tts(req: TTSRequest) -> Response:
    """Synthesise one sentence (the client sends sentences as the tutor streams)."""
    engine = get_tts()
    if engine is None:
        raise HTTPException(404, "server-side TTS is disabled (TTS_ENGINE=browser)")
    speed = req.speed or settings.tts_speed
    try:
        samples = await asyncio.to_thread(engine.synth, req.text, speed, req.voice)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return Response(
        content=wav_bytes(samples, engine.sample_rate),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store", "X-TTS-Engine": engine.name, "X-TTS-Voice": req.voice or engine.voice},
    )


@app.post("/session", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    pack = load_pack()
    topic_id = req.topic_id or pack.curriculum.tree.topic_id
    try:
        curriculum = load_curriculum(topic_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    if settings.require_reviewed_content:
        problems = strict_problems(pack)
        if problems:
            raise HTTPException(
                409,
                detail={"message": "Content is not approved for use.", "problems": problems},
            )
    session = Session(student_id=req.student_id, topic_id=topic_id)
    session.turns.append(Turn(role="tutor", text=curriculum.tree.opening_prompt, phase=Phase.DIAGNOSTIC))
    await store.save(session)
    return CreateSessionResponse(
        session_id=session.id, phase=session.phase, opening_prompt=curriculum.tree.opening_prompt
    )


@app.get("/session/{session_id}", response_model=SessionView)
async def get_session(session_id: str) -> SessionView:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    curriculum = load_curriculum(session.topic_id)
    return SessionView(
        session_id=session.id,
        student_id=session.student_id,
        topic_id=session.topic_id,
        phase=session.phase,
        target_node=session.target_node,
        student_level_summary=session.student_level_summary,
        study_mode=session.study_mode,
        mastery=mastery_view(session, curriculum),
        turns=session.turns,
        ledger=session.ledger,
    )


@app.get("/students/{student_id}/ledger", response_model=StudentLedger)
async def get_student_ledger(student_id: str) -> StudentLedger:
    pack = load_pack()
    curriculum = pack.curriculum
    corpus = load_corpus(pack)
    events = student_events(Session(student_id=student_id, topic_id=curriculum.tree.topic_id), ledger_store)
    return export_ledger(student_id, curriculum, events, corpus)


@app.get("/students/{student_id}/ledger/{event_id}/trace", response_model=LedgerTrace)
async def get_ledger_trace(student_id: str, event_id: str) -> LedgerTrace:
    pack = load_pack()
    corpus = load_corpus(pack)
    event = ledger_store.event(student_id, event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    session = await store.get(event.session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    student_turn = next((t.text for t in session.turns if t.id == event.evidence_turn_id), None)
    if student_turn is None:
        raise HTTPException(404, "evidence turn not found")
    passages: list[TracePassage] = []
    if corpus is not None:
        for pid in event.passage_ids:
            if pid in corpus.by_id:
                passage = corpus.by_id[pid]
                passages.append(TracePassage(citation=cite_passage(passage, corpus), text=passage.text))
    return LedgerTrace(event=event, student_turn=student_turn, passages=passages, grader_call_id=event.grader_call_id)


def _sse(event: TurnEvent) -> str:
    return f"event: {event.kind}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


@app.post("/session/{session_id}/turn")
async def turn(session_id: str, req: TurnRequest) -> StreamingResponse:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    curriculum = load_curriculum(session.topic_id)

    async def gen() -> AsyncIterator[str]:
        try:
            async for ev in run_turn(session, req.transcript, curriculum, get_grader(), get_tutor()):
                yield _sse(ev)
        except Exception as e:  # surface to the client instead of a dropped stream
            yield _sse(TurnEvent("error", {"message": f"{type(e).__name__}: {e}"}))
        finally:
            await store.save(session)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
