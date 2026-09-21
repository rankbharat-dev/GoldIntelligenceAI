"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchSummary, TIMEFRAMES } from "@/lib/api";

function Row({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-muted-foreground" title={hint}>
        {label}
      </span>
      <span className="text-right font-mono tabular-nums">{value}</span>
    </div>
  );
}

const pct = (x: number | null | undefined, digits = 2) => (x == null ? "—" : `${(x * 100).toFixed(digits)}%`);
const day = (s: string) => s.slice(0, 10);

const GAP_LABELS: Record<string, string> = {
  weekend: "Weekend closes",
  daily_break: "Daily breaks",
  closure: "Holiday / long closures",
  long_intraday: "Intraday gaps ≥ 30 min",
  short_intraday: "Intraday gaps < 30 min",
};

export function DataHealth() {
  const { data: s, isLoading, error } = useQuery({ queryKey: ["summary"], queryFn: () => fetchSummary() });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-40 w-full" />
        ))}
      </div>
    );
  }
  if (error || !s) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Data health unavailable</CardTitle>
          <CardDescription>
            Start the API with <code className="font-mono">ci-api</code>. {String(error ?? "")}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const q = s.quality;
  const offsets = s.clock_model.distinct_offsets_hours.map((h) => `UTC${h >= 0 ? "+" : ""}${h}`).join(", ");
  const minMatch = Math.min(
    ...Object.values(s.verification_vs_broker).map((v) => v.ohlc_match_rate ?? 0),
  );

  return (
    <div className="space-y-3">
      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            Dataset
            <Badge variant={q.passed ? "secondary" : "destructive"}>
              {q.passed ? "Quality gate passed" : "Quality gate FAILED"}
            </Badge>
          </CardTitle>
          <CardDescription>
            {s.broker} · {s.broker_server}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Row label="Research window" value={`${day(q.coverage.research_window_utc[0])} → ${day(q.coverage.research_window_utc[1])}`} />
          <Row label="Span" value={`${q.coverage.years} years`} />
          {TIMEFRAMES.map((tf) => (
            <Row key={tf} label={`${tf} bars`} value={s.bars[tf]?.toLocaleString() ?? "—"} />
          ))}
          <Row label="Prices" value={s.price_side} />
          <Separator className="my-2" />
          <Row
            label="Match vs broker bars"
            hint="Our M5/M15/H1, rebuilt from M1, compared bar-for-bar with the broker's own bars"
            value={<span className={minMatch === 1 ? "text-emerald-400" : "text-amber-400"}>{pct(minMatch, 3)}</span>}
          />
          <Row label="Broker clock" value={offsets} hint="Measured from the daily break, not assumed" />
          <Row
            label="Clock consistency"
            value={pct(s.clock_model.days_consistent_with_week)}
            hint={`${s.clock_model.days_measured} days measured`}
          />
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Gaps</CardTitle>
          <CardDescription>
            Daily break at {q.daily_break_ny.typical_start} New York, ~{q.daily_break_ny.typical_minutes} min
          </CardDescription>
        </CardHeader>
        <CardContent>
          {Object.entries(q.gaps).map(([k, g]) => (
            <Row key={k} label={GAP_LABELS[k] ?? k} value={`${g.count.toLocaleString()} · ${g.missing_minutes.toLocaleString()} min`} />
          ))}
          <Row label="Missing minutes (short gaps)" value={pct(q.short_intraday_missing_share, 3)} />
          {q.largest_unexpected_gaps.length > 0 && (
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground">Largest closures</summary>
              <ul className="mt-1 space-y-0.5 font-mono">
                {q.largest_unexpected_gaps.slice(0, 8).map((g) => (
                  <li key={g.start_ny} className="flex justify-between">
                    <span>{g.start_ny} NY</span>
                    <span>{Math.round(g.minutes / 60)} h</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Anomalies & spread</CardTitle>
          <CardDescription>Flagged for research, not deleted</CardDescription>
        </CardHeader>
        <CardContent>
          <Row label="Price spikes" value={q.price_anomalies.count.toLocaleString()} hint={q.price_anomalies.rule} />
          <Row label="Flat bars (H = L)" value={pct(q.flat_bars_share)} />
          <Separator className="my-2" />
          <Row label="Spread p50 / p90 / p99" value={`${q.spread_points.p50} / ${q.spread_points.p90} / ${q.spread_points.p99} pts`} />
          <Row label="Spread max" value={`${q.spread_points.max} pts`} />
          <Row
            label="Zero-spread bars"
            value={q.spread_points.nonpositive.toLocaleString()}
            hint="Broker reported spread ≤ 0; the cost model must not trust these"
          />
          <Row label="Blocking errors" value={Object.values(q.blocking).reduce((a, b) => a + b, 0)} />
        </CardContent>
      </Card>

      <p className="px-1 text-[11px] leading-relaxed text-muted-foreground">
        Dataset {s.dataset_id} · code {s.code_version.git_commit?.slice(0, 7) ?? "?"}
        {s.code_version.dirty ? " (uncommitted changes)" : ""}
      </p>
    </div>
  );
}
