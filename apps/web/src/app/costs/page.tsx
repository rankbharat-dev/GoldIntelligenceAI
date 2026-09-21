"use client";

import { useQuery } from "@tanstack/react-query";

import { LevelChart } from "@/components/costs/level-chart";
import { SpreadHeatmap } from "@/components/costs/spread-heatmap";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchCostModel, type CostModelSummary, type ModelScore, type ScenarioName } from "@/lib/api";

const SCENARIOS: { key: ScenarioName; label: string; hint: string }[] = [
  { key: "optimistic", label: "Optimistic", hint: "p25 · upper bound / sanity" },
  { key: "base", label: "Base", hint: "p50 · headline result" },
  { key: "pessimistic", label: "Pessimistic", hint: "p90 · promotion gate" },
];

const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;
const signedPct = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;

function Row({ label, value, hint }: { label: React.ReactNode; value: React.ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-muted-foreground" title={hint}>
        {label}
      </span>
      <span className="text-right font-mono tabular-nums">{value}</span>
    </div>
  );
}

function ScenarioCard({ m }: { m: CostModelSummary }) {
  const usdPerPoint = m.point * m.contract_size; // USD per point per lot
  const recent = m.summary.mean_spread_points.last_60_days;
  const all = m.summary.mean_spread_points.research_window;
  const ex = m.execution;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Cost scenarios</CardTitle>
        <CardDescription>Mean spread per bar · points and USD per lot round trip</CardDescription>
      </CardHeader>
      <CardContent>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th className="py-1 text-left font-normal">Scenario</th>
              <th className="py-1 text-right font-normal">Last 60 d</th>
              <th className="py-1 text-right font-normal">5-y window</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {SCENARIOS.map((s) => (
              <tr key={s.key} className={s.key === "pessimistic" ? "text-foreground" : ""}>
                <td className="py-1 font-sans" title={s.hint}>
                  {s.label}
                  {s.key === "pessimistic" && (
                    <Badge variant="outline" className="ml-1.5 align-middle text-[10px]">
                      gate
                    </Badge>
                  )}
                </td>
                <td className="py-1 text-right">
                  {recent[s.key].toFixed(0)} <span className="text-muted-foreground">${(recent[s.key] * usdPerPoint).toFixed(2)}</span>
                </td>
                <td className="py-1 text-right">
                  {all[s.key].toFixed(0)} <span className="text-muted-foreground">${(all[s.key] * usdPerPoint).toFixed(2)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Separator className="my-2" />
        <p className="mb-1 text-xs text-muted-foreground">Slippage per fill (points; ATR = M5 ATR(14) at order time)</p>
        {SCENARIOS.map((s) => {
          const sc = ex.scenarios[s.key];
          return (
            <Row
              key={s.key}
              label={s.label}
              value={`mkt ${sc.market.fixed_points}+${pct(sc.market.atr_frac)} · stop ${sc.stop.fixed_points}+${pct(sc.stop.atr_frac)}${sc.window_multiplier > 1 ? ` ×${sc.window_multiplier}` : ""}`}
              hint="Stop slippage is multiplied inside the rollover window (and news windows, once a calendar exists)"
            />
          );
        })}
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{ex.slippage_status}</p>
      </CardContent>
    </Card>
  );
}

function Score({ name, s, chosen }: { name: string; s: ModelScore; chosen: boolean }) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-2 text-xs font-medium">
        {name}
        {chosen && <Badge variant="secondary">chosen</Badge>}
      </div>
      <Row label="Bias of p50" value={signedPct(s.relative_bias_p50)} />
      <Row label="MAE of p50" value={`${s.mae_p50.toFixed(1)} pts`} />
      <Row label="Minutes ≤ p90" value={pct(s.coverage_p90)} />
    </div>
  );
}

function ValidationCard({ m }: { m: CostModelSummary }) {
  const v = m.validation;
  const h = v.abs_cells_on_pre_tick_history;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          Validation
          <Badge variant={v.passed ? "secondary" : "destructive"}>{v.passed ? "Passed" : "FAILED"}</Badge>
        </CardTitle>
        <CardDescription>
          Fit on ticks before {v.calibration_days_before}, predict {v.holdout_minutes.toLocaleString()} unseen minutes
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Score name="Level × ratio" s={v.models.level_x_ratio} chosen={v.chosen_model === "level_x_ratio"} />
        <Separator />
        <Score name="Absolute cells (blueprint literal)" s={v.models.abs_cells} chosen={v.chosen_model === "abs_cells"} />
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          On 2021–2025 history the absolute cells overstate spread by a median {h.median_p50_over_level.toFixed(2)}× and
          predict a typical spread below the broker&apos;s own quoted minimum in {pct(h.share_p50_below_quoted_minimum)} of
          bars. Gate: |bias| ≤ {pct(v.acceptance.max_abs_relative_bias_p50, 0)}, coverage ≥{" "}
          {pct(v.acceptance.min_coverage_p90, 0)}.
        </p>
      </CardContent>
    </Card>
  );
}

const MT5_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function CarryCard({ m }: { m: CostModelSummary }) {
  const { swap, commission } = m.execution;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Swap & commission</CardTitle>
        <CardDescription>From the frozen symbol spec · rollover {swap.rollover}</CardDescription>
      </CardHeader>
      <CardContent>
        <Row label="Long, per lot per night" value={`$${swap.long_usd_per_lot_night.toFixed(2)}`} />
        <Row label="Short, per lot per night" value={`$${swap.short_usd_per_lot_night.toFixed(2)}`} />
        <Row label="Triple swap" value={MT5_DAYS[swap.triple_day_mt5] ?? swap.triple_day_mt5} />
        <Separator className="my-2" />
        <Row label="Commission (round turn / lot)" value={`$${commission.per_lot_round_turn_usd.toFixed(2)}`} />
        {!commission.confirmed && (
          <p className="mt-1 rounded-md bg-amber-500/10 px-2 py-1.5 text-[11px] leading-relaxed text-amber-300">
            ⚠ Not confirmed for this account (open item A4). The pessimistic scenario charges $
            {commission.unconfirmed_pessimistic_usd.toFixed(2)}/lot until it is.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function ModelCard({ m }: { m: CostModelSummary }) {
  const s = m.summary;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Cost model</CardTitle>
        <CardDescription>
          {m.broker} · {m.broker_server}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Row
          label="Tick window"
          value={`${m.tick_window.first_day} → ${m.tick_window.last_day}`}
          hint={`${m.tick_window.tick_days} days`}
        />
        <Row label="Ticks" value={`${(m.tick_window.ticks / 1e6).toFixed(1)} M`} />
        <Row label="Bars measured from ticks" value={pct(s.measured_share)} hint={`${s.measured_bars.toLocaleString()} of ${s.bars.toLocaleString()} M1 bars; the rest are modeled`} />
        <Row label="Abnormal-spread bars" value={s.abnormal_spread_bars.toLocaleString()} hint="Above the p99 of their UTC hour (tier-normalised); excluded from entries later" />
        <Row label="Bars with imputed level" value={s.level_imputed_bars.toLocaleString()} hint="Broker reported spread ≤ 0; previous valid level carried forward" />
        <Row label="Rollover-window bars" value={s.rollover_window_bars.toLocaleString()} />
      </CardContent>
    </Card>
  );
}

function ByYear({ m }: { m: CostModelSummary }) {
  const rows = m.summary.mean_spread_points.by_year;
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Mean spread per M1 bar by year and scenario, points</caption>
      <thead>
        <tr className="text-xs text-muted-foreground">
          <th className="py-1 text-left font-normal">Year</th>
          {SCENARIOS.map((s) => (
            <th key={s.key} className="py-1 text-right font-normal">
              {s.label}
            </th>
          ))}
          <th className="py-1 text-right font-normal">Bars</th>
        </tr>
      </thead>
      <tbody className="font-mono tabular-nums">
        {rows.map((r) => (
          <tr key={r.year} className="border-t border-foreground/5">
            <td className="py-1">{r.year}</td>
            {SCENARIOS.map((s) => (
              <td key={s.key} className="py-1 text-right">
                {r[s.key].toFixed(1)}
              </td>
            ))}
            <td className="py-1 text-right text-muted-foreground">{r.bars.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function CostsPage() {
  const { data: m, isLoading, error } = useQuery({ queryKey: ["cost-model"], queryFn: () => fetchCostModel() });

  return (
    <div className="flex flex-col">
      <div className="px-4 pt-3">
        <h1 className="text-base font-semibold">Data Center · Costs</h1>
        <p className="text-xs text-muted-foreground">Spread, slippage, swap — what an edge must survive</p>
      </div>

      {error && (
        <div className="p-4">
          <Card>
            <CardHeader>
              <CardTitle>Cost model unavailable</CardTitle>
              <CardDescription>
                Build it with <code className="font-mono">ci-costs build</code> and start the API with{" "}
                <code className="font-mono">ci-api</code>. {String(error)}
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      )}

      <main className="grid flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[1fr_360px]">
        <div className="min-w-0 space-y-3">
          <Card size="sm">
            <CardHeader>
              <CardTitle>Spread by hour × weekday</CardTitle>
              <CardDescription>
                Time-weighted from ticks · hours in UTC · empty cells = market closed. On this broker the spread moves in
                tiers set week to week; its time-of-day shape is flat apart from the daily rollover.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SpreadHeatmap />
            </CardContent>
          </Card>

          <Card size="sm">
            <CardHeader>
              <CardTitle>Spread level since 2021</CardTitle>
              <CardDescription>
                Each M1 bar&apos;s spread equals the minimum quoted in that minute (verified against ticks), so it anchors
                the modeled spread for years without ticks.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LevelChart />
            </CardContent>
          </Card>

          <Card size="sm">
            <CardHeader>
              <CardTitle>Mean spread by year</CardTitle>
              <CardDescription>
                Points per M1 bar. Pessimistic never drops below the recent tier, so cheap past years cannot flatter a
                strategy that would pay today&apos;s spread.
              </CardDescription>
            </CardHeader>
            <CardContent>{m ? <ByYear m={m} /> : <Skeleton className="h-40 w-full" />}</CardContent>
          </Card>
        </div>

        <aside className="space-y-3">
          {isLoading &&
            [0, 1, 2].map((i) => <Skeleton key={i} className="h-44 w-full" />)}
          {m && (
            <>
              <ModelCard m={m} />
              <ScenarioCard m={m} />
              <ValidationCard m={m} />
              <CarryCard m={m} />
              <p className="px-1 text-[11px] leading-relaxed text-muted-foreground">
                {m.cost_model_id} · {m.model_version} · config {m.config_hash} · code{" "}
                {m.code_version.git_commit?.slice(0, 7) ?? "?"}
                {m.code_version.dirty ? " (uncommitted changes)" : ""}
              </p>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}
