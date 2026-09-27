import type { DoneEvent, GradeEvent } from "./contracts";

export type SseMsg = {
  kind: string;
  data: unknown;
};

export type SseHandlers = {
  onGrade?: (payload: GradeEvent) => void;
  onText?: (delta: string) => void;
  onDone?: (payload: DoneEvent) => void;
  onError?: (message: string) => void;
  onScope?: (payload: unknown) => void;
  onTask?: (payload: unknown) => void;
  onTaskResult?: (payload: unknown) => void;
  onSkill?: (payload: unknown) => void;
  onPractice?: (payload: unknown) => void;
};

export function parseSseBlock(block: string): SseMsg | null {
  if (!block || !block.trim()) return null;

  let kind = "";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (!line.trim()) continue;
    if (line.startsWith("event: ")) {
      kind = line.slice("event: ".length).trim();
      continue;
    }
    if (line.startsWith("data: ")) {
      dataLines.push(line.slice("data: ".length));
    }
  }

  if (!kind) return null;

  const payload = dataLines.length ? dataLines.join("\n") : "";
  let data: unknown = {};

  if (payload) {
    try {
      data = JSON.parse(payload);
    } catch {
      data = payload;
    }
  }

  return { kind, data };
}

export function dispatch(block: string, handlers: SseHandlers = {}): void {
  const parsed = parseSseBlock(block);
  if (!parsed) return;

  const { kind, data } = parsed;

  switch (kind) {
    case "grade": {
      const grade = data as Partial<GradeEvent> | null;
      handlers.onGrade?.({
        verdicts: (grade?.verdicts ?? []) as GradeEvent["verdicts"],
        summary: String(grade?.summary ?? ""),
        ...(grade?.claims ? { claims: grade.claims } : {}),
        ...(grade?.omissions ? { omissions: grade.omissions } : {}),
      });
      break;
    }
    case "text": {
      const text = data as { delta?: string } | string | null;
      handlers.onText?.(typeof text === "string" ? text : text?.delta ?? "");
      break;
    }
    case "done": {
      const done = data as Partial<DoneEvent> | null;
      handlers.onDone?.({
        phase: done?.phase ?? "DIAGNOSTIC",
        target_node: done?.target_node ?? null,
        tutor_turn_id: done?.tutor_turn_id ?? "",
        student_turn_id: done?.student_turn_id ?? "",
        ledger_delta: (done?.ledger_delta ?? []) as DoneEvent["ledger_delta"],
        ...(done?.citations ? { citations: done.citations } : {}),
        ...(done?.grounding ? { grounding: done.grounding } : {}),
      });
      break;
    }
    case "error": {
      const error = data as { message?: string } | string | null;
      handlers.onError?.(typeof error === "string" ? error : error?.message ?? "");
      break;
    }
    case "scope":
      handlers.onScope?.(data);
      break;
    case "task":
      handlers.onTask?.(data);
      break;
    case "task_result":
      handlers.onTaskResult?.(data);
      break;
    case "skill":
      handlers.onSkill?.(data);
      break;
    case "practice":
      handlers.onPractice?.(data);
      break;
    default:
      break;
  }
}
