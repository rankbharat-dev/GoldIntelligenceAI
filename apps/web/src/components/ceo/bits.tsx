"use client";

import { Check, Copy, Crown, Database, DraftingCompass, ScanSearch, ShieldCheck, type LucideIcon } from "lucide-react";
import { useState } from "react";

import type { AgentKey, MissionStatus, TaskState } from "@/lib/ceo";
import { cn } from "@/lib/utils";

export const AGENT_ICON: Record<AgentKey, LucideIcon> = {
  director: Crown,
  data_scientist: Database,
  pattern_analyst: ScanSearch,
  strategy_architect: DraftingCompass,
  validator: ShieldCheck,
};

export const AGENT_NAME: Record<AgentKey, string> = {
  director: "Research Director",
  data_scientist: "Data Scientist",
  pattern_analyst: "Pattern Analyst",
  strategy_architect: "Strategy Architect",
  validator: "Validation Analyst",
};

/** Plain-Hinglish labels: the owner should never need to decode a state name. */
export const MISSION_LABEL: Record<MissionStatus, { text: string; cls: string }> = {
  draft: { text: "Director ke plan ka intezaar", cls: "border-sky-500/40 text-sky-300" },
  awaiting_approval: { text: "Plan aapki approval ka intezaar", cls: "border-amber-500/50 text-amber-300" },
  running: { text: "Kaam chal raha hai", cls: "border-primary/50 text-primary" },
  paused: { text: "Ruka hua (pause)", cls: "border-amber-500/40 text-amber-300" },
  completed: { text: "Report taiyaar", cls: "border-emerald-500/40 text-emerald-300" },
  failed: { text: "Fail / time khatam", cls: "border-red-500/40 text-red-300" },
  cancelled: { text: "Cancel kiya", cls: "text-muted-foreground" },
};

export const TASK_LABEL: Record<TaskState, { text: string; cls: string }> = {
  pending: { text: "plan mein", cls: "text-muted-foreground" },
  waiting_deps: { text: "pichhle kaam ka intezaar", cls: "text-muted-foreground" },
  waiting_ceo: { text: "aapki approval chahiye", cls: "border-amber-500/50 text-amber-300" },
  queued: { text: "shuru hone ko taiyaar", cls: "border-sky-500/40 text-sky-300" },
  running: { text: "kaam chal raha hai", cls: "border-primary/50 text-primary" },
  completed: { text: "✓ ho gaya", cls: "border-emerald-500/40 text-emerald-300" },
  failed: { text: "✗ fail", cls: "border-red-500/40 text-red-300" },
  cancelled: { text: "cancel", cls: "text-muted-foreground" },
};

export function Chip({ text, cls }: { text: string; cls?: string }) {
  return <span className={cn("inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[11px] whitespace-nowrap", cls)}>{text}</span>;
}

export function CopyCommand({ command }: { command: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(command).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-xs text-primary hover:bg-primary/20"
      title="Copy"
    >
      {command}
      {done ? <Check className="size-3" /> : <Copy className="size-3" />}
    </button>
  );
}

export function ago(iso: string | null | undefined) {
  if (!iso) return "—";
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s pehle`;
  if (s < 3600) return `${Math.round(s / 60)} min pehle`;
  if (s < 86400) return `${Math.round(s / 3600)} ghante pehle`;
  return `${Math.round(s / 86400)} din pehle`;
}
