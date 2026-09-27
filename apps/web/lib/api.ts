// Thin client for the tutor service. The /turn endpoint is SSE over POST, so we
// parse the stream by hand instead of using EventSource (which is GET-only).

import type { ContentInfo, DoneEvent, GradeEvent, MasteryEntry, NodeStatus, Passage, PassageResponse, Phase, SessionView, SkillDef, Turn, Verdict } from "./contracts";
import { dispatch } from "./sse";

export const API_BASE = process.env.NEXT_PUBLIC_TUTOR_API ?? "http://localhost:8000";

export type { ContentInfo, DoneEvent, GradeEvent, MasteryEntry, NodeStatus, Passage, PassageResponse, Phase, SessionView, SkillDef, Turn, Verdict };

export async function createSession(studentId = "demo_student", topicId?: string) {
  const r = await fetch(`${API_BASE}/session`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ student_id: studentId, ...(topicId ? { topic_id: topicId } : {}) }),
  });
  if (!r.ok) throw new Error(`createSession ${r.status}: ${await r.text()}`);
  return (await r.json()) as { session_id: string; phase: Phase; opening_prompt: string };
}

export async function getSession(sessionId: string): Promise<SessionView> {
  const r = await fetch(`${API_BASE}/session/${sessionId}`);
  if (!r.ok) throw new Error(`getSession ${r.status}`);
  return (await r.json()) as SessionView;
}

export async function getContent(): Promise<ContentInfo> {
  const r = await fetch(`${API_BASE}/content`);
  if (!r.ok) throw new Error(`getContent ${r.status}`);
  return (await r.json()) as ContentInfo;
}

export interface TurnHandlers {
  onGrade?: (g: GradeEvent) => void;
  onText?: (delta: string) => void;
  onDone?: (d: DoneEvent) => void;
  onError?: (message: string) => void;
  onScope?: (payload: unknown) => void;
  onTask?: (payload: unknown) => void;
  onTaskResult?: (payload: unknown) => void;
  onSkill?: (payload: unknown) => void;
  onPractice?: (payload: unknown) => void;
}

export async function streamTurn(sessionId: string, transcript: string, h: TurnHandlers): Promise<void> {
  const r = await fetch(`${API_BASE}/session/${sessionId}/turn`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify({ transcript }),
  });
  if (!r.ok || !r.body) {
    h.onError?.(`turn ${r.status}: ${await r.text()}`);
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      dispatch(block, h);
    }
  }
  if (buf.trim()) dispatch(buf, h);
}

export async function getPassage(id: string): Promise<PassageResponse> {
  const r = await fetch(`${API_BASE}/passages/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(`getPassage ${r.status}: ${await r.text()}`);
  return (await r.json()) as PassageResponse;
}

export async function getStudentLedger(studentId: string): Promise<unknown> {
  const r = await fetch(`${API_BASE}/students/${encodeURIComponent(studentId)}/ledger`);
  if (!r.ok) throw new Error(`getStudentLedger ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function getSkills(studentId: string): Promise<SkillDef[]> {
  const r = await fetch(`${API_BASE}/students/${encodeURIComponent(studentId)}/skills`);
  if (!r.ok) throw new Error(`getSkills ${r.status}: ${await r.text()}`);
  return (await r.json()) as SkillDef[];
}
