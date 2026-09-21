"use client";

import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  TickMarkType,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchCandles, type CandlesResponse, type Timeframe } from "@/lib/api";

export type DisplayZone = "UTC" | "America/New_York" | "Asia/Kolkata";

const UP = "#26a69a";
const DOWN = "#ef5350";
const MUTED = "#6b7280"; // bars built from fewer M1 bars than their length
const PAGE = 1500;
const LOAD_MORE_WHEN_WITHIN = 40; // bars from the left edge

interface Bars {
  candles: CandlestickData<UTCTimestamp>[];
  volume: HistogramData<UTCTimestamp>[];
  hasMore: boolean;
}

function toBars(r: CandlesResponse): Bars {
  const candles: CandlestickData<UTCTimestamp>[] = [];
  const volume: HistogramData<UTCTimestamp>[] = [];
  for (let i = 0; i < r.count; i++) {
    const time = r.time[i] as UTCTimestamp;
    const up = r.close[i] >= r.open[i];
    const partial = r.incomplete?.[i] ?? false;
    const color = partial ? MUTED : up ? UP : DOWN;
    candles.push({
      time,
      open: r.open[i],
      high: r.high[i],
      low: r.low[i],
      close: r.close[i],
      ...(partial ? { color, borderColor: color, wickColor: color } : {}),
    });
    volume.push({ time, value: r.volume[i], color: up ? "rgba(38,166,154,0.35)" : "rgba(239,83,80,0.35)" });
  }
  return { candles, volume, hasMore: r.has_more };
}

function formatter(zone: DisplayZone, opts: Intl.DateTimeFormatOptions) {
  const f = new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour12: false, ...opts });
  return (t: Time) => f.format(new Date((t as number) * 1000));
}

interface Legend {
  time: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  partial: boolean;
}

export function CandleChart({ timeframe, zone }: { timeframe: Timeframe; zone: DisplayZone }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const barsRef = useRef<Bars>({ candles: [], volume: [], hasMore: true });
  const loadingRef = useRef(false);
  const tfRef = useRef(timeframe);

  // Status is derived from which timeframe the loaded data / error belongs to.
  const [readyTf, setReadyTf] = useState<Timeframe | null>(null);
  const [failure, setFailure] = useState<{ tf: Timeframe; msg: string } | null>(null);
  const status = failure?.tf === timeframe ? "error" : readyTf === timeframe ? "ready" : "loading";
  const error = failure?.msg ?? null;
  const [legend, setLegend] = useState<Legend | null>(null);
  const [loadedCount, setLoadedCount] = useState(0);

  // ---------------------------------------------------------------- create once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#a1a1aa",
        fontSize: 12,
        attributionLogo: true, // TradingView attribution (Apache-2.0 NOTICE)
        panes: { separatorColor: "#27272a" },
      },
      grid: { vertLines: { color: "#1f1f23" }, horzLines: { color: "#1f1f23" } },
      rightPriceScale: { borderColor: "#27272a" },
      timeScale: { borderColor: "#27272a", timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: { mode: 0 },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" } }, 1);
    chart.panes()[1]?.setStretchFactor(0.18);

    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volume;
    if (process.env.NODE_ENV === "development") {
      // Lets automated UI checks drive the time scale; synthetic mouse events don't reach the canvas.
      (window as unknown as { __ciChart?: IChartApi }).__ciChart = chart;
    }
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // ---------------------------------------------------------------- time zone
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const full = formatter(zone, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    const hm = formatter(zone, { hour: "2-digit", minute: "2-digit" });
    const day = formatter(zone, { day: "2-digit", month: "short" });
    const month = formatter(zone, { month: "short", year: "2-digit" });
    const year = formatter(zone, { year: "numeric" });
    chart.applyOptions({
      localization: { timeFormatter: full },
      timeScale: {
        tickMarkFormatter: (t: Time, type: TickMarkType) =>
          type === TickMarkType.Year
            ? year(t)
            : type === TickMarkType.Month
              ? month(t)
              : type === TickMarkType.DayOfMonth
                ? day(t)
                : hm(t),
      },
    });
  }, [zone]);

  // ---------------------------------------------------------------- legend
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const full = formatter(zone, { weekday: "short", year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    const onMove = (p: MouseEventParams<Time>) => {
      const bars = barsRef.current;
      const c = p.time !== undefined && candleRef.current ? (p.seriesData.get(candleRef.current) as CandlestickData | undefined) : undefined;
      const last = bars.candles[bars.candles.length - 1];
      const bar = c ?? last;
      if (!bar) return setLegend(null);
      const idx = bars.candles.findIndex((b) => b.time === bar.time);
      setLegend({
        time: full(bar.time),
        o: bar.open,
        h: bar.high,
        l: bar.low,
        c: bar.close,
        v: idx >= 0 ? bars.volume[idx].value : 0,
        partial: idx >= 0 && bars.candles[idx].color === MUTED,
      });
    };
    chart.subscribeCrosshairMove(onMove);
    onMove({ seriesData: new Map() } as unknown as MouseEventParams<Time>); // show the latest bar
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, [zone, loadedCount]);

  // ---------------------------------------------------------------- data
  const loadOlder = useCallback(async () => {
    const bars = barsRef.current;
    const chart = chartRef.current;
    if (loadingRef.current || !bars.hasMore || !bars.candles.length || !chart) return;
    loadingRef.current = true;
    const tf = tfRef.current;
    try {
      const older = toBars(await fetchCandles(tf, bars.candles[0].time as number, PAGE));
      if (tf !== tfRef.current) return; // timeframe changed mid-request
      const range = chart.timeScale().getVisibleLogicalRange();
      barsRef.current = {
        candles: [...older.candles, ...bars.candles],
        volume: [...older.volume, ...bars.volume],
        hasMore: older.hasMore,
      };
      candleRef.current?.setData(barsRef.current.candles);
      volumeRef.current?.setData(barsRef.current.volume);
      // Keep the view still: everything shifted right by the prepended count.
      if (range) {
        chart.timeScale().setVisibleLogicalRange({
          from: range.from + older.candles.length,
          to: range.to + older.candles.length,
        });
      }
      setLoadedCount(barsRef.current.candles.length);
    } catch (e) {
      setFailure({ tf, msg: String(e) });
    } finally {
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    tfRef.current = timeframe;
    let cancelled = false;
    fetchCandles(timeframe, undefined, PAGE)
      .then((r) => {
        if (cancelled) return;
        const bars = toBars(r);
        barsRef.current = bars;
        candleRef.current?.setData(bars.candles);
        volumeRef.current?.setData(bars.volume);
        const n = bars.candles.length;
        chartRef.current?.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 180), to: n + 6 });
        setLoadedCount(n);
        setFailure(null);
        setReadyTf(timeframe);
      })
      .catch((e) => {
        if (cancelled) return;
        setFailure({ tf: timeframe, msg: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [timeframe]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const onRange = (r: LogicalRange | null) => {
      if (r && r.from < LOAD_MORE_WHEN_WITHIN) void loadOlder();
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    return () => chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
  }, [loadOlder]);

  const fmt = (x: number) => x.toFixed(2);
  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute left-3 right-20 top-2 z-10 flex flex-col gap-0.5">
      <div className="flex flex-wrap items-baseline gap-x-3 font-mono text-xs">
        <span className="font-sans text-sm font-semibold text-foreground">XAUUSD · {timeframe}</span>
        {legend && (
          <>
            <span className="text-muted-foreground">{legend.time}</span>
            <span>O <b className={legend.c >= legend.o ? "text-emerald-400" : "text-red-400"}>{fmt(legend.o)}</b></span>
            <span>H <b>{fmt(legend.h)}</b></span>
            <span>L <b>{fmt(legend.l)}</b></span>
            <span>C <b className={legend.c >= legend.o ? "text-emerald-400" : "text-red-400"}>{fmt(legend.c)}</b></span>
            <span className="text-muted-foreground">Vol {legend.v.toLocaleString()}</span>
            {legend.partial && <span className="text-amber-400">incomplete bar</span>}
          </>
        )}
      </div>
      <div className="text-[11px] text-muted-foreground">
        {status === "loading" && "Loading candles…"}
        {status === "ready" && `${loadedCount.toLocaleString()} bars loaded · drag left for older history`}
        {status === "error" && <span className="text-red-400">Could not load candles: {error}</span>}
      </div>
      </div>
    </div>
  );
}
