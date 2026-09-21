"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, FlaskConical, Library, Play } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { CandleChart, type ChartMarker } from "@/components/candle-chart";
import { Field, inputCls, Notice, NumberInput, PageHeader, Section, Stat, toneOf } from "@/components/research/bits";
import { ConditionChips, ConditionList, toBuilderDraft } from "@/components/research/conditions";
import { JobProgress, useJob } from "@/components/research/jobs";
import { Button } from "@/components/ui/button";
import {
  explore,
  fmtInt,
  fmtNum,
  fmtPct,
  fmtR,
  research,
  type Barriers,
  type Condition,
  type Distribution,
  type Pattern,
  type ScreenRun,
  type Side,
  type StudyBucket,
  type StudyRun,
} from "@/lib/research";
import { cn } from "@/lib/utils";

// Behaviour = dataviz slot 1 (blue). Text stays in ink colours.
const BEHAVIOUR = "#3987e5";
const LABEL_COLOR: Record<number, string> = { 1: "#34d399", [-1]: "#f87171", 0: "#a1a1aa" };
const DEFAULT_BARRIERS: Barriers = { target_atr: 1.5, stop_atr: 1.0, horizon_bars: 24 };

type Tab = "library" | "study" | "distributions";

function ExplorerInner() {
  const params = useSearchParams();
  const router = useRouter();
  const runId = params.get("run");
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) ?? "library");

  return (
    <div className="space-y-3 p-3">
      <PageHeader
        title="Behaviour Explorer"
        subtitle="What does gold do after a candle pattern or a structure event? Measured with real fills and costs, tiers A and B only — C stays sealed."
      >
        <div className="flex gap-1">
          {(
            [
              ["library", "Pre-registered library", Library],
              ["study", "Event study", FlaskConical],
              ["distributions", "Distributions", BarChart3],
            ] as const
          ).map(([t, label, Icon]) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                if (runId) router.push(`/explorer?tab=${t}`);
              }}
              aria-pressed={tab === t && !runId}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs",
                tab === t && !runId ? "border-primary/60 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          ))}
        </div>
      </PageHeader>
      {runId ? <RunView runId={runId} /> : tab === "library" ? <LibraryTab /> : tab === "study" ? <StudyTab /> : <DistributionsTab />}
    </div>
  );
}

// ---------------------------------------------------------------- library

function LibraryTab() {
  const lib = useQuery({ queryKey: ["behaviours"], queryFn: explore.behaviours });
  const job = useJob();
  if (lib.isError) return <Notice tone="error">Behaviour library unavailable: {String(lib.error)}</Notice>;
  if (!lib.data) return <p className="text-xs text-muted-foreground">Loading the library…</p>;
  const groups = lib.data.groups;
  return (
    <div className="space-y-3">
      <Notice>
        Each behaviour below was <b>written down before its results were computed</b> (blueprint §9.2): exact conditions,
        direction, triple-barrier exit (target {DEFAULT_BARRIERS.target_atr} ATR · stop {DEFAULT_BARRIERS.stop_atr} ATR ·
        {DEFAULT_BARRIERS.horizon_bars} bars), and the sample it needs (≥ {lib.data.min_samples.A} in A, ≥ {lib.data.min_samples.B} in B).
        Rule version <span className="font-mono">{lib.data.rule_version}</span>. Changing a rule creates a new version, never an edit.
      </Notice>
      <Section
        title="Screen every behaviour"
        description="Runs all registered behaviours on one tier and corrects for testing many at once (Benjamini–Hochberg, q = 10 %). Before costs asks “does it predict anything?”; after pessimistic costs asks “can it be traded?”."
        actions={
          <div className="flex gap-2">
            <Button size="sm" disabled={job.busy} onClick={() => job.start(() => explore.screen("A"))}>
              <Play /> Screen tier A
            </Button>
            <Button size="sm" variant="outline" disabled={job.busy} onClick={() => job.start(() => explore.screen("B"))}>
              <Play /> Screen tier B
            </Button>
          </div>
        }
      >
        <JobProgress job={job.job} error={job.error} />
        {lib.data.screens.length > 0 ? (
          <ul className="mt-1 space-y-0.5 text-xs">
            {lib.data.screens.map((s) => (
              <li key={s.run_id}>
                <Link className="text-primary hover:underline" href={`/explorer?run=${s.run_id}`}>
                  Tier {s.tier} · {new Date(s.created_at).toLocaleString()}
                </Link>{" "}
                <span className="text-muted-foreground">
                  · {String(s.summary.behaviours)} behaviours · discoveries before costs {String(s.summary.discoveries_gross)}, after costs{" "}
                  {String(s.summary.discoveries_net)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">No screen yet.</p>
        )}
      </Section>
      <Section title={`Library · ${lib.data.patterns.length} registered behaviours`} description="Click Study to run one behaviour on a tier and open its full report.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-xs">
            <thead className="text-muted-foreground">
              <tr className="text-left">
                <th className="py-1 pr-2 font-normal">Behaviour</th>
                <th className="py-1 pr-2 font-normal">Rule</th>
                <th className="py-1 pr-2 font-normal">Registered</th>
                <th className="py-1 pr-2 text-right font-normal">Tier A: n · hit · net R</th>
                <th className="py-1 pr-2 text-right font-normal">Tier B: n · hit · net R</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody>
              {lib.data.patterns.map((p) => (
                <PatternRow key={p.pattern_id} p={p} group={groups[p.behaviour] ?? p.behaviour} busy={job.busy} start={job.start} />
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

function latestCell(x: Pattern["latest"]["A"]) {
  if (!x) return <span className="text-muted-foreground">—</span>;
  const net = x.mean_r_net as number | null;
  return (
    <Link href={`/explorer?run=${x.run_id}`} className="font-mono hover:underline">
      {fmtInt(x.n as number)} · {fmtPct(x.target_rate as number, 0)} ·{" "}
      <span className={net == null ? "" : net > 0 ? "text-emerald-400" : "text-red-400"}>{fmtR(net, 2)}</span>
    </Link>
  );
}

function SideBadge({ side }: { side: Side }) {
  return (
    <span className={cn("rounded px-1 text-[10px] font-semibold uppercase", side === "long" ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300")}>
      {side}
    </span>
  );
}

function PatternRow({ p, group, busy, start }: { p: Pattern; group: string; busy: boolean; start: ReturnType<typeof useJob>["start"] }) {
  return (
    <tr className="border-t border-border/60 align-top">
      <td className="py-1.5 pr-2">
        <p className="font-medium">
          {p.name} <SideBadge side={p.definition.side} />
        </p>
        <p className="text-[11px] text-muted-foreground">
          {group} · <span className="font-mono">{p.pattern_id}</span>
        </p>
      </td>
      <td className="max-w-[320px] py-1.5 pr-2">
        <ConditionChips conditions={p.definition.conditions} />
      </td>
      <td className="py-1.5 pr-2 font-mono text-[11px] text-muted-foreground">{new Date(p.registered_at).toISOString().slice(0, 16).replace("T", " ")}</td>
      <td className="py-1.5 pr-2 text-right">{latestCell(p.latest.A)}</td>
      <td className="py-1.5 pr-2 text-right">{latestCell(p.latest.B)}</td>
      <td className="py-1.5 text-right whitespace-nowrap">
        <Button size="xs" variant="outline" disabled={busy} onClick={() => start(() => explore.study({ pattern_id: p.pattern_id, tier: "A" }))}>
          Study A
        </Button>{" "}
        <Button size="xs" variant="outline" disabled={busy} onClick={() => start(() => explore.study({ pattern_id: p.pattern_id, tier: "B" }))}>
          Study B
        </Button>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------- ad-hoc study

function StudyTab() {
  const catalogue = useQuery({ queryKey: ["catalogue"], queryFn: research.catalogue, staleTime: Infinity });
  const [name, setName] = useState("My behaviour");
  const [side, setSide] = useState<Side>("long");
  const [conds, setConds] = useState<Condition[]>([
    { feature: "sweep_low", op: "==", value: true },
    { feature: "close_loc", op: ">=", value: 0.6 },
  ]);
  const [b, setB] = useState<Barriers>(DEFAULT_BARRIERS);
  const job = useJob();
  if (!catalogue.data) return <p className="text-xs text-muted-foreground">Loading features…</p>;
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Section title="Describe the behaviour" description="All conditions must hold on the bar's close. Structure features (swings, S/R, trendlines, sweeps) are in the “Market structure” group.">
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <Field label="Name">
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Expected move">
              <div className="flex gap-1">
                {(["long", "short"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={side === s}
                    onClick={() => setSide(s)}
                    className={cn(
                      "h-8 rounded-md border px-3 text-xs",
                      side === s ? (s === "long" ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-300" : "border-red-500/60 bg-red-500/15 text-red-300") : "text-muted-foreground",
                    )}
                  >
                    {s === "long" ? "up (long)" : "down (short)"}
                  </button>
                ))}
              </div>
            </Field>
          </div>
          <ConditionList conditions={conds} onChange={setConds} catalogue={catalogue.data} />
          <div className="grid grid-cols-3 gap-2">
            <Field label="Target (× ATR)">
              <NumberInput value={b.target_atr} min={0.1} onChange={(v) => setB({ ...b, target_atr: v ?? 1.5 })} />
            </Field>
            <Field label="Stop (× ATR)">
              <NumberInput value={b.stop_atr} min={0.1} onChange={(v) => setB({ ...b, stop_atr: v ?? 1 })} />
            </Field>
            <Field label="Horizon (M5 bars)">
              <NumberInput value={b.horizon_bars} step={1} min={1} onChange={(v) => setB({ ...b, horizon_bars: Math.round(v ?? 24) })} />
            </Field>
          </div>
        </div>
      </Section>
      <aside className="space-y-3">
        <Section title="Run" description="Ad-hoc studies use tier A only and are marked exploratory. Pre-register a behaviour (from its report) to test it on tier B.">
          <Button size="sm" disabled={job.busy} onClick={() => job.start(() => explore.study({ name, side, conditions: conds, barriers: b, tier: "A" }))}>
            <Play /> Study on tier A
          </Button>
          <div className="mt-2">
            <JobProgress job={job.job} error={job.error} />
          </div>
        </Section>
        <Notice>
          <b>How to read a study.</b> Every time the pattern appears we pretend to enter at the next minute with the real
          spread, and see what is hit first: the target, the stop or the time limit. We compare with the same test on
          every bar (the baseline). If the pattern is not better than the baseline <i>before</i> costs, it carries no
          information; if it is only better before costs, it is real but too small to trade.
        </Notice>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- run views

function RunView({ runId }: { runId: string }) {
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => research.run(runId) as unknown as Promise<StudyRun | ScreenRun> });
  if (run.isError) return <Notice tone="error">Unknown run {runId}.</Notice>;
  if (!run.data) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const doc = run.data;
  return doc.kind === "screen" ? <ScreenView run={doc} /> : <StudyView run={doc} />;
}

function Pct({ x, base }: { x: number | null | undefined; base?: number | null }) {
  return (
    <span className="font-mono">
      {fmtPct(x, 1)}
      {base != null && <span className="text-muted-foreground"> vs {fmtPct(base, 1)}</span>}
    </span>
  );
}

function StudyView({ run }: { run: StudyRun }) {
  const p = run.scenarios.pessimistic;
  const o = run.scenarios.optimistic;
  const base = run.baseline;
  const lift = run.lift_vs_baseline;
  const markers = useMemo<ChartMarker[]>(
    () =>
      run.markers.event_time.map((t, i) => {
        const up = run.definition.side === "long";
        return {
          time: t,
          position: up ? "belowBar" : "aboveBar",
          shape: up ? "arrowUp" : "arrowDown",
          color: LABEL_COLOR[run.markers.label[i]] ?? "#a1a1aa",
        };
      }),
    [run],
  );
  const anchor = run.markers.event_time.length ? run.markers.event_time[run.markers.event_time.length - 1] : null;
  const verdict = verdictOf(run);
  return (
    <div className="space-y-3">
      <Section
        title={`${run.name} · tier ${run.tier}`}
        description={
          <>
            <SideBadge side={run.definition.side} /> <ConditionChips conditions={run.definition.conditions} /> · target {run.definition.barriers.target_atr} ATR · stop{" "}
            {run.definition.barriers.stop_atr} ATR · {run.definition.barriers.horizon_bars} bars ·{" "}
            {run.registered ? <span className="text-primary">pre-registered {run.pattern_id}</span> : <span className="text-amber-300">exploratory (not registered)</span>}
          </>
        }
      >
        <div className={cn("mb-3 rounded-lg border px-3 py-2 text-xs", verdict.tone)}>{verdict.text}</div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <Stat label="Occurrences" value={fmtInt(run.occurrences)} hint={`${fmtPct(run.occurrences / Math.max(run.bars_in_tier, 1), 2)} of bars · need ≥ ${run.sample.min}`} tone={run.sample.sufficient ? undefined : "bad"} />
          <Stat label="Target hit first" value={fmtPct(p.target_rate, 1)} hint={`baseline ${fmtPct(base.target_rate, 1)} · lift ${lift ? fmtPct(lift.target_rate, 1) : "—"}`} tone={toneOf(lift?.target_rate)} />
          <Stat label="Avg R before costs" value={fmtR(p.mean_r_gross)} hint={`baseline ${fmtR(base.mean_r_gross)}`} tone={toneOf(p.mean_r_gross)} />
          <Stat label="Avg R after costs (pess.)" value={fmtR(p.mean_r_net)} hint={`base scenario ${fmtR(run.scenarios.base.mean_r_net)}`} tone={toneOf(p.mean_r_net)} />
          <Stat
            label="Chance it is luck (before costs)"
            value={run.gross.bootstrap.p_mean_le_0 == null ? "—" : fmtPct(run.gross.bootstrap.p_mean_le_0, 1)}
            hint="bootstrap p (one-sided)"
          />
          <Stat label="95 % range, R after costs" value={`${fmtNum(run.net.bootstrap.low, 3)} … ${fmtNum(run.net.bootstrap.high, 3)}`} hint="stationary bootstrap" />
        </div>
      </Section>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <Section title="Outcome by cost scenario" description="Same occurrences, three cost levels. Only pessimistic can promote.">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-normal">Scenario</th>
                <th className="py-1 text-right font-normal">Target</th>
                <th className="py-1 text-right font-normal">Stop</th>
                <th className="py-1 text-right font-normal">Time</th>
                <th className="py-1 text-right font-normal">Avg R net</th>
                <th className="py-1 text-right font-normal">MFE / MAE</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {(["optimistic", "base", "pessimistic"] as const).map((s) => {
                const x = run.scenarios[s];
                return (
                  <tr key={s} className="border-t border-border/60">
                    <td className="py-1 font-sans">{s}</td>
                    <td className="py-1 text-right">{fmtPct(x.target_rate, 1)}</td>
                    <td className="py-1 text-right">{fmtPct(x.stop_rate, 1)}</td>
                    <td className="py-1 text-right">{fmtPct(x.time_rate, 1)}</td>
                    <td className={cn("py-1 text-right", (x.mean_r_net ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(x.mean_r_net)}</td>
                    <td className="py-1 text-right">
                      {fmtNum(x.mfe_r, 2)} / {fmtNum(x.mae_r, 2)}
                    </td>
                  </tr>
                );
              })}
              <tr className="border-t border-border/60 text-muted-foreground">
                <td className="py-1 font-sans">baseline (pess.)</td>
                <td className="py-1 text-right">{fmtPct(base.target_rate, 1)}</td>
                <td className="py-1 text-right">{fmtPct(base.stop_rate, 1)}</td>
                <td className="py-1 text-right">{fmtPct(base.time_rate, 1)}</td>
                <td className="py-1 text-right">{fmtR(base.mean_r_net)}</td>
                <td className="py-1 text-right">
                  {fmtNum(base.mfe_r, 2)} / {fmtNum(base.mae_r, 2)}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted-foreground">
            MFE / MAE = best and worst move while the trade was open, in R. Optimistic-cost R here: {fmtR(o.mean_r_net)}.
          </p>
        </Section>
        <Section title="Fixed-horizon move (diagnostic only)" description="Average move in the expected direction after n bars, in ATR, and how often it was positive. Not tradeable as such (§8.2).">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-normal">After</th>
                <th className="py-1 text-right font-normal">Avg move (ATR)</th>
                <th className="py-1 text-right font-normal">Positive</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {Object.entries(run.forward_returns_atr).map(([n, v]) => (
                <tr key={n} className="border-t border-border/60">
                  <td className="py-1 font-sans">{n} bars ({Number(n) * 5} min)</td>
                  <td className={cn("py-1 text-right", (v.mean_atr ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtNum(v.mean_atr, 3)}</td>
                  <td className="py-1 text-right">{fmtPct(v.hit_rate, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        {(
          [
            ["By year", run.by_year, "year"],
            ["By session", run.by_session, "session"],
            ["By volatility regime", run.by_vol_regime, "vol_regime"],
          ] as const
        ).map(([title, rows, key]) => (
          <Section key={title} title={title} description="Avg R before costs per bucket (buckets under 30 occurrences are greyed).">
            <BucketBars rows={rows} keyName={key} />
          </Section>
        ))}
      </div>

      <Section title="Where it happened" description="Latest occurrences (M5). Green = target first, red = stop first, grey = time limit.">
        <div className="relative h-[360px] overflow-hidden rounded-lg border">
          {anchor != null ? <CandleChart timeframe="M5" zone="Asia/Kolkata" markers={markers} anchor={anchor} /> : <p className="p-3 text-xs text-muted-foreground">No occurrences.</p>}
        </div>
      </Section>

      <NextSteps run={run} />
    </div>
  );
}

function verdictOf(run: StudyRun): { text: string; tone: string } {
  const p = run.scenarios.pessimistic;
  const pg = run.gross.bootstrap.p_mean_le_0;
  if (!run.sample.sufficient) {
    return { text: `Too few occurrences (${run.occurrences} < ${run.sample.min}): ${run.sample.consequence}.`, tone: "border-amber-500/40 bg-amber-500/5 text-amber-200" };
  }
  if ((p.mean_r_net ?? -1) > 0 && pg != null && pg < 0.05) {
    return { text: "Positive after pessimistic costs and unlikely to be luck on this tier. Next: pre-register (if not yet), check tier B, then build it as a strategy and Validate.", tone: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200" };
  }
  if ((p.mean_r_gross ?? 0) > 0 && pg != null && pg < 0.05) {
    return { text: "The pattern carries information before costs, but costs eat it. Ideas: wider targets/stops (costs become a smaller share of 1 R), a filter that keeps only the strongest cases, or a Raw-account cost profile (Phase 9).", tone: "border-dashed text-muted-foreground" };
  }
  return { text: "No edge: after the pattern, price does about what it does after any bar. That is a useful answer — this idea can be dropped.", tone: "border-dashed text-muted-foreground" };
}

function BucketBars({ rows, keyName }: { rows: StudyBucket[]; keyName: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!rows?.length) return <p className="text-xs text-muted-foreground">No occurrences.</p>;
  const max = Math.max(0.05, ...rows.map((r) => Math.abs(r.mean_r_gross ?? 0)));
  return (
    <div className="space-y-1">
      {rows.map((r, i) => {
        const v = r.mean_r_gross ?? 0;
        const w = (Math.abs(v) / max) * 50;
        return (
          <div
            key={String(r[keyName])}
            className={cn("grid grid-cols-[88px_1fr_110px] items-center gap-2 text-xs", !r.scored && "opacity-45")}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="truncate">{String(r[keyName])}</span>
            <span className="relative h-3.5">
              <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
              <span
                className="absolute inset-y-0.5 rounded-sm"
                style={{ background: BEHAVIOUR, width: `${w}%`, left: v >= 0 ? "50%" : `${50 - w}%` }}
              />
            </span>
            <span className="text-right font-mono tabular-nums text-muted-foreground">
              {hover === i ? `n ${r.n} · net ${fmtNum(r.mean_r_net, 2)}` : `${fmtR(r.mean_r_gross, 3)}`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function NextSteps({ run }: { run: StudyRun }) {
  const router = useRouter();
  const [slug, setSlug] = useState(run.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "my_behaviour");
  const [hyp, setHyp] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Section title="Next steps">
      <div className="grid gap-3 md:grid-cols-2">
        {run.exploratory ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Pre-register it to test it on tier B. You write the hypothesis now; the rule is frozen as it is.
            </p>
            <Field label="Id (lowercase_with_underscores)">
              <input className={inputCls} value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} />
            </Field>
            <Field label="Hypothesis">
              <textarea className={cn(inputCls, "h-14 py-1.5")} value={hyp} onChange={(e) => setHyp(e.target.value)} placeholder="Why should this move price?" />
            </Field>
            <Button
              size="sm"
              variant="outline"
              disabled={hyp.trim().length < 10 || slug.length < 3}
              onClick={async () => {
                try {
                  const p = await explore.register({ slug, name: run.name, side: run.definition.side, conditions: run.definition.conditions, hypothesis: hyp, barriers: run.definition.barriers });
                  setMsg(`Registered as ${p.pattern_id}. Study it on tier B from the library.`);
                } catch (e) {
                  setMsg(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              Pre-register
            </Button>
            {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Registered behaviour <span className="font-mono">{run.pattern_id}</span>. Its tier A and B studies are in the library.</p>
        )}
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Turn it into a strategy: the same conditions and exits open in the Visual Builder for review. A backtest there is
            one position at a time and counts as a trial on its family.
          </p>
          <Button
            size="sm"
            onClick={() => {
              toBuilderDraft(run.name, run.definition.side, run.definition.conditions, run.definition.barriers, run.registered ? `Pre-registered behaviour ${run.pattern_id}` : "");
              router.push("/strategy-lab");
            }}
          >
            Open in Strategy Lab
          </Button>
        </div>
      </div>
    </Section>
  );
}

function ScreenView({ run }: { run: ScreenRun }) {
  const rows = [...run.rows].sort((a, b) => (a.p_gross ?? 1) - (b.p_gross ?? 1));
  return (
    <div className="space-y-3">
      <Section
        title={`${run.name}`}
        description={`All pre-registered behaviours on tier ${run.tier}, corrected for testing ${run.rows.length} at once (Benjamini–Hochberg, q = ${run.fdr_q * 100} %). A ✓ discovery survives that correction.`}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-xs">
            <thead className="text-muted-foreground">
              <tr className="text-left">
                <th className="py-1 pr-2 font-normal">Behaviour</th>
                <th className="py-1 pr-2 text-right font-normal">n</th>
                <th className="py-1 pr-2 text-right font-normal">Target hit (vs all bars)</th>
                <th className="py-1 pr-2 text-right font-normal">R before costs</th>
                <th className="py-1 pr-2 text-right font-normal">q before costs</th>
                <th className="py-1 pr-2 text-right font-normal">R after costs (pess.)</th>
                <th className="py-1 pr-2 text-right font-normal">q after costs</th>
                <th className="py-1 text-right font-normal">Years / sessions positive</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {rows.map((r) => (
                <tr key={r.pattern_id} className="border-t border-border/60">
                  <td className="py-1 pr-2 font-sans">
                    {r.name} <SideBadge side={r.side} />
                  </td>
                  <td className={cn("py-1 pr-2 text-right", !r.sufficient && "text-amber-300")} title={r.sufficient ? "" : "below the §11 minimum"}>
                    {fmtInt(r.n)}
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <Pct x={r.target_rate} base={r.baseline_target_rate} />
                  </td>
                  <td className={cn("py-1 pr-2 text-right", (r.mean_r_gross ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(r.mean_r_gross)}</td>
                  <td className="py-1 pr-2 text-right">
                    {fmtNum(r.q_gross, 3)} {r.discovery_gross && <span className="text-emerald-400">✓</span>}
                  </td>
                  <td className={cn("py-1 pr-2 text-right", (r.mean_r_net ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(r.mean_r_net)}</td>
                  <td className="py-1 pr-2 text-right">
                    {fmtNum(r.q_net, 3)} {r.discovery_net && <span className="text-emerald-400">✓</span>}
                  </td>
                  <td className="py-1 text-right">
                    {fmtPct(r.stability_year, 0)} / {fmtPct(r.stability_session, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Notice>
        Read it like this: “R before costs” says whether gold behaves differently after the pattern at all; “R after
        costs” says whether that difference pays for the spread, slippage and commission. A behaviour worth building on
        needs a ✓ before costs and enough occurrences; a ✓ after costs is rare on M5 gold.
      </Notice>
    </div>
  );
}

// ---------------------------------------------------------------- distributions

function DistributionsTab() {
  const catalogue = useQuery({ queryKey: ["catalogue"], queryFn: research.catalogue, staleTime: Infinity });
  const [feature, setFeature] = useState("sweep_depth_atr");
  const [by, setBy] = useState("year");
  const dist = useQuery({ queryKey: ["dist", feature, by], queryFn: () => explore.distribution(feature, by), retry: false });
  const groups = catalogue.data ? Object.entries(catalogue.data.groups) : [];
  return (
    <div className="space-y-3">
      <Section title="Feature distribution" description="How a feature is distributed over tiers A and B, split by year, session, volatility regime or tier — does it behave the same in every period?">
        <div className="grid gap-2 sm:grid-cols-[1fr_200px]">
          <Field label="Feature">
            <select className={inputCls} value={feature} onChange={(e) => setFeature(e.target.value)}>
              {groups.map(([g, label]) => (
                <optgroup key={g} label={label}>
                  {catalogue.data!.features
                    .filter((f) => f.group === g)
                    .map((f) => (
                      <option key={f.name} value={f.name}>
                        {f.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </Field>
          <Field label="Split by">
            <select className={inputCls} value={by} onChange={(e) => setBy(e.target.value)}>
              {["none", "year", "session", "vol_regime", "tier"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </Field>
        </div>
        {dist.data && <p className="mt-2 text-xs text-muted-foreground">{dist.data.spec.description} · unit {dist.data.spec.unit}</p>}
      </Section>
      {dist.isError && <Notice tone="error">{String(dist.error)}</Notice>}
      {dist.data && (dist.data.numeric ? <NumericDist d={dist.data} /> : <CategoricalDist d={dist.data} />)}
    </div>
  );
}

function NumericDist({ d }: { d: Distribution }) {
  const edges = d.edges ?? [];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {d.groups.map((g) => (
          <Section key={g.group} title={g.group} description={`${fmtInt(g.n)} bars · median ${fmtNum(g.p50, 3)} · mean ${fmtNum(g.mean, 3)}`}>
            <Histogram hist={g.hist ?? []} edges={edges} />
          </Section>
        ))}
      </div>
      <Section title="Quantiles" description="Share-free summary of each group (values, not counts).">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                {["Group", "n", "empty", "p10", "p25", "median", "p75", "p90", "mean"].map((h) => (
                  <th key={h} className={cn("py-1 font-normal", h === "Group" ? "text-left" : "text-right")}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {d.groups.map((g) => (
                <tr key={g.group} className="border-t border-border/60">
                  <td className="py-1 font-sans">{g.group}</td>
                  <td className="py-1 text-right">{fmtInt(g.n)}</td>
                  <td className="py-1 text-right">{fmtInt(g.nulls)}</td>
                  {[g.p10, g.p25, g.p50, g.p75, g.p90, g.mean].map((v, i) => (
                    <td key={i} className="py-1 text-right">
                      {fmtNum(v, 3)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

function Histogram({ hist, edges }: { hist: number[]; edges: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = hist.reduce((a, b) => a + b, 0) || 1;
  const max = Math.max(1, ...hist);
  return (
    <div>
      <div className="flex h-28 items-end gap-[2px]" onMouseLeave={() => setHover(null)}>
        {hist.map((h, i) => (
          <div key={i} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(i)}>
            <div
              className="w-full rounded-t-[3px]"
              style={{ height: `${(h / max) * 100}%`, minHeight: h ? 2 : 0, background: hover === i ? "#6aa6f0" : BEHAVIOUR }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-muted-foreground">
        <span>{fmtNum(edges[0], 2)}</span>
        <span>
          {hover != null
            ? `${fmtNum(edges[hover], 2)} … ${fmtNum(edges[hover + 1], 2)}: ${fmtInt(hist[hover])} (${fmtPct(hist[hover] / total, 1)})`
            : "hover a bar"}
        </span>
        <span>{fmtNum(edges[edges.length - 1], 2)}</span>
      </div>
    </div>
  );
}

function CategoricalDist({ d }: { d: Distribution }) {
  const cats = d.categories ?? [];
  return (
    <Section title="Shares by group" description="Share of bars with each value, per group (bar length = share).">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 text-left font-normal">Group</th>
              <th className="py-1 text-right font-normal">n</th>
              {cats.map((c) => (
                <th key={c} className="py-1 text-right font-normal">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {d.groups.map((g) => (
              <tr key={g.group} className="border-t border-border/60">
                <td className="py-1 font-sans">{g.group}</td>
                <td className="py-1 text-right">{fmtInt(g.n)}</td>
                {cats.map((c) => {
                  const v = g.shares?.[c] ?? null;
                  return (
                    <td key={c} className="py-1 text-right">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="inline-block h-2 rounded-sm" style={{ width: `${Math.round((v ?? 0) * 48)}px`, background: BEHAVIOUR }} />
                        {fmtPct(v, 1)}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Values are shares within each group; a flag that is true on 7 % of bars in one year and 2 % in another means the market (or the broker data) changed.
      </p>
    </Section>
  );
}

export default function ExplorerPage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <ExplorerInner />
    </Suspense>
  );
}
