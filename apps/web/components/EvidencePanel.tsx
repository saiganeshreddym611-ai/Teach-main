"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { getPassage } from "@/lib/api";
import type { LedgerEvent, PassageResponse } from "@/lib/contracts";
import type { MasteryEntry } from "@/lib/api";

const STATUS_TEXT: Record<MasteryEntry["status"], string> = {
  VERIFIED: "mastered",
  PARTIAL: "partly shown",
  GAP: "gap found: the student said something wrong or missed it",
  NOT_MENTIONED: "not assessed yet",
};

function formatConfidence(value: number | null | undefined) {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

export default function EvidencePanel({
  entry,
  ledger,
  onClose,
  returnFocusRef,
}: {
  entry: MasteryEntry;
  ledger: LedgerEvent[];
  onClose: () => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
}) {
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const [passageCache, setPassageCache] = useState<Record<string, PassageResponse | null>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const latestByNode = useMemo(() => {
    const byNode: Record<string, LedgerEvent> = {};
    for (const event of ledger) {
      byNode[event.node_id] = event;
    }
    return byNode;
  }, [ledger]);

  const event = latestByNode[entry.node_id];
  const statusText = STATUS_TEXT[entry.status];

  useEffect(() => {
    headingRef.current?.focus();
  }, [entry.node_id]);

  useEffect(() => {
    const onKeyDown = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key === "Escape") {
        keyEvent.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (!event?.passage_ids?.length) return;
    const missing = event.passage_ids.filter((id) => passageCache[id] === undefined);
    if (!missing.length) return;
    let active = true;
    Promise.all(
      missing.map(async (id) => {
        try {
          return [id, await getPassage(id)] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    ).then((results) => {
      if (!active) return;
      setPassageCache((prev) => ({ ...prev, ...Object.fromEntries(results) }));
    });
    return () => {
      active = false;
    };
  }, [event, passageCache]);

  return (
    <section
      aria-label={`Evidence for ${entry.title}`}
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/60 p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-3 border-b border-zinc-800 pb-3">
        <div>
          <h3 ref={headingRef} tabIndex={-1} className="text-base font-medium text-zinc-100 outline-none">
            {entry.title}
          </h3>
          <p className="mt-1 text-xs text-zinc-400">
            Status: <span className="text-zinc-200">{statusText}</span>
            {entry.confidence != null && (
              <span className="ml-2 text-zinc-300">Confidence: {formatConfidence(entry.confidence)}</span>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            onClose();
            requestAnimationFrame(() => returnFocusRef.current?.focus());
          }}
          className="rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-200 hover:border-zinc-500"
        >
          Back
        </button>
      </div>

      <div className="flex-1 min-h-0 space-y-4 overflow-y-auto pr-1">
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Student quote</p>
          {event?.evidence ? (
            <blockquote className="mt-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-sm leading-6 text-zinc-200">
              “{event.evidence}”
            </blockquote>
          ) : (
            <p className="mt-2 text-sm text-zinc-400">
              {entry.status === "NOT_MENTIONED" ? "Not assessed yet." : "Assessed in an earlier session."}
            </p>
          )}
        </div>

        {event?.passage_ids?.length ? (
          <div className="space-y-3">
            <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">Source passages</p>
            {event.passage_ids.map((id) => {
              const result = passageCache[id];
              const text = result?.passage.text ?? "";
              const label = result?.citation.label ?? id;
              const isExpanded = Boolean(expanded[id]);
              const showToggle = text.length > 220;
              return (
                <div key={id} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                  {result ? (
                    <>
                      <p className="text-sm font-semibold text-zinc-100">{label}</p>
                      <div
                        className="mt-2 whitespace-pre-wrap text-sm leading-6 text-zinc-300"
                        style={{
                          maxHeight: isExpanded ? "none" : "6.5rem",
                          overflow: isExpanded ? "visible" : "hidden",
                        }}
                      >
                        {text}
                      </div>
                      {showToggle && (
                        <button
                          type="button"
                          onClick={() => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))}
                          className="mt-2 text-xs font-medium text-sky-300 hover:text-sky-200"
                        >
                          {isExpanded ? "Show less" : "Show more"}
                        </button>
                      )}
                    </>
                  ) : result === null ? (
                    <p className="text-sm text-zinc-300">Source text unavailable ({id})</p>
                  ) : (
                    <p className="text-sm text-zinc-300">Loading source…</p>
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}
