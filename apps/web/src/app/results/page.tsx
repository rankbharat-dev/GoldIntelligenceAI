"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, PlayCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ago } from "@/components/ceo/bits";
import { Pill } from "@/components/simple/ui";
import { quickVerdict, TIER_PLAIN, VALIDATE_PLAIN } from "@/lib/plain";
import { fmtInt, fmtR, research, type RunRow } from "@/lib/research";
import { cn } from "@/lib/utils";

// Test & Analyze (Simple mode): every test in one list, newest first. Each backtest opens the
// answer-first result with its equity curve and chart replay; each final check its report.

type Kind = "all" | "backtest" | "validate";

export default function ResultsPage() {
  const [kind, setKind] = useState<Kind>("all");
  const q = useQuery({ queryKey: ["runs", "all"], queryFn: () => research.runs(), retry: false });
  const rows = (q.data ?? []).filter((r) => (kind === "all" ? r.kind === "backtest" || r.kind === "validate" : r.kind === kind));

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 md:px-8">
      <header className="space-y-1">
        <p className="text-xs font-semibold tracking-[0.18em] text-primary">TEST &amp; ANALYZE</p>
        <h1 className="text-3xl font-bold">Results &amp; replay</h1>
        <p className="text-muted-foreground">
          Har test ka seedha jawab, paise ka graph, aur chart pe ek-ek trade — aapke rules ke saath verify karo.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Explainer icon={PlayCircle} title="Pehla test" body="Practice data (2021–2024) pe, mehenge kharche ke saath. Yahan pass = sirf agle kadam ki ijaazat." />
        <Explainer icon={ShieldCheck} title="Final check" body="Naya data (2024–2025), walk-forward aur luck test. Iske baad bhi final exam data band rehta hai." />
        <Explainer icon={ArrowRight} title="Chart pe verify" body="Result kholo → 'Chart pe verify karo'. Har trade ki entry, SL, TP aur rule check dikhta hai." />
      </div>

      <section aria-label="Saare tests" className="overflow-hidden rounded-2xl border bg-card">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <h2 className="mr-auto font-semibold">Saare tests</h2>
          <div role="radiogroup" aria-label="Kaunse tests" className="flex rounded-lg border p-0.5">
            {(
              [
                ["all", "Sab"],
                ["backtest", "Pehle test"],
                ["validate", "Final checks"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={kind === k}
                onClick={() => setKind(k)}
                className={cn("h-8 rounded-md px-3 text-xs", kind === k ? "bg-muted font-semibold" : "text-muted-foreground")}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {q.isLoading && <p className="px-4 py-4 text-sm text-muted-foreground">Load ho raha hai…</p>}
        {q.error && <p className="px-4 py-4 text-sm text-red-300">Tests load nahi hue: {String(q.error)}</p>}
        {q.data && !rows.length && (
          <p className="px-4 py-4 text-sm text-muted-foreground">
            Abhi koi test nahi.{" "}
            <Link href="/idea" className="text-primary hover:underline">
              Pehla idea test karo →
            </Link>
          </p>
        )}
        <ul>
          {rows.map((r) => (
            <RunItem key={r.run_id} r={r} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function Explainer({ icon: Icon, title, body }: { icon: typeof PlayCircle; title: string; body: string }) {
  return (
    <div className="flex gap-3 rounded-2xl border bg-card p-4">
      <Icon className="mt-0.5 size-5 shrink-0 text-primary" />
      <div>
        <p className="font-semibold">{title}</p>
        <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </div>
  );
}

function RunItem({ r }: { r: RunRow }) {
  const s = r.summary;
  const name = typeof s.name === "string" ? s.name : r.family;
  const val = r.kind === "validate";
  const pill = val ? (VALIDATE_PLAIN[String(s.verdict)] ?? { text: String(s.verdict), tone: "warn" as const }) : quickVerdict(s);
  const href = val ? `/validate?run=${r.run_id}` : `/result?run=${r.run_id}`;
  const e = typeof s.expectancy_r === "number" ? s.expectancy_r : null;
  return (
    <li className="border-t first:border-t-0">
      <Link href={href} className="grid grid-cols-1 items-center gap-2 px-4 py-3 hover:bg-muted/30 md:grid-cols-[minmax(0,2fr)_minmax(0,1.3fr)_90px_90px_auto]">
        <span className="min-w-0">
          <span className="block truncate font-semibold">{name}</span>
          <span className="text-xs text-muted-foreground">
            {val ? "Final check" : "Pehla test"} · {TIER_PLAIN[r.tier] ?? r.tier} · {ago(r.created_at)}
          </span>
        </span>
        <span>
          <Pill tone={pill.tone}>{pill.text}</Pill>
        </span>
        <span className={cn("font-mono text-sm tabular-nums", e == null ? "text-muted-foreground" : e > 0 ? "text-emerald-400" : "text-red-400")} title="Har trade ki average kamai (mehenga kharcha)">
          {fmtR(e, 2)}
        </span>
        <span className="font-mono text-sm text-muted-foreground tabular-nums">{fmtInt(typeof s.n === "number" ? s.n : null)} trades</span>
        <span className="inline-flex items-center gap-1 text-sm font-semibold text-primary">
          {val ? "Report" : "Result + chart"}
          <ArrowRight className="size-4" />
        </span>
      </Link>
    </li>
  );
}
