"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronDown, ChevronUp, CircleAlert, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { TradeReplay } from "@/components/replay/trade-replay";
import { Help, Pill, TestProgress, Tracker, useTestRun, type StageState } from "@/components/simple/ui";
import { EquityStory, WhereItWorks, WhyPanel } from "@/components/simple/why";
import { TIER_PLAIN, totalCostR, verdictOf, widerExits, type TermKey, type Verdict } from "@/lib/plain";
import { fmtInt, fmtNum, fmtPct, fmtR, research, type BacktestRun, type Metrics } from "@/lib/research";
import { cn } from "@/lib/utils";

// Simple mode · answer first: one verdict, three numbers, what to do next. The jargon lives
// under "Expert details"; the full report stays on /backtest.

export default function ResultPage() {
  return (
    <Suspense>
      <Result />
    </Suspense>
  );
}

function Result() {
  const runId = useSearchParams().get("run");
  const q = useQuery({
    queryKey: ["run", runId],
    queryFn: () => research.run<BacktestRun>(runId!),
    enabled: !!runId,
    retry: false,
  });
  if (!runId)
    return (
      <Shell>
        <p className="text-muted-foreground">
          Koi result chuna nahi.{" "}
          <Link href="/my" className="text-primary hover:underline">
            Meri strategies
          </Link>{" "}
          se ek kholo, ya{" "}
          <Link href="/idea" className="text-primary hover:underline">
            naya idea test karo
          </Link>
          .
        </p>
      </Shell>
    );
  if (q.isLoading) return <Shell><p className="text-muted-foreground">Result load ho raha hai…</p></Shell>;
  if (q.error || !q.data) return <Shell><p className="text-red-300">Result nahi mila: {String(q.error ?? "")}</p></Shell>;
  if (q.data.kind !== "backtest")
    return (
      <Shell>
        <p className="text-muted-foreground">
          Yeh test ka result nahi hai.{" "}
          <Link href={`/backtest?run=${runId}`} className="text-primary hover:underline">
            Expert page pe kholo
          </Link>
          .
        </p>
      </Shell>
    );
  return <ResultView run={q.data} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-6xl px-4 py-8 md:px-8">{children}</div>;
}

const TONE = {
  good: { box: "border-emerald-500/40 bg-emerald-500/10", dot: "bg-emerald-400", Icon: Check },
  warn: { box: "border-amber-500/40 bg-amber-500/10", dot: "bg-amber-400", Icon: CircleAlert },
  bad: { box: "border-red-500/40 bg-red-500/10", dot: "bg-red-400", Icon: X },
} as const;

function ResultView({ run }: { run: BacktestRun }) {
  const m = run.results.pessimistic;
  const v = verdictOf(m);
  const t = TONE[v.tone];
  const stages: StageState[] = ["done", v.kind === "pass" ? "done" : "fail", v.kind === "pass" ? "now" : "todo", "todo", "todo"];
  const [expert, setExpert] = useState(false);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-8 md:px-8">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
        <span>
          <Link href="/my" className="hover:text-foreground">
            Meri strategies
          </Link>{" "}
          / <span className="text-foreground">{run.name}</span>
        </span>
        <Link href={`/backtest?run=${run.run_id}`} className="text-primary hover:underline">
          Poori expert report →
        </Link>
      </div>

      <Tracker states={stages} />

      <section aria-label="Jawab" className={cn("flex flex-col gap-4 rounded-2xl border p-6 sm:flex-row sm:items-start", t.box)}>
        <span className={cn("flex size-14 shrink-0 items-center justify-center rounded-full text-background", t.dot)}>
          <t.Icon className="size-7" strokeWidth={2.6} />
        </span>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold md:text-3xl">{v.title}</h1>
          <p className="max-w-3xl text-base leading-relaxed">{v.why}</p>
          <p className="text-sm text-muted-foreground">
            {TIER_PLAIN[run.tier] ?? run.tier} pe · mehenge kharche ke saath · final exam data band hai
          </p>
        </div>
      </section>

      <section aria-label="Teen numbers" className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Tile term="r" label="Har trade ki average kamai" value={fmtR(m.expectancy_r, 2)} sub={m.expectancy_r != null ? `≈ ${m.expectancy_r < 0 ? "−" : "+"}$${Math.abs(m.expectancy_r * 100).toFixed(0)} har $100 risk pe` : "—"} tone={m.expectancy_r == null ? undefined : m.expectancy_r > 0 ? "good" : "bad"} />
        <Tile term="trades" label="Kitne trades mile" value={fmtInt(m.n)} sub={`${fmtPct(m.win_rate, 0)} trades faayde mein`} />
        <Tile term="drawdown" label="Sabse bada gira hua nuksaan" value={m.max_dd_r != null ? `${fmtNum(m.max_dd_r, 1)} R` : "—"} sub="upar ke peak se neeche tak" />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <WhyPanel m={m} v={v} />
        <EquityStory m={m} />
      </div>

      <section aria-label="Chart pe verify karo" className="space-y-3 rounded-2xl border border-primary/30 bg-card p-5">
        <div>
          <h2 className="text-lg font-bold">Chart pe verify karo — har trade, aapke rules ke saath</h2>
          <p className="text-sm text-muted-foreground">
            Koi bhi trade chuno: asli XAUUSD chart pe signal candle, entry, stop-loss aur target dikhega. Right side mein engine batata hai ki us
            candle pe aapka har rule sach tha ya nahi. &quot;Replay&quot; dabao — candle-by-candle trade chalte hue dekho.
          </p>
        </div>
        <TradeReplay run={run} />
      </section>

      <WhereItWorks m={m} />

      <CostStory m={m} />

      <NextSteps run={run} v={v} />

      <section aria-label="Expert details" className="rounded-2xl border bg-card">
        <button
          type="button"
          aria-expanded={expert}
          onClick={() => setExpert((e) => !e)}
          className="flex w-full items-center justify-between px-5 py-4 text-left"
        >
          <span className="font-semibold">
            Expert details <span className="font-normal text-muted-foreground">— technical naam aur saare numbers</span>
          </span>
          {expert ? <ChevronUp className="size-5" /> : <ChevronDown className="size-5" />}
        </button>
        {expert && <ExpertTable run={run} />}
      </section>
    </div>
  );
}

function Tile({ term, label, value, sub, tone }: { term: TermKey; label: string; value: string; sub: string; tone?: "good" | "bad" }) {
  return (
    <div className="flex flex-col gap-1 rounded-2xl border bg-card p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground">{label}</span>
        <Help term={term} />
      </div>
      <span className={cn("font-mono text-3xl font-bold tabular-nums", tone === "good" && "text-emerald-400", tone === "bad" && "text-red-400")}>{value}</span>
      <span className="text-xs text-muted-foreground">{sub}</span>
    </div>
  );
}

/** Before costs → costs → what is left, per trade, from the engine's own breakdown. */
function CostStory({ m }: { m: Metrics }) {
  const before = m.expectancy_before_costs_r;
  const cost = totalCostR(m);
  if (before == null || cost == null || m.expectancy_r == null) return null;
  const tiny = Math.abs(before) < 0.005;
  const cells: { label: string; value: string; cls: string }[] = [
    { label: "Pattern ki kamai (kharche se pehle)", value: tiny ? "≈ 0 R (kuch nahi)" : fmtR(before, 2), cls: tiny ? "" : before > 0 ? "text-emerald-400" : "text-red-400" },
    { label: "Kharcha (spread, slippage, commission, swap)", value: `−${cost.toFixed(2)} R`, cls: "text-red-400" },
    { label: "Aapke haath mein bacha", value: fmtR(m.expectancy_r, 2), cls: m.expectancy_r > 0 ? "text-emerald-400" : "text-red-400" },
  ];
  return (
    <section aria-label="Paisa kahan gaya" className="space-y-3">
      <div className="flex items-center gap-1">
        <h2 className="text-lg font-bold">Paisa kahan gaya? (har trade, average)</h2>
        <Help term="costs" />
      </div>
      <div className="grid grid-cols-1 items-stretch gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
        {cells.map((c, i) => (
          <div key={c.label} className="contents">
            <div className="rounded-xl border bg-card px-4 py-3">
              <p className="text-xs text-muted-foreground">{c.label}</p>
              <p className={cn("font-mono text-xl font-semibold tabular-nums", c.cls)}>{c.value}</p>
            </div>
            {i < cells.length - 1 && <span className="hidden items-center text-muted-foreground md:flex">{i === 0 ? "−" : "="}</span>}
          </div>
        ))}
      </div>
    </section>
  );
}

function NextSteps({ run, v }: { run: BacktestRun; v: Verdict }) {
  const test = useTestRun();
  const pct = test.job ? Math.round(test.job.progress * 100) : null;
  const card = "flex min-h-36 flex-col gap-2 rounded-2xl border p-5 text-left";
  const cta = "mt-auto inline-flex items-center gap-1.5 text-sm font-semibold text-primary";
  const wider = run.spec.exit.target_atr != null && run.spec.exit.target_atr < 6;

  const options: { key: string; title: string; body: string; cta: string; primary?: boolean; href?: string; onClick?: () => void }[] = [];
  if (v.kind === "pass") {
    options.push({ key: "val", title: "Final check karo", body: "Naye data (check data), walk-forward aur luck test. Wahan bhi pass hua tabhi strategy asli candidate banti hai.", cta: "Final check shuru karo", primary: true, href: `/validate?spec=${run.spec_hash}` });
    options.push({ key: "opt", title: "Settings sudhaaro", body: "Stop / target ki range try karo — par har variant ek koshish gina jaata hai, isliye kam hi try karo.", cta: "Optimize kholo (Expert)", href: `/optimize` });
  }
  if ((v.kind === "loss_costs" || v.kind === "weak") && wider) {
    options.push({ key: "wide", title: "Target bada karo (1:3)", body: "Bade target mein kharcha kamai ka chhota hissa ban jaata hai. Sabse aasaan agla try — ek click mein.", cta: "Bada target se dobara test", primary: true, onClick: () => void test.run(widerExits(run.spec), "A", run.spec_hash) });
  }
  if (v.kind === "loss_costs" || v.kind === "weak") {
    options.push({ key: "ml", title: "Sirf strong cases rakho", body: "AI filter kamzor signals hata deta hai. Practice data pe seekhta hai, check data pe judge hota hai.", cta: "AI filter try karo (Expert)", href: "/ml" });
  }
  if (v.kind === "few" || v.kind === "empty") {
    options.push({ key: "ab", title: "Zyada data pe chalao", body: "Practice + check data dono pe test — zyada trades milenge. (Final exam data phir bhi band rahega.)", cta: "A+B pe dobara test", primary: true, onClick: () => void test.run(run.spec, "AB") });
    options.push({ key: "loosen", title: "Filter dheela karo", body: "\"Poora din\" aur \"Dono\" disha chuno — rules zyada candles pe lagenge.", cta: "Naya idea banao", href: "/idea" });
  }
  if (v.kind === "loss") {
    options.push({ key: "new", title: "Doosra idea try karo", body: "Is pattern ke baad price koi khaas disha nahi pakadta. Koi aur pattern chuno.", cta: "Naya idea", primary: true, href: "/idea" });
    options.push({ key: "learn", title: "Pehle market samjho", body: "Dekho kaunse patterns ke baad gold sach mein kuch karta hai.", cta: "Patterns dekho", href: "/learn" });
  }
  if (v.kind !== "pass")
    options.push({ key: "drop", title: "Idea chhod do", body: "Yeh bhi achha jawab hai: ek galat idea pe asli paisa lagne se bach gaye.", cta: "Strategies pe wapas", href: "/my" });

  return (
    <section aria-label="Ab kya karein" className="space-y-3">
      <h2 className="text-lg font-bold">Ab kya karein?</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {options.slice(0, 3).map((o) => {
          const cls = cn(card, o.primary ? "border-primary/40 bg-primary/10 hover:bg-primary/15" : "bg-card hover:bg-muted/40");
          const body = (
            <>
              <span className="text-base font-semibold">{o.title}</span>
              <span className="text-sm leading-relaxed text-muted-foreground">{o.body}</span>
              <span className={cta}>
                {o.cta}
                <ArrowRight className="size-4" />
              </span>
            </>
          );
          return o.href ? (
            <Link key={o.key} href={o.href} className={cls}>
              {body}
            </Link>
          ) : (
            <button key={o.key} type="button" disabled={test.busy} onClick={o.onClick} className={cn(cls, "disabled:opacity-60")}>
              {body}
            </button>
          );
        })}
      </div>
      <TestProgress busy={test.busy} pct={pct} error={test.error} />
    </section>
  );
}

function ExpertTable({ run }: { run: BacktestRun }) {
  const m = run.results.pessimistic;
  const d = run.deflated_sharpe;
  const rows: [string, string, string, TermKey?][] = [
    ["Expectancy (pessimistic)", "Har trade ki average kamai, mehenge kharche ke saath", fmtR(m.expectancy_r), "expectancy"],
    ["Expectancy (base)", "Normal kharche ke saath", fmtR(run.results.base.expectancy_r)],
    ["Expectancy before costs", "Kharche se pehle", fmtR(m.expectancy_before_costs_r)],
    ["Trades", "Kitni baar trade bana", fmtInt(m.n), "trades"],
    ["Win rate", "Kitne % trades faayde mein", fmtPct(m.win_rate), "win_rate"],
    ["Profit factor", "Total jeet ÷ total haar (pass: ≥ 1.15)", fmtNum(m.profit_factor), "profit_factor"],
    ["Max drawdown", "Sabse bada gira hua nuksaan (pass: ≤ 15 R)", m.max_dd_r != null ? `${fmtNum(m.max_dd_r, 1)} R` : "—", "drawdown"],
    ["Deflated Sharpe (excess)", "Luck test — 0 se upar chahiye", d ? fmtNum(d.deflated_excess, 3) : "—", "deflated"],
    ["Family trials", "Is idea ke kitne versions try hue", fmtInt(run.family_trials), "trials"],
    ["Tier", "Kaunsa data", TIER_PLAIN[run.tier] ?? run.tier, "tier"],
    ["Run id", "Is result ka pakka pata (source)", run.run_id],
  ];
  return (
    <div className="overflow-x-auto px-5 pb-4">
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([tech, plain, val, term]) => (
            <tr key={tech} className="border-t">
              <td className="py-2 pr-3 font-mono text-xs text-primary">{tech}</td>
              <td className="py-2 pr-3 text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  {plain}
                  {term && <Help term={term} />}
                </span>
              </td>
              <td className="py-2 text-right font-mono tabular-nums">{val}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="pt-2 text-xs text-muted-foreground">
        <Pill tone="muted">Source</Pill> Har number engine ke run <span className="font-mono">{run.run_id}</span> se · cost model{" "}
        <span className="font-mono">{run.lineage.cost_model_id}</span>
      </p>
    </div>
  );
}
