"use client";

import { createChart, LineSeries, type IChartApi, type LineData, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Scenario } from "@/lib/research";

// Scenario colours: pessimistic (the promotion gate) carries the brand gold; the others recede.
export const SCENARIO_COLOR: Record<Scenario, string> = {
  optimistic: "#3987e5",
  base: "#9ca3af",
  pessimistic: "#e0b04a",
};

export interface Curve {
  name: Scenario | string;
  color: string;
  time: number[];
  value: number[];
}

/** Cumulative R over trade exit times. Several curves share one axis. */
export function EquityChart({ curves, height = 260 }: { curves: Curve[]; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const chart: IChartApi = createChart(el.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#a1a1aa", attributionLogo: false, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: "#26231d" } },
      rightPriceScale: { borderColor: "#2a2620" },
      timeScale: { borderColor: "#2a2620", timeVisible: false },
      crosshair: { mode: 0 },
    });
    for (const c of curves) {
      const s = chart.addSeries(LineSeries, {
        color: c.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: c.name,
        priceFormat: { type: "custom", formatter: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)} R` },
      });
      // lightweight-charts needs strictly increasing times: keep the last value per second
      const data: LineData<UTCTimestamp>[] = [];
      c.time.forEach((t, i) => {
        const last = data[data.length - 1];
        if (last && (last.time as number) >= t) last.value = c.value[i];
        else data.push({ time: t as UTCTimestamp, value: c.value[i] });
      });
      s.setData(data);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [curves]);
  return <div ref={el} style={{ height }} className="w-full" />;
}
