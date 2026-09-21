"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  fetchCostHeatmap,
  type CostBasis,
  type CostHeatmap,
  type CostStat,
  type CostWindow,
  type VolBucket,
} from "@/lib/api";

// Sequential blue ramp (dataviz reference palette), dark surface: low values
// recede toward the background, high values are the lightest.
const RAMP = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function lerpColor(t: number) {
  const x = Math.min(Math.max(t, 0), 1) * (RAMP.length - 1);
  return RAMP[Math.round(x)];
}

function fmt(v: number, basis: CostBasis) {
  return basis === "abs" ? v.toFixed(0) : `${v.toFixed(2)}×`;
}

function istHour(h: number) {
  const m = (h * 60 + 330) % 1440; // IST = UTC + 5:30
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

interface Opt<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

function Picker<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Opt<T>[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <ToggleGroup
        variant="outline"
        size="sm"
        spacing={0}
        value={[value]}
        onValueChange={(v) => v[0] && onChange(v[0] as T)}
        aria-label={label}
      >
        {options.map((o) => (
          <ToggleGroupItem key={o.value} value={o.value} disabled={o.disabled} className="px-2.5 text-xs">
            {o.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

function Grid({ data }: { data: CostHeatmap }) {
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null);
  const flat = data.values.flat().filter((v): v is number => v != null);
  const lo = Math.min(...flat);
  const hi = Math.max(...flat);
  const t = (v: number) => (hi > lo ? (v - lo) / (hi - lo) : 0.5);
  const hv = hover ? data.values[hover.d][hover.h] : null;
  const hm = hover ? data.minutes[hover.d][hover.h] : null;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <div
          role="grid"
          aria-label={`Spread ${data.stat} by UTC hour and weekday, ${data.unit}`}
          className="grid min-w-[640px] gap-[2px]"
          style={{ gridTemplateColumns: "36px repeat(24, minmax(0, 1fr))" }}
          onMouseLeave={() => setHover(null)}
        >
          <div />
          {data.hours.map((h) => (
            <div key={h} className="pb-1 text-center font-mono text-[10px] text-muted-foreground">
              {h % 3 === 0 ? String(h).padStart(2, "0") : ""}
            </div>
          ))}
          {data.days.map((_, di) => (
            <div key={di} role="row" className="contents">
              <div className="flex items-center text-xs text-muted-foreground">{DAYS[di]}</div>
              {data.hours.map((h, hi2) => {
                const v = data.values[di][hi2];
                const active = hover?.d === di && hover?.h === hi2;
                return (
                  <div
                    key={h}
                    role="gridcell"
                    aria-label={`${DAYS[di]} ${h}:00 UTC: ${v == null ? "market closed / no data" : `${fmt(v, data.basis)} ${data.unit}`}`}
                    onMouseEnter={() => setHover({ d: di, h: hi2 })}
                    className={
                      "h-7 rounded-[3px] " +
                      (v == null ? "border border-dashed border-foreground/10" : "") +
                      (active ? " ring-2 ring-foreground" : "")
                    }
                    style={v == null ? undefined : { background: lerpColor(t(v)) }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="font-mono tabular-nums">{fmt(lo, data.basis)}</span>
          <span
            aria-hidden
            className="h-2.5 w-40 rounded-full"
            style={{ background: `linear-gradient(to right, ${RAMP.join(",")})` }}
          />
          <span className="font-mono tabular-nums">{fmt(hi, data.basis)}</span>
          <span>{data.unit}</span>
        </div>
        <div className="min-h-4 font-mono tabular-nums text-foreground" aria-live="polite">
          {hover ? (
            <>
              {DAYS[hover.d]} {String(data.hours[hover.h]).padStart(2, "0")}:00 UTC ({istHour(data.hours[hover.h])} IST) ·{" "}
              {hv == null ? (
                <span className="text-muted-foreground">market closed / no quotes</span>
              ) : (
                <>
                  <span className="font-semibold">{fmt(hv, data.basis)}</span> {data.unit} ·{" "}
                  <span className="text-muted-foreground">{Math.round(hm ?? 0).toLocaleString()} min of quotes</span>
                </>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">Hover a cell for details</span>
          )}
        </div>
      </div>
    </div>
  );
}

export function SpreadHeatmap() {
  const [win, setWin] = useState<CostWindow>("current");
  const [basis, setBasis] = useState<CostBasis>("abs");
  const [stat, setStat] = useState<CostStat>("p90");
  const [vol, setVol] = useState<VolBucket>("all");
  const effBasis: CostBasis = win === "current" ? "abs" : basis;

  const { data, isLoading, error } = useQuery({
    queryKey: ["cost-heatmap", win, effBasis, stat, vol],
    queryFn: () => fetchCostHeatmap({ window: win, basis: effBasis, stat, vol }),
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Picker
          label="Window"
          value={win}
          onChange={setWin}
          options={[
            { value: "current", label: "Last 60 days" },
            { value: "full", label: "All tick days" },
          ]}
        />
        <Picker
          label="Unit"
          value={effBasis}
          onChange={setBasis}
          options={[
            { value: "abs", label: "Points" },
            { value: "ratio", label: "× minute floor", disabled: win === "current" },
          ]}
        />
        <Picker
          label="Stat"
          value={stat}
          onChange={setStat}
          options={(["p50", "p90", "p99", "mean"] as CostStat[]).map((s) => ({ value: s, label: s }))}
        />
        <Picker
          label="Volatility"
          value={vol}
          onChange={setVol}
          options={(["all", "low", "mid", "high"] as VolBucket[]).map((s) => ({ value: s, label: s }))}
        />
      </div>
      {isLoading && <Skeleton className="h-[260px] w-full" />}
      {error && <p className="text-sm text-destructive">{String(error)}</p>}
      {data && <Grid data={data} />}
    </div>
  );
}
