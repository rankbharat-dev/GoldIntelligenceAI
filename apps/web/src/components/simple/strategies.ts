"use client";

import { useQuery } from "@tanstack/react-query";

import { CREATED_BY, MIN_TRADES_TO_JUDGE, PASS_EXPECTANCY } from "@/lib/plain";
import { research, type RunRow, type SpecRow } from "@/lib/research";

import type { StageState } from "./ui";

// Each saved strategy as a journey: where it stands, in plain words, and the one next step.

export type NextAction =
  | { kind: "test" }
  | { kind: "link"; href: string };

export interface StrategyJourney {
  row: SpecRow;
  by: string;
  stages: StageState[];
  status: { text: string; tone: "good" | "warn" | "bad" | "muted" };
  next: { label: string; action: NextAction };
  lastBacktest: RunRow | null;
  lastValidate: RunRow | null;
}

const num = (x: unknown) => (typeof x === "number" ? x : null);

export function journey(row: SpecRow, runs: RunRow[]): StrategyJourney {
  const bt = runs.find((r) => r.kind === "backtest") ?? null;
  const va = runs.find((r) => r.kind === "validate") ?? null;
  const opt = runs.some((r) => r.kind === "optimize");
  const stages: StageState[] = ["done", "now", "todo", "todo", "todo"];
  let status: StrategyJourney["status"] = { text: "Test baaki hai", tone: "muted" };
  let next: StrategyJourney["next"] = { label: "Test chalao", action: { kind: "test" } };

  if (bt) {
    const e = num(bt.summary.expectancy_r);
    const n = num(bt.summary.n) ?? 0;
    const passed = e != null && e >= PASS_EXPECTANCY && n >= MIN_TRADES_TO_JUDGE;
    stages[1] = passed ? "done" : "fail";
    stages[2] = opt ? "done" : passed ? "now" : "todo";
    if (n < MIN_TRADES_TO_JUDGE) status = { text: "Trades bahut kam", tone: "warn" };
    else if (e != null && e <= 0) status = { text: "Pehle test mein fail", tone: "bad" };
    else if (!passed) status = { text: "Thoda positive, pass nahi", tone: "warn" };
    else status = { text: "Pehla test pass", tone: "good" };
    next = passed
      ? { label: "Final check karo", action: { kind: "link", href: `/validate?spec=${row.spec_hash}` } }
      : { label: "Result dekho", action: { kind: "link", href: `/result?run=${bt.run_id}` } };
  }
  if (va) {
    const v = va.summary.verdict;
    stages[1] = stages[1] === "now" ? "done" : stages[1];
    if (v === "candidate") {
      stages[3] = "done";
      stages[4] = "now";
      status = { text: "Final check pass — paper trade ke liye taiyaar", tone: "good" };
      next = { label: "Report dekho", action: { kind: "link", href: `/validate?run=${va.run_id}` } };
    } else if (v === "rejected") {
      stages[3] = "fail";
      status = { text: "Final check mein fail", tone: "bad" };
      next = { label: "Kyun fail hua", action: { kind: "link", href: `/validate?run=${va.run_id}` } };
    } else {
      stages[3] = "now";
      status = { text: "Final check adhoora (final exam baaki)", tone: "warn" };
      next = { label: "Report dekho", action: { kind: "link", href: `/validate?run=${va.run_id}` } };
    }
  }
  return { row, by: CREATED_BY[row.created_by] ?? row.created_by, stages, status, next, lastBacktest: bt, lastValidate: va };
}

export function useJourneys() {
  const specs = useQuery({ queryKey: ["strategies"], queryFn: research.strategies, retry: false });
  const runs = useQuery({ queryKey: ["runs", "all"], queryFn: () => research.runs(), retry: false });
  const bySpec = new Map<string, RunRow[]>();
  for (const r of runs.data ?? []) {
    const list = bySpec.get(r.spec_hash) ?? [];
    list.push(r); // API returns newest first
    bySpec.set(r.spec_hash, list);
  }
  const rows = (specs.data ?? [])
    .map((s) => journey(s, bySpec.get(s.spec_hash) ?? []))
    .sort((a, b) => (b.row.last_run ?? b.row.created_at).localeCompare(a.row.last_run ?? a.row.created_at));
  return { rows, loading: specs.isLoading || runs.isLoading, error: specs.error ?? runs.error };
}
