"use client";

import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { inputCls, Notice, PageHeader, Section, Stat, toneOf } from "@/components/research/bits";
import { JobProgress, useJob } from "@/components/research/jobs";
import { Button } from "@/components/ui/button";
import { fmtInt, fmtNum, fmtPct, fmtR, ml, research, type MLRun, type MLSide } from "@/lib/research";
import { cn } from "@/lib/utils";

function MLInner() {
  const params = useSearchParams();
  const runId = params.get("run");
  const lib = useQuery({ queryKey: ["strategies"], queryFn: research.strategies });
  const hist = useQuery({ queryKey: ["ml-runs"], queryFn: ml.runs });
  const [pick, setPick] = useState("");
  const job = useJob();
  const chosen = lib.data?.find((s) => s.spec_hash === pick);
  return (
    <div className="space-y-3 p-3">
      <PageHeader
        title="ML Lab"
        subtitle="Can a model trained on tier A choose which signals of a rule to take, so the rule does better on unseen tier B? LightGBM vs the rule itself."
      />
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-3">{runId ? <MLView id={runId} /> : <HowItWorks />}</div>
        <aside className="space-y-3">
          <Section title="Train a filter" description="Pick a saved strategy. Its tier-A signals are labelled with its own exits at pessimistic costs; the filter is judged on tier B.">
            <select className={inputCls} value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Strategy">
              <option value="">choose a strategy…</option>
              {lib.data?.map((s) => (
                <option key={s.spec_hash} value={s.spec_hash}>
                  {s.name} · {s.family}
                </option>
              ))}
            </select>
            <Button size="sm" className="mt-2" disabled={!chosen || job.busy} onClick={() => chosen && job.start(() => ml.run(chosen.spec))}>
              <Play /> Train & test
            </Button>
            <p className="mt-1.5 text-[11px] text-muted-foreground">Counts as one trial on the strategy&apos;s family. Tier C is never used.</p>
            <div className="mt-2">
              <JobProgress job={job.job} error={job.error} />
            </div>
          </Section>
          <Section title="Earlier filters">
            {!hist.data?.length && <p className="text-xs text-muted-foreground">None yet.</p>}
            <ul className="space-y-1 text-xs">
              {hist.data?.map((r) => (
                <li key={r.run_id}>
                  <Link className="hover:underline" href={`/ml?run=${r.run_id}`}>
                    {String(r.summary.name)}
                  </Link>{" "}
                  <span className={r.summary.verdict === "helps" ? "text-emerald-300" : "text-muted-foreground"}>· {String(r.summary.verdict)}</span>
                </li>
              ))}
            </ul>
          </Section>
        </aside>
      </div>
    </div>
  );
}

function HowItWorks() {
  return (
    <Notice>
      <b>How the ML Lab stays honest.</b> The model sees only what was known at each signal&apos;s bar close. It trains on tier A;
      its probability cut-off is chosen from predictions on A made by models that never saw those months (time-ordered folds
      with a one-day gap). Then the rule and the filtered rule both run on tier B through the real backtester. The filter
      “helps” only if it beats the rule there by ≥ 0.02 R with ≥ 100 trades and a confidence range above the rule —
      otherwise the report says “not helping”, which is a result too.
    </Notice>
  );
}

function Side({ title, s }: { title: string; s: MLSide }) {
  return (
    <div className="rounded-lg border p-2.5">
      <p className="mb-1.5 text-xs font-medium">{title}</p>
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Trades" value={fmtInt(s.n)} />
        <Stat label="Avg R (pess.)" value={fmtR(s.expectancy_r)} tone={toneOf(s.expectancy_r)} />
        <Stat label="Profit factor" value={fmtNum(s.profit_factor)} />
        <Stat label="95 % range" value={`${fmtNum(s.bootstrap?.low, 3)} … ${fmtNum(s.bootstrap?.high, 3)}`} />
      </div>
    </div>
  );
}

function MLView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["run", id], queryFn: () => research.run(id) as unknown as Promise<MLRun> });
  if (q.isError) return <Notice tone="error">Unknown run {id}.</Notice>;
  if (!q.data) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const d = q.data;
  const helps = d.verdict === "helps";
  const maxGain = Math.max(1, ...d.importance.map((i) => i.gain));
  return (
    <>
      <Section title={`${d.name} · ML filter`} description={`family ${d.family} · ${d.family_trials} trials on the family`}>
        <div className={cn("mb-3 rounded-lg border px-3 py-2 text-xs", helps ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-200" : "border-dashed text-muted-foreground")}>
          {helps ? (
            <>
              ✓ The filter beats the rule on unseen tier B.
              {(d.test.filtered.expectancy_r ?? 0) <= 0 && (
                <span className="text-amber-200"> But the filtered strategy still loses after pessimistic costs — better, not tradeable.</span>
              )}
            </>
          ) : (
            <>
              ✗ Not helping on tier B: {d.reasons.join("; ")}.
            </>
          )}
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Side title="Rule alone (tier B)" s={d.test.baseline} />
          <Side title="Rule + ML filter (tier B)" s={d.test.filtered} />
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Change in average R on B: <b className="font-mono">{fmtR(d.test.delta_r)}</b> · trained on {fmtInt(d.train.signals)} tier-A signals (
          {fmtPct(d.train.positive_share, 0)} profitable after costs) · out-of-fold AUC {fmtNum(d.train.oof_auc, 3)} (0.5 = no skill) · cut-off{" "}
          {fmtNum(d.threshold.threshold, 3)}
        </p>
      </Section>
      <Section title="What the model looked at" description="Top features by gain. A filter leaning on one feature is a hint for a simpler rule.">
        <div className="space-y-1">
          {d.importance.map((i) => (
            <div key={i.feature} className="grid grid-cols-[150px_1fr_70px] items-center gap-2 text-xs">
              <span className="truncate font-mono">{i.feature}</span>
              <span className="h-2.5 rounded-sm" style={{ width: `${(i.gain / maxGain) * 100}%`, background: "#3987e5" }} />
              <span className="text-right font-mono text-muted-foreground">{i.gain.toFixed(0)}</span>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Cut-off choice on tier A (out-of-fold)">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 text-left font-normal">Keep top</th>
              <th className="py-1 text-right font-normal">Probability ≥</th>
              <th className="py-1 text-right font-normal">Signals kept</th>
              <th className="py-1 text-right font-normal">Avg R (pess.)</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {d.threshold.table.map((r) => (
              <tr key={r.quantile} className={cn("border-t border-border/60", r.threshold === d.threshold.threshold && "text-primary")}>
                <td className="py-1 font-sans">{fmtPct(1 - r.quantile, 0)}</td>
                <td className="py-1 text-right">{r.threshold.toFixed(3)}</td>
                <td className="py-1 text-right">{fmtInt(r.kept)}</td>
                <td className="py-1 text-right">{fmtR(r.expectancy_r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </>
  );
}

export default function MLPage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <MLInner />
    </Suspense>
  );
}
