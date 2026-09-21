"use client";

import { useQuery } from "@tanstack/react-query";

import type { DisplayZone } from "@/components/candle-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchFeatureBar,
  fetchFeatureSet,
  type FeatureSpec,
  type FeatureValue,
  type Timeframe,
} from "@/lib/api";

// Groups open by default; the rest are one click away.
const OPEN_GROUPS = new Set(["anatomy", "sequence", "volatility", "session"]);
const NO_ENTRY_FLAGS: Record<string, string> = {
  hyg_rollover: "Rollover window",
  hyg_abnormal_spread: "Abnormal spread",
  hyg_week_first3: "First 3 bars of week",
  hyg_week_last3: "Last 3 bars of week",
};
const INFO_FLAGS: Record<string, string> = {
  hyg_weekend_gap: "After weekend gap",
  hyg_spans_weekend_gap: "Lookback spans weekend",
  hyg_incomplete: "Incomplete bar",
};
const TIMING: Record<string, string> = {
  bar_close: "known at this bar's close",
  bar_open: "known at this bar's open (previous bars only)",
  calendar: "known in advance (clock / calendar)",
  htf_close: "from the last closed higher-timeframe bar",
};

function formatter(zone: DisplayZone) {
  const f = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour12: false,
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (t: number) => f.format(new Date(t * 1000));
}

function formatValue(v: FeatureValue, spec: FeatureSpec): React.ReactNode {
  if (v === null || v === undefined) return <span className="text-muted-foreground">—</span>;
  if (typeof v === "boolean") {
    const warn = spec.group === "hygiene";
    return v ? <span className={warn ? "text-amber-400" : "text-foreground"}>yes</span> : <span className="text-muted-foreground">no</span>;
  }
  if (typeof v === "string") return v;
  switch (spec.unit) {
    case "sign":
      return v > 0 ? <span className="text-emerald-400">▲ up</span> : v < 0 ? <span className="text-red-400">▼ down</span> : "flat";
    case "frac":
      return v.toFixed(2);
    case "atr": {
      // Sizes (ranges, wicks) are never negative; only directional values get a sign.
      const size = /range|wick|dist_(high|low)20/.test(spec.name);
      return `${v > 0 && !size ? "+" : ""}${v.toFixed(2)} ATR`;
    }
    case "pts":
      return `${Math.round(v).toLocaleString()} pts`;
    case "x":
      return `${v.toFixed(2)}×`;
    case "bps":
      return `${v.toFixed(1)} bps`;
    case "min": {
      const h = Math.floor(v / 60);
      return h ? `${h} h ${v % 60} m` : `${v} m`;
    }
    case "bars":
      return `${v > 0 && spec.name.includes("streak") ? "+" : ""}${v}`;
    default:
      return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(3);
  }
}

function Row({ spec, value }: { spec: FeatureSpec; value: FeatureValue }) {
  return (
    <div
      className="flex items-baseline justify-between gap-3 py-0.5 text-xs"
      title={`${spec.description}\n${spec.name} · ${TIMING[spec.timing] ?? spec.timing}`}
    >
      <span className="truncate text-muted-foreground">{spec.name}</span>
      <span className="shrink-0 text-right font-mono tabular-nums">{formatValue(value, spec)}</span>
    </div>
  );
}

export function FeaturesPanel({
  time,
  tf,
  zone,
  onClear,
}: {
  time: number;
  tf: Timeframe;
  zone: DisplayZone;
  onClear: () => void;
}) {
  const set = useQuery({ queryKey: ["feature-set"], queryFn: () => fetchFeatureSet() });
  const bar = useQuery({ queryKey: ["feature-bar", time, tf], queryFn: () => fetchFeatureBar(time, tf) });
  const fmt = formatter(zone);

  if (set.isLoading || bar.isLoading) return <Skeleton className="h-96 w-full" />;
  if (set.error || bar.error || !set.data || !bar.data) {
    return (
      <Card size="sm">
        <CardHeader>
          <CardTitle>Features unavailable</CardTitle>
          <CardDescription>
            {String(set.error ?? bar.error ?? "")}. Build them with <code className="font-mono">ci-features build</code>.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const s = set.data;
  const b = bar.data;
  const noEntry = Object.keys(NO_ENTRY_FLAGS).filter((k) => b.values[k] === true);
  const info = Object.keys(INFO_FLAGS).filter((k) => b.values[k] === true);
  const byGroup = Object.keys(s.groups).map((g) => ({ g, specs: s.schema.filter((f) => f.group === g) }));
  const check = s.leakage_selfcheck.passed;

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          M5 bar features
          <button
            type="button"
            onClick={onClear}
            className="rounded px-1.5 text-xs font-normal text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close features"
          >
            ✕
          </button>
        </CardTitle>
        <CardDescription className="space-y-0.5">
          <span className="block font-mono text-foreground">{fmt(b.meta.event_time)}</span>
          <span className="block">
            available at {fmt(b.meta.available_at).slice(-5)} (bar close) · trading day {b.meta.trading_day}
          </span>
          {b.mapped && (
            <span className="block text-amber-400">
              You clicked a {b.tf} bar — showing the M5 bar {b.tf === "M1" ? "containing that minute" : "that closes with it"}.
            </span>
          )}
          {!b.in_research_window && <span className="block text-amber-400">Before the research window.</span>}
        </CardDescription>
        <div className="flex flex-wrap gap-1 pt-1">
          {noEntry.length === 0 ? (
            <Badge variant="secondary">Entry allowed (§5.3)</Badge>
          ) : (
            noEntry.map((k) => (
              <Badge key={k} variant="destructive">
                No entry · {NO_ENTRY_FLAGS[k]}
              </Badge>
            ))
          )}
          {info.map((k) => (
            <Badge key={k} variant="outline">
              {INFO_FLAGS[k]}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        {byGroup.map(({ g, specs }) => (
          <details key={g} open={OPEN_GROUPS.has(g)} className="group">
            <summary className="cursor-pointer select-none py-1 text-xs font-medium">
              {s.groups[g]} <span className="font-normal text-muted-foreground">· {specs.length}</span>
            </summary>
            <div className="pb-1 pl-2">
              {g === "h1" || g === "m15" ? (
                <p className="pb-0.5 text-[11px] text-muted-foreground">
                  from the {g.toUpperCase()} bar that closed{" "}
                  {fmt((g === "h1" ? b.meta.h1_close_utc : b.meta.m15_close_utc) ?? 0).slice(-5)}
                </p>
              ) : null}
              {specs.map((f) => (
                <Row key={f.name} spec={f} value={b.values[f.name]} />
              ))}
            </div>
          </details>
        ))}

        {b.costs && (
          <>
            <Separator className="my-2" />
            <details>
              <summary className="cursor-pointer select-none py-1 text-xs font-medium">
                Cost model spread{" "}
                <span className="font-normal text-muted-foreground">· for backtests, not a feature</span>
              </summary>
              <div className="pb-1 pl-2 text-xs">
                {(["optimistic", "base", "pessimistic"] as const).map((k) => (
                  <div key={k} className="flex justify-between py-0.5">
                    <span className="text-muted-foreground">{k}</span>
                    <span className="font-mono tabular-nums">{b.costs![`spread_${k}`].toFixed(1)} pts</span>
                  </div>
                ))}
                <div className="flex justify-between py-0.5">
                  <span className="text-muted-foreground">source</span>
                  <span className="font-mono">{b.costs.spread_source}</span>
                </div>
              </div>
            </details>
          </>
        )}

        <p className="pt-2 text-[11px] leading-relaxed text-muted-foreground">
          {s.schema.length} features · {s.feature_set_id} · leakage self-check{" "}
          <span className={check ? "text-emerald-400" : "text-red-400"}>
            {check ? "passed" : check === null ? "not run" : "FAILED"}
          </span>
          . Hover a name for its meaning and when it becomes known.
        </p>
      </CardContent>
    </Card>
  );
}
