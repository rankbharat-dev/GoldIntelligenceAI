"use client";

import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  LineSeries,
  LineType,
  type IChartApi,
  type LineData,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { fetchCostLevels, type CostLevels } from "@/lib/api";

// Categorical slots 1 and 2 of the dataviz reference palette, dark-surface steps.
const LEVEL = "#3987e5";
const MEASURED = "#d95926";

const day = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" });

interface Hover {
  time: number;
  level?: number;
  measured?: number;
}

function Chart({ data }: { data: CostLevels }) {
  const el = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart: IChartApi = createChart(el.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#a1a1aa", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1f1f23" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: { horzLine: { visible: false } },
      handleScroll: false,
      handleScale: false,
    });
    const common = { lineWidth: 2 as const, lineType: LineType.WithSteps, priceLineVisible: false, lastValueVisible: false };
    const level = chart.addSeries(LineSeries, { ...common, color: LEVEL });
    const measured = chart.addSeries(LineSeries, { ...common, color: MEASURED });

    const levelData: LineData<UTCTimestamp>[] = data.time.map((t, i) => ({
      time: t as UTCTimestamp,
      value: data.level_median[i],
    }));
    const measuredData: LineData<UTCTimestamp>[] = [];
    data.time.forEach((t, i) => {
      const v = data.measured_mean[i];
      if (v != null) measuredData.push({ time: t as UTCTimestamp, value: v });
    });
    level.setData(levelData);
    measured.setData(measuredData);
    chart.timeScale().fitContent();

    const onMove = (p: MouseEventParams<Time>) => {
      if (p.time === undefined) return setHover(null);
      const l = p.seriesData.get(level) as LineData | undefined;
      const m = p.seriesData.get(measured) as LineData | undefined;
      setHover({ time: p.time as number, level: l?.value, measured: m?.value });
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [data]);

  const last = data.time.length - 1;
  const shown: Hover = hover ?? {
    time: data.time[last],
    level: data.level_median[last],
    measured: data.measured_mean[last] ?? undefined,
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span className="font-mono text-muted-foreground">{day.format(new Date(shown.time * 1000))}</span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ background: LEVEL }} />
          <span className="text-muted-foreground">Bar minimum spread (daily median)</span>
          <span className="font-mono tabular-nums">{shown.level?.toFixed(0) ?? "—"}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ background: MEASURED }} />
          <span className="text-muted-foreground">Tick-measured, time-weighted</span>
          <span className="font-mono tabular-nums">{shown.measured?.toFixed(1) ?? "—"}</span>
        </span>
        <span className="text-muted-foreground">points</span>
      </div>
      <div
        ref={el}
        className="h-[220px] w-full"
        role="img"
        aria-label="Daily XAUUSD spread level in points since 2021, with tick-measured spread for the tick window"
      />
      <p className="text-[11px] text-muted-foreground">
        Full trading days only — Sunday-open and holiday stub sessions (≈1 h, spreads up to 10×) are left out of this line.
      </p>
    </div>
  );
}

export function LevelChart() {
  const { data, isLoading, error } = useQuery({ queryKey: ["cost-levels"], queryFn: () => fetchCostLevels() });
  if (isLoading) return <Skeleton className="h-[240px] w-full" />;
  if (error || !data) return <p className="text-sm text-destructive">{String(error)}</p>;
  return <Chart data={data} />;
}
