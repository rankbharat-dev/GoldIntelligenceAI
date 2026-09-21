"use client";

import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { Notice, PageHeader, Section, Stat, toneOf } from "@/components/research/bits";
import { JobProgress, useJob } from "@/components/research/jobs";
import { gridSize, ParamGridEditor, toGrid, type Range } from "@/components/research/param-grid";
import { StrategyPicker } from "@/components/research/strategy-picker";
import { Button } from "@/components/ui/button";
import { fmtInt, fmtNum, fmtPct, fmtR, research, type OptimizeRow, type OptimizeRun, type StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

function Heatmap({ run }: { run: OptimizeRun }) {
  const o = run.optimize;
  if (o.params.length !== 2) return null;
  const [px, py] = o.params;
  const cell = new Map(o.table.map((r) => [`${r.params[px.path]}|${r.params[py.path]}`, r]));
  const vals = o.table.map((r) => r.expectancy_r).filter((v): v is number => v != null);
  const max = Math.max(...vals.map(Math.abs), 0.001);
  // diverging: red below zero, green above, neutral at zero
  const colour = (v: number | null | undefined, enough: boolean) => {
    if (v == null || !enough) return "transparent";
    const a = Math.min(Math.abs(v) / max, 1) * 0.85 + 0.1;
    return v >= 0 ? `rgba(52, 211, 153, ${a})` : `rgba(248, 113, 113, ${a})`;
  };
  return (
    <div className="overflow-x-auto">
      <table className="text-[11px]">
        <thead>
          <tr>
            <th className="p-1 text-left font-normal text-muted-foreground">
              {py.path.split(".").slice(-1)[0]} ↓ / {px.path.split(".").slice(-1)[0]} →
            </th>
            {px.values.map((x) => (
              <th key={String(x)} className="p-1 font-mono font-normal text-muted-foreground">
                {x}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {py.values.map((y) => (
            <tr key={String(y)}>
              <th className="p-1 text-right font-mono font-normal text-muted-foreground">{y}</th>
              {px.values.map((x) => {
                const r = cell.get(`${x}|${y}`);
                const enough = (r?.n ?? 0) >= o.min_trades;
                const best = o.best && r && r.spec_hash === o.best.spec_hash;
                return (
                  <td
                    key={String(x)}
                    title={r ? `${fmtR(r.expectancy_r)} · ${r.n} trades` : ""}
                    className={cn("h-8 min-w-12 border border-background p-1 text-center font-mono", best && "ring-2 ring-primary")}
                    style={{ background: colour(r?.expectancy_r, enough) }}
                  >
                    {r?.expectancy_r == null ? "—" : r.expectancy_r.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultView({ id }: { id: string }) {
  const { data: run, error } = useQuery({ queryKey: ["run", id], queryFn: () => research.run<OptimizeRun>(id) });
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const sorted = useMemo(
    () => [...(run?.optimize.table ?? [])].sort((a, b) => (b.expectancy_r ?? -99) - (a.expectancy_r ?? -99)),
    [run],
  );
  if (error) return <Notice tone="error">{String(error)}</Notice>;
  if (!run) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const o = run.optimize;
  const best = o.best;
  const dsr = o.best_deflated_sharpe;

  const openBest = async (row: OptimizeRow) => {
    setSaving(true);
    const spec = JSON.parse(JSON.stringify(run.spec)) as StrategySpec & Record<string, unknown>;
    for (const [path, v] of Object.entries(row.params)) {
      const parts = path.split(".");
      let d: Record<string, unknown> | unknown[] = spec;
      for (const k of parts.slice(0, -1)) d = (Array.isArray(d) ? d[Number(k)] : d[k]) as Record<string, unknown>;
      const last = parts[parts.length - 1];
      if (Array.isArray(d)) d[Number(last)] = v;
      else d[last] = v;
    }
    const r = await research.save(spec, run.spec_hash);
    router.push(`/strategy-lab?spec=${r.spec_hash}`);
  };

  return (
    <div className="space-y-3">
      <PageHeader title={`Optimize · ${run.name}`} subtitle={`${o.variants} variants on tier A · pessimistic costs · run ${run.run_id}`}>
        <Link className="text-xs text-primary hover:underline" href={`/optimize?spec=${run.spec_hash}`}>
          New search
        </Link>
      </PageHeader>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Best expectancy (A)" value={fmtR(best?.expectancy_r)} tone={toneOf(best?.expectancy_r)} hint={best ? `${fmtInt(best.n)} trades` : "no variant had enough trades"} />
        <Stat
          label="Plateau or spike?"
          value={o.plateau?.verdict ?? "—"}
          tone={o.plateau?.verdict === "plateau" ? "good" : o.plateau?.verdict === "spike" ? "bad" : "muted"}
          hint={o.plateau?.ratio != null ? `neighbours keep ${fmtPct(o.plateau.ratio, 0)} of it` : undefined}
        />
        <Stat label="Family trials now" value={fmtInt(o.family_trials)} hint="every variant counted" />
        <Stat
          label="Best vs luck (Deflated Sharpe)"
          value={dsr ? (dsr.deflated_excess > 0 ? "above bar" : "below bar") : "—"}
          tone={dsr ? (dsr.deflated_excess > 0 ? "good" : "bad") : "muted"}
          hint={dsr ? `P = ${fmtPct(dsr.probability)}` : undefined}
        />
      </div>
      <Notice>
        The best cell of a grid is the luckiest of {o.variants} tries on the same data — that is why the trial count went up
        and why the winner must still pass <b>Validate</b> (tier B, walk-forward, costs). A <b>plateau</b> (neighbours almost
        as good) is a better sign than a lone <b>spike</b>.
      </Notice>
      {o.params.length === 2 && (
        <Section title="Sensitivity map" description={`Expectancy per variant (pessimistic). Blank = fewer than ${o.min_trades} trades. Gold border = best.`}>
          <Heatmap run={run} />
        </Section>
      )}
      <Section title="All variants" description="Sorted by pessimistic expectancy on tier A.">
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                {o.params.map((p) => (
                  <th key={p.path} className="py-1 pr-2 text-left font-normal">
                    {p.path.replace("entries.", "rule ").replace(".conditions.", " cond ")}
                  </th>
                ))}
                <th className="py-1 pr-2 text-right font-normal">Trades</th>
                <th className="py-1 pr-2 text-right font-normal">Expectancy</th>
                <th className="py-1 pr-2 text-right font-normal">PF</th>
                <th className="py-1 pr-2 text-right font-normal">Max DD</th>
                <th className="py-1 text-right font-normal" />
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {sorted.map((r, i) => (
                <tr key={i} className="border-t border-border/60">
                  {o.params.map((p) => (
                    <td key={p.path} className="py-1 pr-2">
                      {String(r.params[p.path])}
                    </td>
                  ))}
                  {r.invalid ? (
                    <td colSpan={5} className="py-1 font-sans text-muted-foreground">
                      invalid: {r.invalid}
                    </td>
                  ) : (
                    <>
                      <td className={cn("py-1 pr-2 text-right", (r.n ?? 0) < o.min_trades && "text-muted-foreground")}>{fmtInt(r.n)}</td>
                      <td className={cn("py-1 pr-2 text-right", (r.expectancy_r ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(r.expectancy_r)}</td>
                      <td className="py-1 pr-2 text-right">{fmtNum(r.profit_factor)}</td>
                      <td className="py-1 pr-2 text-right">{r.max_dd_r == null ? "—" : `${r.max_dd_r.toFixed(1)} R`}</td>
                      <td className="py-1 text-right font-sans">
                        <Button size="xs" variant="ghost" disabled={saving} onClick={() => void openBest(r)}>
                          Open
                        </Button>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
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
  const grid = toGrid(ranges);
  const total = gridSize(ranges);
  const optimizations = runs.data?.filter((r) => r.kind === "optimize") ?? [];

  return (
    <div className="space-y-3">
      <PageHeader title="Optimize" subtitle="Search parameters on tier A only; every variant is counted as a trial on the family." />
      <Section title="1 · Strategy">
        <StrategyPicker value={hash} onChange={(h) => { setHash(h); setRanges([]); }} />
      </Section>
      {spec.data && (
        <Section
          title="2 · Parameters to vary"
          description="Up to 3 at once, at most 400 variants. Two parameters give a sensitivity map."
        >
          <div className="space-y-2">
            <ParamGridEditor spec={spec.data.spec} ranges={ranges} onChange={setRanges} />
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <Button size="sm" disabled={!ranges.length || total < 2 || total > 400 || job.busy} onClick={() => job.start(() => research.optimize(spec.data!.spec, grid))}>
                <Play /> Run {total || 0} variants
              </Button>
              <span className={cn("text-xs", total > 400 ? "text-red-400" : "text-muted-foreground")}>
                {grid.map((g) => g.values.length).join(" × ") || "—"} = {total} variants · adds up to {total} trials to “{spec.data.family}” (now {spec.data.family_trials})
              </span>
            </div>
            <JobProgress job={job.job} error={job.error} />
          </div>
        </Section>
      )}
      <Section title="Previous searches">
        {!optimizations.length ? (
          <p className="text-xs text-muted-foreground">None yet.</p>
        ) : (
          <ul className="space-y-1 text-xs">
            {optimizations.map((r) => {
              const s = r.summary as { name: string; variants: number; expectancy_r: number | null; plateau: string | null };
              return (
                <li key={r.run_id}>
                  <Link className="text-primary hover:underline" href={`/optimize?run=${r.run_id}`}>
                    {s.name}
                  </Link>{" "}
                  <span className="text-muted-foreground">
                    · {s.variants} variants · best {fmtR(s.expectancy_r)} · {s.plateau ?? "—"} · {r.created_at.slice(0, 16).replace("T", " ")}
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

export default function OptimizePage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <Page />
    </Suspense>
  );
}
