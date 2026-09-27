"use client";

import { useMemo, useRef, useState } from "react";
import EvidencePanel from "@/components/EvidencePanel";
import type { MasteryEntry, NodeStatus } from "@/lib/api";
import type { LedgerEvent } from "@/lib/contracts";

const STATUS_STYLE: Record<NodeStatus, string> = {
  VERIFIED: "bg-emerald-500/20 text-emerald-200 border-emerald-500/40",
  PARTIAL: "bg-amber-500/15 text-amber-200 border-amber-500/40",
  GAP: "bg-rose-500/15 text-rose-200 border-rose-500/40",
  NOT_MENTIONED: "bg-zinc-800/60 text-zinc-500 border-zinc-700/60",
};

const STATUS_DOT: Record<NodeStatus, string> = {
  VERIFIED: "bg-emerald-400",
  PARTIAL: "bg-amber-400",
  GAP: "bg-rose-400",
  NOT_MENTIONED: "bg-zinc-600",
};

function shortTitle(title: string) {
  return title.split("—").pop()!.trim();
}

function subtreeIdsOf(nodeId: string, mastery: MasteryEntry[]): Set<string> {
  const ids = new Set<string>([nodeId]);
  const walk = (id: string) => {
    for (const child of mastery.filter((m) => m.parent === id)) {
      ids.add(child.node_id);
      walk(child.node_id);
    }
  };
  walk(nodeId);
  return ids;
}

export default function MasteryGrid({
  mastery,
  ledger,
  omissions,
  targetNode,
  summary,
}: {
  mastery: MasteryEntry[];
  ledger: LedgerEvent[];
  omissions: string[];
  targetNode: string | null;
  summary: string;
}) {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const openButtonRef = useRef<HTMLButtonElement | null>(null);
  const level1 = mastery.filter((m) => m.level === 1);
  const childrenOf = (id: string) => mastery.filter((m) => m.parent === id);
  const verified = mastery.filter((m) => m.status === "VERIFIED").length;
  const pct = mastery.length ? Math.round((verified / mastery.length) * 100) : 0;

  const chapterGroups = useMemo(() => {
    const groups: Array<{ chapter: string; entries: MasteryEntry[] }> = [];
    for (const node of level1) {
      const chapter = node.chapter ?? "Other";
      const existing = groups.find((group) => group.chapter === chapter);
      if (existing) {
        existing.entries.push(node);
      } else {
        groups.push({ chapter, entries: [node] });
      }
    }
    return groups;
  }, [level1]);

  const selectedEntry = mastery.find((m) => m.node_id === selectedNode) ?? null;

  const hasSubtreeEvidence = (nodeId: string) => {
    const ids = subtreeIdsOf(nodeId, mastery);
    return ledger.some((event) => ids.has(event.node_id));
  };

  const renderEntry = (entry: MasteryEntry) => {
    const isOmitted = omissions.includes(entry.node_id) && !hasSubtreeEvidence(entry.node_id);
    const children = childrenOf(entry.node_id);
    return (
      <div
        key={entry.node_id}
        className={[
          "rounded-xl border bg-zinc-900/40 p-3",
          isOmitted ? "border-dashed border-rose-500/60 bg-rose-500/5" : "border-zinc-800/80",
        ].join(" ")}
      >
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[entry.status]}`} />
          <button
            type="button"
            onClick={(e) => {
              setSelectedNode(entry.node_id);
              openButtonRef.current = e.currentTarget;
            }}
            className={[
              "flex-1 text-left text-sm font-medium transition",
              entry.status === "VERIFIED" ? "text-emerald-100" : "text-zinc-200",
              targetNode === entry.node_id ? "animate-pulse" : "",
            ].join(" ")}
          >
            {entry.title}
          </button>
          {isOmitted && (
            <span className="rounded-full border border-rose-500/50 bg-rose-500/10 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.18em] text-rose-200">
              not mentioned
            </span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {children.map((child) => (
            <button
              key={child.node_id}
              type="button"
              title={`${child.title} — ${child.status}${child.confidence != null ? ` (${Math.round(child.confidence * 100)}%)` : ""}`}
              onClick={(e) => {
                setSelectedNode(child.node_id);
                openButtonRef.current = e.currentTarget;
              }}
              className={[
                "rounded-md border px-2 py-0.5 text-[11px] leading-5 whitespace-nowrap",
                STATUS_STYLE[child.status],
                child.level === 3 ? "opacity-80" : "",
                targetNode === child.node_id ? "ring-2 ring-sky-400/70 animate-pulse" : "",
              ].join(" ")}
            >
              {child.level === 3 && <span className="text-zinc-500 mr-1">L3</span>}
              {shortTitle(child.title)}
            </button>
          ))}
        </div>
      </div>
    );
  };

  return (
    <aside className="flex h-full min-h-0 flex-col gap-4">
      <div>
        <div className="flex items-baseline justify-between">
          <h2 className="text-xs uppercase tracking-[0.2em] text-zinc-500">Mastery ledger</h2>
          <span className="text-sm text-zinc-300 tabular-nums">
            {verified}/{mastery.length} · {pct}%
          </span>
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-zinc-800">
          <div className="h-full bg-emerald-400 transition-all duration-700" style={{ width: `${pct}%` }} />
        </div>
        {summary && <p className="mt-2 text-xs leading-snug text-zinc-400">{summary}</p>}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto pr-1">
        {selectedEntry ? (
          <EvidencePanel
            entry={selectedEntry}
            ledger={ledger}
            onClose={() => {
              setSelectedNode(null);
              requestAnimationFrame(() => openButtonRef.current?.focus());
            }}
            returnFocusRef={openButtonRef}
          />
        ) : chapterGroups.length > 1 ? (
          <div className="space-y-3">
            {chapterGroups.map((group) => (
              <div key={group.chapter} className="space-y-2">
                <h3 className="text-[10px] uppercase tracking-[0.2em] text-zinc-500">{group.chapter}</h3>
                {group.entries.map(renderEntry)}
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-3">{level1.map(renderEntry)}</div>
        )}
      </div>

      <div className="flex gap-3 text-[10px] text-zinc-500">
        {(["VERIFIED", "PARTIAL", "GAP", "NOT_MENTIONED"] as NodeStatus[]).map((s) => (
          <span key={s} className="flex items-center gap-1">
            <span className={`h-2 w-2 rounded-full ${STATUS_DOT[s]}`} />
            {s === "NOT_MENTIONED" ? "pending" : s.toLowerCase()}
          </span>
        ))}
      </div>
    </aside>
  );
}
