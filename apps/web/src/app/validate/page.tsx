"use client";

import { useQuery } from "@tanstack/react-query";
import { Lock, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { BucketTable, Field, inputCls, Notice, PageHeader, Section, Stat, toneOf } from "@/components/research/bits";
import { EquityChart } from "@/components/research/equity-chart";
import { JobProgress, useJob } from "@/components/research/jobs";
import { gridSize, ParamGridEditor, toGrid, type Range } from "@/components/research/param-grid";
import { StrategyPicker } from "@/components/research/strategy-picker";
import { Button } from "@/components/ui/button";
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtR, research, type ChecklistItem, type ValidateRun } from "@/lib/research";
import { cn } from "@/lib/utils";

const VERDICT = {
  candidate: { label: "Candidate", tone: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300", text: "Every §15 criterion passed, including the one-time holdout. Next step: paper trading." },
  pending: { label: "Not yet decided", tone: "border-amber-500/50 bg-amber-500/10 text-amber-200", text: "Nothing has failed so far; the criteria marked pending still need data (usually the sealed holdout)." },
  rejected: { label: "Rejected", tone: "border-red-500/50 bg-red-500/10 text-red-300", text: "At least one pre-committed criterion failed. There is no partial promotion — the reasons are below." },
} as const;

function show(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) < 1 && v !== 0 && !Number.isInteger(v) ? v.toFixed(3) : v.toLocaleString();
  if (typeof v === "object") {
    // {r, pct} drawdown and {excess, probability} Deflated Sharpe, in readable units
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => {
        if (x == null) return `${k} —`;
        if (typeof x !== "number") return `${k} ${String(x)}`;
        if (k === "r") return `${x.toFixed(1)} R`;
        if (k === "pct" || k === "probability") return `${(x * 100).toFixed(1)}%`;
        return `${k} ${x.toFixed(3)}`;
      })
      .join(" · ");
  }
  return String(v);
}

function Checklist({ items }: { items: ChecklistItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="w-6 py-1 font-normal" />
            <th className="py-1 pr-2 text-left font-normal">Criterion (blueprint §15)</th>
            <th className="py-1 pr-2 text-right font-normal">Value</th>
            <th className="py-1 text-right font-normal">Needs</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.key} className="border-t border-border/60 align-top">
              <td className={cn("py-1.5 font-mono", i.passed === true ? "text-emerald-400" : i.passed === false ? "text-red-400" : "text-amber-300")}>
                {i.passed === true ? "✓" : i.passed === false ? "✗" : "…"}
              </td>
              <td className="py-1.5 pr-2">
                {i.label}
                {i.why && <span className="block text-[11px] text-muted-foreground">{i.why}</span>}
              </td>
              <td className="py-1.5 pr-2 text-right font-mono tabular-nums">{show(i.value)}</td>
              <td className="py-1.5 text-right text-muted-foreground">{i.threshold}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Unseal({ run }: { run: ValidateRun }) {
  const [reason, setReason] = useState("");
  const [family, setFamily] = useState("");
  const job = useJob();
  const ready = run.checklist.ready_to_unseal;
  return (
    <Section
      title="Final holdout (tier C) — one look, ever"
      description={`Tier C (from ${fmtDate(run.split.c_start)}, the newest ~20 % of data) has never been used by any backtest. Each strategy family may look at it exactly once; after that it becomes ordinary development data for the family.`}
    >
      {run.holdout ? (
        <div className="space-y-1 text-xs">
          <p>
            Family <b>{run.family}</b> used its holdout on {run.holdout.accessed_at.slice(0, 16).replace("T", " ")} for strategy{" "}
            <span className="font-mono">{run.holdout.strategy_id}</span>.
          </p>
          <p className="text-muted-foreground">Reason logged: “{run.holdout.reason}”</p>
          {run.holdout_run ? (
            <Link className="text-primary hover:underline" href={`/backtest?run=${run.holdout_run}`}>
              Open the tier C result
            </Link>
          ) : (
            <p className="text-muted-foreground">Run Validate again to include the tier C result in the checklist.</p>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {ready ? (
            <Notice tone="warn">Every other criterion passed. This is the moment the holdout exists for.</Notice>
          ) : (
            <Notice tone="error">
              {run.checklist.failed} criterion(s) already failed. Unsealing now spends this family’s only holdout on a strategy
              that cannot be promoted — usually a mistake.
            </Notice>
          )}
          <Field label="Why now? (logged permanently)">
            <textarea className={cn(inputCls, "h-14 py-1.5")} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Field label={`Type the family name to confirm: ${run.family}`}>
            <input className={inputCls} value={family} onChange={(e) => setFamily(e.target.value)} />
          </Field>
          <Button
            variant="destructive"
            size="sm"
            disabled={reason.trim().length < 10 || family.trim() !== run.family || job.busy}
            onClick={() => job.start(() => research.unseal(run.spec_hash, reason, family))}
          >
            <Lock /> Unseal tier C for “{run.family}”
          </Button>
          <JobProgress job={job.job} error={job.error} />
        </div>
      )}
    </Section>
  );
}

function ResultView({ id }: { id: string }) {
  const { data: run, error } = useQuery({ queryKey: ["run", id], queryFn: () => research.run<ValidateRun>(id) });
  const wfCurve = useMemo(
    () =>
      run?.walk_forward.oos.equity?.time.length
        ? [{ name: "out-of-sample", color: "#e0b04a", time: run.walk_forward.oos.equity.time, value: run.walk_forward.oos.equity.cum_r }]
        : [],
    [run],
  );
  if (error) return <Notice tone="error">{String(error)}</Notice>;
  if (!run) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const v = VERDICT[run.checklist.verdict];
  const wf = run.walk_forward;
  const rb = run.robustness;
  const dsr = run.deflated_sharpe;
  const maxFold = Math.max(...wf.folds.map((f) => Math.abs(f.total_r ?? 0)), 0.001);
  return (
    <div className="space-y-3">
      <PageHeader title={`Validate · ${run.name}`} subtitle={`${run.family} · ${run.spec_hash} · run ${run.run_id}`}>
        <div className="flex gap-3 text-xs">
          <Link className="text-primary hover:underline" href={`/strategy-lab?spec=${run.spec_hash}`}>Edit</Link>
          <Link className="text-primary hover:underline" href={`/validate?spec=${run.spec_hash}`}>Validate again</Link>
        </div>
      </PageHeader>

      <div className={cn("flex items-start gap-3 rounded-xl border p-3", v.tone)}>
        <ShieldCheck className="mt-0.5 size-5 shrink-0" />
        <div>
          <p className="text-sm font-semibold">{v.label}</p>
          <p className="text-xs opacity-90">
            {v.text} {run.checklist.failed} failed · {run.checklist.pending} pending.
          </p>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Section title="Promotion checklist" description="Pre-committed thresholds; pessimistic costs throughout.">
          <Checklist items={run.checklist.items} />
        </Section>
        <div className="space-y-3">
          <Section title="Tiers side by side" description="Expectancy per trade · trades (in brackets).">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-normal">Tier</th>
                  <th className="py-1 text-right font-normal">Optimistic</th>
                  <th className="py-1 text-right font-normal">Base</th>
                  <th className="py-1 text-right font-normal">Pessimistic</th>
                  <th className="py-1 text-right font-normal">PF (pess.)</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {(["A", "B", "AB"] as const).map((t) => (
                  <tr key={t} className="border-t border-border/60">
                    <td className="py-1 font-sans">
                      <Link className="text-primary hover:underline" href={`/backtest?run=${run.backtests[t]}`}>
                        {t === "AB" ? "A+B" : t}
                      </Link>
                    </td>
                    {(["optimistic", "base", "pessimistic"] as const).map((s) => {
                      const m = run.tiers[t][s];
                      return (
                        <td key={s} className={cn("py-1 text-right", (m.expectancy_r ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>
                          {fmtNum(m.expectancy_r, 3)} <span className="text-muted-foreground">({fmtInt(m.n)})</span>
                        </td>
                      );
                    })}
                    <td className="py-1 text-right">{fmtNum(run.tiers[t].pessimistic.profit_factor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Deflated Sharpe (A+B)" value={dsr ? (dsr.deflated_excess > 0 ? "above bar" : "below bar") : "—"} tone={dsr ? (dsr.deflated_excess > 0 ? "good" : "bad") : "muted"} hint={dsr ? `${dsr.n_trials} trials · P ${fmtPct(dsr.probability)}` : undefined} />
            <Stat label="Bootstrap 95 % range" value={`${fmtNum(rb.bootstrap_expectancy_ci.low, 3)} … ${fmtNum(rb.bootstrap_expectancy_ci.high, 3)}`} hint="expectancy, R" />
            <Stat label="Bad-case drawdown" value={rb.monte_carlo_drawdown_r.p95 == null ? "—" : `${rb.monte_carlo_drawdown_r.p95} R`} hint="95th pct, reshuffled" />
            <Stat
              label="Intrabar policy effect"
              value={fmtR(run.ambiguity_sensitivity.difference_r)}
              hint="optimistic − pessimistic policy"
              tone={Math.abs(run.ambiguity_sensitivity.difference_r ?? 0) > 0.02 ? "bad" : undefined}
            />
          </div>
        </div>
      </div>

      <Section
        title={`Walk-forward · ${wf.mode}`}
        description={`${wf.train_months}-month training windows, each followed by ${wf.test_months} unseen months. Only the unseen months count below. ${wf.positive_folds} of ${wf.scored_folds} test windows were positive.`}
      >
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-1">
            {wf.folds.map((f) => {
              const t = f.total_r ?? 0;
              return (
                <div key={f.test[0]} className="grid grid-cols-[88px_minmax(0,1fr)_110px] items-center gap-2 text-[11px]">
                  <span className="font-mono text-muted-foreground">{f.test[0].slice(0, 7)}</span>
                  <div className="relative h-3 rounded bg-muted">
                    <div className="absolute inset-y-0 left-1/2 w-px bg-foreground/30" />
                    <div
                      className={cn("absolute inset-y-0", t >= 0 ? "left-1/2 bg-emerald-500/70" : "right-1/2 bg-red-500/70")}
                      style={{ width: `${(Math.abs(t) / maxFold) * 50}%` }}
                    />
                  </div>
                  <span className="text-right font-mono">
                    {t.toFixed(1)} R <span className="text-muted-foreground">({f.n})</span>
                  </span>
                </div>
              );
            })}
          </div>
          <div>
            <div className="mb-2 grid grid-cols-3 gap-2">
              <Stat label="OOS expectancy" value={fmtR(wf.oos.expectancy_r)} tone={toneOf(wf.oos.expectancy_r)} />
              <Stat label="OOS trades" value={fmtInt(wf.oos.n)} />
              <Stat label="OOS PF" value={fmtNum(wf.oos.profit_factor)} />
            </div>
            {wfCurve.length > 0 && <EquityChart curves={wfCurve} height={180} />}
          </div>
        </div>
      </Section>

      <Section title="Stability (A+B, pessimistic)" description="§10: the edge must be positive in ≥ 70 % of years and of sessions (buckets with ≥ 10 trades).">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <p className="mb-1 text-xs font-medium">By year · {fmtPct(run.stability?.year.score, 0)}</p>
            <BucketTable rows={run.by_year} keyName="year" label="Year" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">By session · {fmtPct(run.stability?.session.score, 0)}</p>
            <BucketTable rows={run.by_session} keyName="session" label="Session" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">By volatility regime</p>
            <BucketTable rows={run.by_vol_regime} keyName="vol_regime" label="Regime" />
          </div>
        </div>
      </Section>

      <Unseal run={run} />
    </div>
  );
}

function Launcher() {
  const params = useSearchParams();
  const [hash, setHash] = useState<string | null>(params.get("spec"));
  const spec = useQuery({ queryKey: ["strategy", hash], queryFn: () => research.strategy(hash!), enabled: !!hash });
  const [ranges, setRanges] = useState<Range[]>([]);
  const job = useJob();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => research.runs() });
  const n = gridSize(ranges);
  const validations = runs.data?.filter((r) => r.kind === "validate") ?? [];
  return (
    <div className="space-y-3">
      <PageHeader title="Validate" subtitle="Does the edge survive honest tests? Tiers A and B, walk-forward, robustness and the §15 checklist." />
      <Section title="1 · Strategy">
        <StrategyPicker value={hash} onChange={(h) => { setHash(h); setRanges([]); }} />
      </Section>
      {spec.data && (
        <Section
          title="2 · Walk-forward (optional re-optimisation)"
          description="Leave empty to test the fixed spec window by window. Add parameters to re-optimise them on each 12-month window and trade only the next 3 months — every variant counts as a trial."
        >
          <ParamGridEditor spec={spec.data.spec} ranges={ranges} onChange={setRanges} />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Button size="sm" disabled={job.busy || n > 400} onClick={() => job.start(() => research.validateJob(spec.data!.spec, toGrid(ranges)))}>
              <ShieldCheck /> Run validation
            </Button>
            <span className="text-xs text-muted-foreground">
              {n ? `${n} variants per window` : "fixed spec"} · takes about 20 s – a few minutes
            </span>
          </div>
          <div className="mt-2">
            <JobProgress job={job.job} error={job.error} />
          </div>
        </Section>
      )}
      <Section title="Previous validations">
        {!validations.length ? (
          <p className="text-xs text-muted-foreground">None yet.</p>
        ) : (
          <ul className="space-y-1 text-xs">
            {validations.map((r) => {
              const s = r.summary as { name: string; verdict: keyof typeof VERDICT; failed: number; expectancy_r: number | null; oos_expectancy_r: number | null };
              return (
                <li key={r.run_id}>
                  <Link className="text-primary hover:underline" href={`/validate?run=${r.run_id}`}>
                    {s.name}
                  </Link>{" "}
                  <span className={cn(s.verdict === "rejected" ? "text-red-400" : s.verdict === "candidate" ? "text-emerald-400" : "text-amber-300")}>
                    {VERDICT[s.verdict]?.label}
                  </span>
                  <span className="text-muted-foreground">
                    {" "}
                    · {s.failed} failed · A+B {fmtR(s.expectancy_r)} · walk-forward {fmtR(s.oos_expectancy_r)} · {r.created_at.slice(0, 16).replace("T", " ")}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </div>
  );
}

function Page() {
  const run = useSearchParams().get("run");
  return <div className="p-3">{run ? <ResultView id={run} /> : <Launcher />}</div>;
}

export default function ValidatePage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <Page />
    </Suspense>
  );
}
