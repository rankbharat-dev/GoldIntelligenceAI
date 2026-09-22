"use client";

import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { CandleChart, type ChartMarker } from "@/components/candle-chart";
import { BucketTable, Notice, PageHeader, Section, Stat, toneOf } from "@/components/research/bits";
import { EquityChart, SCENARIO_COLOR } from "@/components/research/equity-chart";
import { JobProgress, useJob } from "@/components/research/jobs";
import { StrategyPicker } from "@/components/research/strategy-picker";
import { TradeReplay } from "@/components/replay/trade-replay";
import { Button } from "@/components/ui/button";
import {
  fmtDate,
  fmtInt,
  fmtNum,
  fmtPct,
  fmtR,
  research,
  type BacktestRun,
  type Metrics,
  type Scenario,
  type Trade,
} from "@/lib/research";
import { cn } from "@/lib/utils";

const SCENARIOS: Scenario[] = ["optimistic", "base", "pessimistic"];
const DAY = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ScenarioToggle({ value, onChange }: { value: Scenario; onChange: (s: Scenario) => void }) {
  return (
    <div className="flex gap-1">
      {SCENARIOS.map((s) => (
        <button
          key={s}
          onClick={() => onChange(s)}
          aria-pressed={value === s}
          className={cn(
            "rounded-md border px-2 py-0.5 text-xs capitalize",
            value === s ? "border-primary/60 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

const ROWS: { label: string; get: (m: Metrics) => string; tone?: (m: Metrics) => number | null | undefined }[] = [
  { label: "Trades", get: (m) => fmtInt(m.n) },
  { label: "Expectancy / trade", get: (m) => fmtR(m.expectancy_r), tone: (m) => m.expectancy_r },
  { label: "…before costs", get: (m) => fmtR(m.expectancy_before_costs_r), tone: (m) => m.expectancy_before_costs_r },
  { label: "Win rate", get: (m) => fmtPct(m.win_rate) },
  { label: "Profit factor", get: (m) => fmtNum(m.profit_factor) },
  { label: "Total", get: (m) => (m.total_r == null ? "—" : `${m.total_r.toFixed(1)} R`), tone: (m) => m.total_r },
  { label: "Max drawdown", get: (m) => (m.max_dd_r == null ? "—" : `${m.max_dd_r.toFixed(1)} R · ${fmtPct(m.max_dd_pct)}`) },
  { label: "Final equity", get: (m) => (m.final_equity_usd == null ? "—" : `$${Math.round(m.final_equity_usd).toLocaleString()}`) },
  { label: "Sharpe / trade", get: (m) => fmtNum(m.sharpe_per_trade, 3) },
  { label: "Avg hold", get: (m) => (m.avg_hold_minutes == null ? "—" : `${Math.round(m.avg_hold_minutes)} min`) },
];

function CostBars({ run }: { run: BacktestRun }) {
  const parts = ["spread", "slippage", "commission", "swap"] as const;
  const max = Math.max(...SCENARIOS.map((s) => parts.reduce((a, p) => a + Math.max(run.results[s].costs_r?.[p] ?? 0, 0), 0)), 0.001);
  const shade: Record<(typeof parts)[number], string> = {
    spread: "#e0b04a",
    slippage: "#b3862f",
    commission: "#7d6128",
    swap: "#4d3f22",
  };
  return (
    <div className="space-y-2">
      {SCENARIOS.map((s) => {
        const c = run.results[s].costs_r;
        if (!c) return null;
        const total = parts.reduce((a, p) => a + c[p], 0);
        return (
          <div key={s} className="space-y-1">
            <div className="flex text-xs">
              <span className="capitalize">{s}</span>
              <span className="ml-auto font-mono text-muted-foreground">{total.toFixed(3)} R / trade</span>
            </div>
            <div className="flex h-3 overflow-hidden rounded bg-muted">
              {parts.map((p) => (
                <div key={p} title={`${p}: ${c[p].toFixed(3)} R`} style={{ width: `${(Math.max(c[p], 0) / max) * 100}%`, background: shade[p] }} />
              ))}
            </div>
          </div>
        );
      })}
      <div className="flex flex-wrap gap-3 pt-1 text-[11px] text-muted-foreground">
        {parts.map((p) => (
          <span key={p} className="flex items-center gap-1">
            <span className="size-2 rounded-sm" style={{ background: shade[p] }} /> {p}
          </span>
        ))}
      </div>
    </div>
  );
}

function MonthStrip({ rows }: { rows: { month?: string | number | null; total_r: number | null }[] }) {
  if (!rows?.length) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r.total_r ?? 0)), 0.001);
  return (
    <div>
      <div className="flex h-20 items-center gap-px">
        {rows.map((r) => {
          const v = r.total_r ?? 0;
          const h = (Math.abs(v) / max) * 50;
          return (
            <div key={String(r.month)} className="relative flex h-full flex-1 flex-col justify-center" title={`${r.month}: ${v.toFixed(1)} R`}>
              <div
                className={cn("w-full", v >= 0 ? "self-end bg-emerald-500/70" : "bg-red-500/70")}
                style={{ height: `${h}%`, marginTop: v >= 0 ? "auto" : "50%", marginBottom: v >= 0 ? "50%" : "auto" }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{String(rows[0].month)}</span>
        <span>{String(rows[rows.length - 1].month)}</span>
      </div>
    </div>
  );
}

function Trades({ run }: { run: BacktestRun }) {
  const [scenario, setScenario] = useState<Scenario>("pessimistic");
  const [page, setPage] = useState(0);
  const [pick, setPick] = useState<Trade | null>(null);
  const size = 100;
  const q = useQuery({
    queryKey: ["trades", run.run_id, scenario, page],
    queryFn: () => research.trades(run.run_id, scenario, page * size, size),
  });
  const markers = useMemo<ChartMarker[]>(() => {
    if (!pick) return [];
    const long = pick.side > 0;
    return [
      { time: pick.entry_time, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: "#e0b04a", text: `${long ? "buy" : "sell"} ${pick.entry_price.toFixed(2)}` },
      {
        time: pick.exit_time,
        position: long ? "aboveBar" : "belowBar",
        shape: "circle",
        color: pick.r_net >= 0 ? "#34d399" : "#f87171",
        text: `${pick.exit_reason} ${pick.r_net >= 0 ? "+" : ""}${pick.r_net.toFixed(2)}R`,
      },
    ];
  }, [pick]);
  const pages = q.data ? Math.ceil(q.data.total / size) : 0;
  const tz = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", year: "2-digit", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  return (
    <Section
      title="Trades"
      description="Click a trade to replay it on the M1 chart (times in IST). Entry and exit prices include spread and slippage."
      actions={<ScenarioToggle value={scenario} onChange={(s) => { setScenario(s); setPage(0); }} />}
    >
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="max-h-[420px] overflow-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left font-normal">Entry (IST)</th>
                <th className="px-2 py-1 text-left font-normal">Side</th>
                <th className="px-2 py-1 text-left font-normal">Exit</th>
                <th className="px-2 py-1 text-right font-normal">R</th>
                <th className="px-2 py-1 text-right font-normal">USD</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {q.data?.trades.map((t) => (
                <tr
                  key={`${t.entry_time}-${t.side}`}
                  onClick={() => setPick(t)}
                  className={cn("cursor-pointer border-t border-border/60 hover:bg-muted/50", pick?.entry_time === t.entry_time && "bg-primary/10")}
                >
                  <td className="px-2 py-1">{tz.format(new Date(t.entry_time * 1000))}</td>
                  <td className={cn("px-2 py-1 font-sans", t.side > 0 ? "text-emerald-400" : "text-red-400")}>{t.side > 0 ? "long" : "short"}</td>
                  <td className="px-2 py-1 font-sans text-muted-foreground">
                    {t.exit_reason}
                    {t.ambiguous && <span className="text-amber-400"> ·amb</span>}
                  </td>
                  <td className={cn("px-2 py-1 text-right", t.r_net >= 0 ? "text-emerald-400" : "text-red-400")}>{t.r_net.toFixed(2)}</td>
                  <td className="px-2 py-1 text-right">{Math.round(t.pnl_usd).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {q.data && (
            <div className="flex items-center gap-2 border-t px-2 py-1 text-[11px] text-muted-foreground">
              {q.data.total.toLocaleString()} trades
              <span className="ml-auto" />
              <Button size="xs" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Prev
              </Button>
              {page + 1} / {pages || 1}
              <Button size="xs" variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </div>
          )}
        </div>
        <div className="relative h-[420px] overflow-hidden rounded-lg border">
          {pick ? (
            <CandleChart key={pick.entry_time} timeframe="M1" zone="Asia/Kolkata" markers={markers} anchor={pick.entry_time} />
          ) : (
            <p className="p-3 text-xs text-muted-foreground">Pick a trade on the left to see it on the chart.</p>
          )}
        </div>
      </div>
      {pick && (
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          entry {pick.entry_price.toFixed(3)} · stop {pick.stop_initial.toFixed(3)} · target {pick.target?.toFixed(3) ?? "—"} · exit{" "}
          {pick.exit_price.toFixed(3)} · MFE {pick.mfe_r.toFixed(2)} R · MAE {pick.mae_r.toFixed(2)} R · before costs {pick.r_before_costs.toFixed(2)} R ·{" "}
          {pick.lots} lots · held {pick.bars_held_m1} min · {pick.session} / {pick.vol_regime}
        </p>
      )}
    </Section>
  );
}

function RunView({ id }: { id: string }) {
  const { data: run, error, isLoading } = useQuery({ queryKey: ["run", id], queryFn: () => research.run<BacktestRun>(id) });
  const [scenario, setScenario] = useState<Scenario>("pessimistic");
  const curves = useMemo(
    () =>
      run
        ? SCENARIOS.filter((s) => run.results[s].equity?.time.length).map((s) => ({
            name: s,
            color: SCENARIO_COLOR[s],
            time: run.results[s].equity!.time,
            value: run.results[s].equity!.cum_r,
          }))
        : [],
    [run],
  );
  if (error) return <Notice tone="error">{String(error)}</Notice>;
  if (isLoading || !run) return <p className="text-xs text-muted-foreground">Loading run…</p>;
  if (run.kind !== "backtest") return <Notice>This run is a {(run as { kind: string }).kind}; open it from its own page.</Notice>;

  const p = run.results.pessimistic;
  const m = run.results[scenario];
  const dsr = run.deflated_sharpe;
  const rb = run.robustness;
  return (
    <div className="space-y-3">
      <PageHeader
        title={`${run.name} · tier ${run.tier === "AB" ? "A+B" : run.tier}`}
        subtitle={`${run.family} · ${run.spec_hash} · ${fmtDate(run.tier_bounds_utc[0])} → ${fmtDate(run.tier_bounds_utc[1])} · run ${run.run_id}`}
      >
        <div className="flex flex-wrap gap-2 text-xs">
          <Link className="text-primary hover:underline" href={`/strategy-lab?spec=${run.spec_hash}`}>Edit in builder</Link>
          <Link className="text-primary hover:underline" href={`/optimize?spec=${run.spec_hash}`}>Optimize</Link>
          <Link className="text-primary hover:underline" href={`/validate?spec=${run.spec_hash}`}>Validate</Link>
        </div>
      </PageHeader>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Expectancy · pessimistic" value={fmtR(p.expectancy_r)} tone={toneOf(p.expectancy_r)} hint="the promotion gate" />
        <Stat label="Trades" value={fmtInt(p.n)} hint={`${fmtInt(run.signals)} signals`} />
        <Stat label="Profit factor" value={fmtNum(p.profit_factor)} />
        <Stat label="Max drawdown" value={p.max_dd_r == null ? "—" : `${p.max_dd_r.toFixed(1)} R`} hint={fmtPct(p.max_dd_pct)} />
        <Stat label="Family trials" value={fmtInt(run.family_trials)} hint="variants tried in this family" />
        <Stat
          label="Deflated Sharpe"
          value={dsr ? (dsr.deflated_excess > 0 ? "above bar" : "below bar") : "—"}
          tone={dsr ? (dsr.deflated_excess > 0 ? "good" : "bad") : "muted"}
          hint={dsr ? `P = ${fmtPct(dsr.probability)} at ${dsr.n_trials} trials` : undefined}
        />
      </div>

      {p.n > 0 && p.expectancy_r != null && p.expectancy_r <= 0 && (
        <Notice tone="warn">
          After pessimistic costs this strategy loses {fmtR(p.expectancy_r)} per trade. Before costs it made{" "}
          {fmtR(p.expectancy_before_costs_r)} — costs of {fmtR((p.expectancy_before_costs_r ?? 0) - p.expectancy_r)} per trade decide the outcome.
        </Notice>
      )}

      {p.ruined_at && (
        <Notice tone="error">
          With {run.spec.sizing.risk_pct}% risk per trade the simulated ${run.spec.sizing.initial_equity_usd.toLocaleString()} account
          hit zero on {fmtDate(p.ruined_at)} (pessimistic). The R results cover every trade; the USD path stops there.
        </Notice>
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Section title="Equity in R, three cost scenarios" description="Pessimistic (gold) is the one that counts for promotion.">
          <EquityChart curves={curves} />
        </Section>
        <Section title="Scenarios side by side" description="Same signals, different spread, slippage and commission.">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-normal" />
                  {SCENARIOS.map((s) => (
                    <th key={s} className="py-1 text-right font-normal capitalize" style={{ color: SCENARIO_COLOR[s] }}>
                      {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {ROWS.map((r) => (
                  <tr key={r.label} className="border-t border-border/60">
                    <td className="py-1 font-sans text-muted-foreground">{r.label}</td>
                    {SCENARIOS.map((s) => {
                      const t = r.tone?.(run.results[s]);
                      return (
                        <td key={s} className={cn("py-1 text-right", t != null && (t > 0 ? "text-emerald-400" : t < 0 ? "text-red-400" : ""))}>
                          {r.get(run.results[s])}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Section title="What the costs take" description="Average cost per trade in R, by component.">
          <CostBars run={run} />
          <p className="mt-2 text-[11px] text-muted-foreground">
            Spread measured from ticks on {fmtPct(p.measured_spread_share)} of trades (rest modeled). Commission in pessimistic
            is the unconfirmed raw-account charge (A4).
          </p>
        </Section>
        <Section title="Is it luck?" description="Honesty checks on the pessimistic trades.">
          <div className="space-y-1.5 text-xs">
            <p>
              95 % bootstrap range of expectancy:{" "}
              <b className="font-mono">
                {fmtR(rb.bootstrap_expectancy_ci.low)} … {fmtR(rb.bootstrap_expectancy_ci.high)}
              </b>
            </p>
            <p>
              Drawdown if the same trades came in another order: median{" "}
              <b className="font-mono">{fmtNum(rb.monte_carlo_drawdown_r.p50, 1)} R</b>, bad case (95 %){" "}
              <b className="font-mono">{fmtNum(rb.monte_carlo_drawdown_r.p95, 1)} R</b>
            </p>
            <p>
              Deflated Sharpe: per-trade Sharpe <b className="font-mono">{fmtNum(dsr?.sharpe_per_trade, 4)}</b> vs the best
              expected from {dsr?.n_trials ?? "?"} lucky tries <b className="font-mono">{fmtNum(dsr?.sr0_expected_max, 4)}</b>
            </p>
            <p>
              Intrabar ambiguity: <b className="font-mono">{fmtPct(p.ambiguity_rate, 2)}</b> of trades (limit 5 %)
            </p>
          </div>
        </Section>
        <Section title="How much cost can it take?" description="Extra spread every trade could pay before the edge is gone.">
          <div className="space-y-1.5 text-xs">
            <p>
              Break-even extra spread:{" "}
              <b className="font-mono">{rb.cost_stress.breakeven_extra_spread_points == null ? "—" : `${rb.cost_stress.breakeven_extra_spread_points} pts`}</b>
            </p>
            <p>
              …or extra commission: <b className="font-mono">{rb.cost_stress.breakeven_extra_commission_usd_per_lot == null ? "—" : `$${rb.cost_stress.breakeven_extra_commission_usd_per_lot} / lot`}</b>
            </p>
            <table className="w-full font-mono tabular-nums">
              <tbody>
                {rb.cost_stress.spread_points?.map((x) => (
                  <tr key={x.extra} className="border-t border-border/60">
                    <td className="py-0.5 font-sans text-muted-foreground">+{x.extra} pts</td>
                    <td className={cn("py-0.5 text-right", x.expectancy_r > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(x.expectancy_r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-muted-foreground">Negative already at +0 means pessimistic costs alone kill it.</p>
          </div>
        </Section>
      </div>

      <Section title="Where it works and where it doesn't" description="The same trades grouped several ways. An edge in one year or one session is not an edge in gold." actions={<ScenarioToggle value={scenario} onChange={setScenario} />}>
        <div className="mb-3">
          <p className="mb-1 text-xs text-muted-foreground">Total R by month</p>
          <MonthStrip rows={m.by_month ?? []} />
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div>
            <p className="mb-1 text-xs font-medium">
              By year · positive in {fmtPct(m.stability?.year.score, 0)}
            </p>
            <BucketTable rows={m.by_year ?? []} keyName="year" label="Year" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">
              By session · positive in {fmtPct(m.stability?.session.score, 0)}
            </p>
            <BucketTable rows={m.by_session ?? []} keyName="session" label="Session" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">By volatility regime</p>
            <BucketTable rows={m.by_vol_regime ?? []} keyName="vol_regime" label="Regime" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">By weekday</p>
            <BucketTable rows={(m.by_weekday ?? []).map((r) => ({ ...r, weekday: DAY[Number(r.weekday)] ?? r.weekday }))} keyName="weekday" label="Day" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">By side</p>
            <BucketTable rows={m.by_side ?? []} keyName="side" label="Side" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium">Exit reasons</p>
            <table className="w-full text-xs">
              <tbody className="font-mono">
                {Object.entries(m.exit_reasons ?? {}).map(([k, v]) => (
                  <tr key={k} className="border-t border-border/60">
                    <td className="py-1 font-sans">{k}</td>
                    <td className="py-1 text-right">{v.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      <Trades run={run} />

      <Section
        title="Trade replay · rule check"
        description="Pessimistic trades on the chart with entry / SL / TP zones, the engine's stored indicators, bar-by-bar replay, and each entry condition + filter evaluated on the decision bar (POST /api/strategy/explain)."
      >
        <TradeReplay run={run} />
      </Section>

      <p className="px-1 text-[11px] text-muted-foreground">
        {run.lineage.dataset_id} · {run.lineage.cost_model_id} · {run.lineage.feature_set_id} · code{" "}
        {run.lineage.code_version.git_commit?.slice(0, 7) ?? "?"}
        {run.lineage.code_version.dirty ? " (uncommitted)" : ""} · ambiguity policy {run.ambiguity_policy}
      </p>
    </div>
  );
}

function Launcher() {
  const params = useSearchParams();
  const router = useRouter();
  const [hash, setHash] = useState<string | null>(params.get("spec"));
  const spec = useQuery({ queryKey: ["strategy", hash], queryFn: () => research.strategy(hash!), enabled: !!hash });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => research.runs() });
  const job = useJob();
  const backtests = runs.data?.filter((r) => r.kind === "backtest") ?? [];
  return (
    <div className="space-y-3">
      <PageHeader title="Backtest" subtitle="Event-driven: decisions at M5 close, fills on the M1 path, three cost scenarios, every run counted." />
      <Section title="Run a backtest" description="Tier A = development (2021–2024), B = validation (2024–2025). Tier C stays sealed until Validate.">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-64 flex-1">
            <StrategyPicker value={hash} onChange={setHash} />
          </div>
          {(["A", "B", "AB"] as const).map((t) => (
            <Button key={t} size="sm" disabled={!spec.data || job.busy} onClick={() => job.start(() => research.backtest(spec.data!.spec, t))}>
              <Play /> Tier {t === "AB" ? "A+B" : t}
            </Button>
          ))}
        </div>
        <div className="mt-2">
          <JobProgress job={job.job} error={job.error} />
        </div>
      </Section>
      <Section title="Recent backtests" description="Pessimistic headline of each run.">
        {!backtests.length ? (
          <p className="text-xs text-muted-foreground">No backtests yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-normal">When</th>
                  <th className="py-1 text-left font-normal">Strategy</th>
                  <th className="py-1 text-left font-normal">Tier</th>
                  <th className="py-1 text-right font-normal">Trades</th>
                  <th className="py-1 text-right font-normal">Expectancy</th>
                  <th className="py-1 text-right font-normal">PF</th>
                  <th className="py-1 text-right font-normal">Trials</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {backtests.map((r) => {
                  const s = r.summary as { name: string; n: number; expectancy_r: number | null; profit_factor: number | null; family_trials: number };
                  return (
                    <tr key={r.run_id} className="cursor-pointer border-t border-border/60 hover:bg-muted/50" onClick={() => router.push(`/backtest?run=${r.run_id}`)}>
                      <td className="py-1">{r.created_at.slice(0, 16).replace("T", " ")}</td>
                      <td className="py-1 font-sans">{s.name}</td>
                      <td className="py-1">{r.tier}</td>
                      <td className="py-1 text-right">{fmtInt(s.n)}</td>
                      <td className={cn("py-1 text-right", (s.expectancy_r ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(s.expectancy_r)}</td>
                      <td className="py-1 text-right">{fmtNum(s.profit_factor)}</td>
                      <td className="py-1 text-right">{s.family_trials}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

function Page() {
  const params = useSearchParams();
  const run = params.get("run");
  return <div className="p-3">{run ? <RunView id={run} /> : <Launcher />}</div>;
}

export default function BacktestPage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <Page />
    </Suspense>
  );
}
