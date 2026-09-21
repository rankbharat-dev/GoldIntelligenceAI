"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import type { ChartMarker, OverlayLine } from "@/components/candle-chart";
import { cn } from "@/lib/utils";
import { explore, type StructureData } from "@/lib/research";

// Overlay colours: dataviz reference slots (blue / orange) for rising / falling geometry,
// brand gold for horizontal levels. Identity is also carried by the legend text.
export const STRUCT_COLOR = { up: "#3987e5", down: "#d95926", level: "#e0b04a", swing: "#a1a1aa" };

export type Layer = "swings" | "levels" | "lines" | "events";
export const LAYERS: { key: Layer; label: string; hint: string }[] = [
  { key: "swings", label: "Swings", hint: "Confirmed swing highs / lows (known 5 bars later)" },
  { key: "levels", label: "S/R", hint: "Support / resistance: clustered swings with ≥ 2 touches (current levels)" },
  { key: "lines", label: "Trendlines", hint: "Rising line through higher lows (blue), falling through lower highs (orange); dashed = channel" },
  { key: "events", label: "Events", hint: "Sweeps (SW), breakouts (BO), retests (RT), failed breaks (FB)" },
];

const EVENT_TEXT: Record<string, [string, "aboveBar" | "belowBar", string]> = {
  sweep_low: ["SW", "belowBar", STRUCT_COLOR.up],
  sweep_high: ["SW", "aboveBar", STRUCT_COLOR.down],
  break_up: ["BO", "belowBar", STRUCT_COLOR.up],
  break_down: ["BO", "aboveBar", STRUCT_COLOR.down],
  retest_up: ["RT", "belowBar", STRUCT_COLOR.up],
  retest_down: ["RT", "aboveBar", STRUCT_COLOR.down],
  failed_up: ["FB", "aboveBar", STRUCT_COLOR.down],
  failed_down: ["FB", "belowBar", STRUCT_COLOR.up],
};

/** Round the requested window so small pans reuse the cached result. */
function roundWindow(from: number, to: number): [number, number] {
  const h = 3600;
  return [Math.floor(from / h) * h, Math.ceil(to / h) * h];
}

export function useStructure(range: [number, number] | null, layers: Set<Layer>) {
  const win = range ? roundWindow(range[0], range[1]) : null;
  const q = useQuery({
    queryKey: ["structure", win],
    queryFn: () => explore.structure(win![0], win![1]),
    enabled: !!win && layers.size > 0,
    staleTime: Infinity,
    retry: false,
  });
  const out = useMemo(() => toOverlay(q.data, layers, win), [q.data, layers, win?.[0], win?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...out, data: q.data, loading: q.isFetching, error: q.error as Error | null };
}

function toOverlay(d: StructureData | undefined, layers: Set<Layer>, win: [number, number] | null) {
  const markers: ChartMarker[] = [];
  const overlays: OverlayLine[] = [];
  if (!d || !win) return { markers, overlays };
  if (layers.has("swings")) {
    for (const s of d.swings) {
      markers.push({ time: s.time, position: s.kind === "high" ? "aboveBar" : "belowBar", shape: "circle", color: STRUCT_COLOR.swing });
    }
  }
  if (layers.has("events")) {
    for (const e of d.events) {
      const spec = EVENT_TEXT[e.kind];
      if (spec) markers.push({ time: e.time, position: spec[1], shape: "square", color: spec[2], text: spec[0] });
    }
  }
  if (layers.has("levels")) {
    for (const l of d.levels) {
      const from = Math.max(l.first_time ?? win[0], win[0]);
      overlays.push({ points: [{ time: from, value: l.price }, { time: win[1], value: l.price }], color: STRUCT_COLOR.level, width: l.touches >= 3 ? 2 : 1, dashed: true });
    }
  }
  if (layers.has("lines")) {
    for (const ln of d.lines.slice(-24)) {
      const color = ln.kind === "up" ? STRUCT_COLOR.up : STRUCT_COLOR.down;
      const pts = [
        { time: ln.p1.time, value: ln.p1.price },
        { time: ln.p2.time, value: ln.p2.price },
        { time: ln.end.time, value: ln.end.price },
      ];
      overlays.push({ points: pts, color, width: 2 });
      if (ln.channel_offset) {
        const off = ln.kind === "up" ? ln.channel_offset : -ln.channel_offset;
        overlays.push({ points: pts.map((p) => ({ time: p.time, value: p.value + off })), color, width: 1, dashed: true });
      }
    }
  }
  return { markers, overlays };
}

export function LayerToggles({ value, onChange, loading }: { value: Set<Layer>; onChange: (v: Set<Layer>) => void; loading?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Structure overlays">
      {LAYERS.map((l) => {
        const on = value.has(l.key);
        return (
          <button
            key={l.key}
            type="button"
            title={l.hint}
            aria-pressed={on}
            onClick={() => {
              const next = new Set(value);
              if (on) next.delete(l.key);
              else next.add(l.key);
              onChange(next);
            }}
            className={cn(
              "rounded-md border px-2 py-0.5 text-xs",
              on ? "border-primary/60 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {l.label}
          </button>
        );
      })}
      {loading && <span className="text-[11px] text-muted-foreground">detecting…</span>}
    </div>
  );
}

export function StructureLegend() {
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      <span><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: STRUCT_COLOR.up }} />rising line / bullish event</span>
      <span><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: STRUCT_COLOR.down }} />falling line / bearish event</span>
      <span><span className="mr-1 inline-block h-0.5 w-4 border-t border-dashed align-middle" style={{ borderColor: STRUCT_COLOR.level }} />S/R level (thick = 3+ touches)</span>
      <span>● swing · SW sweep · BO breakout · RT retest · FB failed break</span>
    </p>
  );
}
