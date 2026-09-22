"use client";

import { Check, CircleHelp, Loader2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useJob } from "@/components/research/jobs";
import { TERMS, type TermKey } from "@/lib/plain";
import { research, type StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

// Building blocks of the Simple-mode pages: plain help, the journey tracker, status chips.

/** A "?" button that opens the plain meaning of a term. */
export function Help({ term, className }: { term: TermKey; className?: string }) {
  const [open, setOpen] = useState(false);
  const t = TERMS[term];
  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={`${t.name} ka matlab`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex size-7 items-center justify-center rounded-full text-primary hover:bg-primary/10"
      >
        <CircleHelp className="size-4" />
      </button>
      {open && (
        <span
          role="note"
          className="absolute top-8 right-0 z-20 w-64 rounded-lg border bg-popover p-3 text-left text-xs leading-relaxed text-popover-foreground shadow-lg"
        >
          <b className="block text-primary">{t.name}</b>
          {t.plain}
        </span>
      )}
    </span>
  );
}

export type StageState = "done" | "fail" | "now" | "todo";

export const STAGES = ["Banaya", "Pehla test", "Sudhaaro", "Final check", "Paper trade"] as const;

/** The strategy journey: Banaya → Pehla test → Sudhaaro → Final check → Paper trade. */
export function Tracker({ states, compact = false }: { states: StageState[]; compact?: boolean }) {
  if (compact) {
    return (
      <div className="flex gap-1" aria-label={STAGES.map((s, i) => `${s}: ${states[i]}`).join(", ")}>
        {states.map((s, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 w-6 rounded-full",
              s === "done" && "bg-emerald-400",
              s === "fail" && "bg-red-400",
              s === "now" && "bg-primary",
              s === "todo" && "bg-muted",
            )}
          />
        ))}
      </div>
    );
  }
  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {STAGES.map((label, i) => {
        const s = states[i];
        return (
          <li key={label} className="flex items-center gap-3">
            <span className="flex items-center gap-2">
              <span
                className={cn(
                  "flex size-7 items-center justify-center rounded-full",
                  s === "done" && "bg-emerald-400 text-background",
                  s === "fail" && "bg-red-400 text-background",
                  s === "now" && "border-2 border-primary text-primary",
                  s === "todo" && "border-2 border-muted",
                )}
              >
                {s === "done" && <Check className="size-4" strokeWidth={3} />}
                {s === "fail" && <X className="size-4" strokeWidth={3} />}
              </span>
              <span className={cn("text-sm font-medium", s === "fail" && "text-red-400", s === "todo" && "text-muted-foreground")}>{label}</span>
            </span>
            {i < STAGES.length - 1 && <span className="hidden h-px w-8 bg-border sm:block" />}
          </li>
        );
      })}
    </ol>
  );
}

export function Pill({ tone, children }: { tone: "good" | "warn" | "bad" | "muted"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-full px-2.5 text-xs font-semibold whitespace-nowrap",
        tone === "good" && "bg-emerald-500/15 text-emerald-300",
        tone === "warn" && "bg-amber-500/15 text-amber-200",
        tone === "bad" && "bg-red-500/15 text-red-300",
        tone === "muted" && "bg-muted text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

/**
 * Save a spec, backtest it on a tier and open its plain result page when done.
 * One job at a time; the job tray in the header shows it too.
 */
export function useTestRun() {
  const router = useRouter();
  const job = useJob({ navigate: false });
  const [err, setErr] = useState<string | null>(null);
  const opened = useRef<string | null>(null);

  useEffect(() => {
    const j = job.job;
    if (j?.status === "done" && j.result?.run_id && opened.current !== j.job_id) {
      opened.current = j.job_id;
      router.push(`/result?run=${j.result.run_id}`);
    }
  }, [job.job, router]);

  const run = async (spec: StrategySpec, tier: "A" | "B" | "AB" = "A", parent?: string | null) => {
    setErr(null);
    try {
      await research.save(spec, parent ?? null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      return;
    }
    await job.start(() => research.backtest(spec, tier));
  };

  const failed = job.job?.status === "failed" ? job.job.message || "Test fail ho gaya" : null;
  return { run, busy: job.busy, job: job.job, error: err ?? job.error ?? failed };
}

/** Progress line for a running test, in plain words. */
export function TestProgress({
  busy,
  pct,
  error,
  label = "Test chal raha hai — har 5-minute candle pe, asli kharchon ke saath",
}: {
  busy: boolean;
  pct: number | null;
  error: string | null;
  label?: string;
}) {
  if (error) return <p className="text-sm text-red-300">Nahi chala: {error}</p>;
  if (!busy) return null;
  return (
    <div className="space-y-1.5" role="status">
      <p className="flex items-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin text-primary" />
        {label}
        {pct != null ? ` · ${pct}%` : "…"}
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-primary transition-all" style={{ width: `${Math.max(pct ?? 3, 3)}%` }} />
      </div>
    </div>
  );
}
