"use client";

import {
  BaselineSeries,
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  TickMarkType,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { fetchCandles, fetchIndicators, type IndicatorsResponse, type Timeframe } from "@/lib/api";
import type { Trade } from "@/lib/research";

// One backtest trade on a real XAUUSD chart: the signal candle, entry, stop-loss and target
// zones, the exit, and the engine's own indicators — with bar-by-bar replay. Every price
// comes from the engine (trade record, candles, stored indicator features).

export type ReplayTf = Extract<Timeframe, "M1" | "M5" | "M15">;
export type IndicatorKey = "ema" | "bb" | "vwap" | "rsi";

export const TF_SECONDS: Record<ReplayTf, number> = { M1: 60, M5: 300, M15: 900 };

const UP = "#26a69a";
const DOWN = "#ef5350";
const GOLD = "#e0b04a";
const TP = "#34d399";
const SL = "#f87171";
const ENTRY = "#60a5fa";

const LINES: { key: IndicatorKey; col: keyof IndicatorsResponse["price"]; color: string; width: 1 | 2; dashed?: boolean; label: string }[] = [
  { key: "ema", col: "ema9", color: "#38bdf8", width: 1, label: "EMA 9" },
  { key: "ema", col: "ema21", color: "#a78bfa", width: 1, label: "EMA 21" },
  { key: "ema", col: "ema50", color: GOLD, width: 2, label: "EMA 50" },
  { key: "ema", col: "ema200", color: "#f472b6", width: 2, label: "EMA 200" },
  { key: "bb", col: "bb_upper", color: "#7c8aa5", width: 1, dashed: true, label: "BB upper" },
  { key: "bb", col: "bb_mid", color: "#7c8aa5", width: 1, label: "BB mid (SMA 50)" },
  { key: "bb", col: "bb_lower", color: "#7c8aa5", width: 1, dashed: true, label: "BB lower" },
  { key: "vwap", col: "vwap", color: "#22d3ee", width: 1, dashed: true, label: "VWAP (din)" },
];

export const INDICATOR_LEGEND: Record<IndicatorKey, { label: string; swatches: string[] }> = {
  ema: { label: "EMA 9 · 21 · 50 · 200", swatches: ["#38bdf8", "#a78bfa", GOLD, "#f472b6"] },
  bb: { label: "Bollinger 50 / 2.1", swatches: ["#7c8aa5"] },
  vwap: { label: "VWAP", swatches: ["#22d3ee"] },
  rsi: { label: "RSI 14", swatches: ["#e0b04a"] },
};

const snap = (t: number, step: number) => t - (t % step);

interface Loaded {
  key: string;
  candles: CandlestickData<UTCTimestamp>[];
  ind: IndicatorsResponse | null;
  error: string | null;
}

function istFormatter(opts: Intl.DateTimeFormatOptions) {
  const f = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour12: false, ...opts });
  return (t: Time) => f.format(new Date((t as number) * 1000));
}

/** Candles + indicators around one trade: ~60 bars of context before the signal, ~30 after the exit. */
function useTradeWindow(trade: Trade, tf: ReplayTf): Loaded | null {
  const [state, setState] = useState<Loaded | null>(null);
  const key = `${trade.entry_time}:${trade.side}:${tf}`;
  useEffect(() => {
    let cancelled = false;
    const step = TF_SECONDS[tf];
    const signal = snap(trade.decision_time - 300, step);
    const exit = snap(trade.exit_time, step);
    const held = Math.ceil((exit - signal) / step);
    const limit = Math.min(1500, Math.max(held, 1) + 60 + 30);
    fetchCandles(tf, exit + 31 * step, limit)
      .then(async (r) => {
        const candles: CandlestickData<UTCTimestamp>[] = r.time.map((t, i) => ({
          time: t as UTCTimestamp,
          open: r.open[i],
          high: r.high[i],
          low: r.low[i],
          close: r.close[i],
        }));
        let ind: IndicatorsResponse | null = null;
        if (candles.length) {
          try {
            ind = await fetchIndicators(candles[0].time - 900, candles[candles.length - 1].time + 900);
          } catch {
            ind = null; // candles still show; the indicator toggles say "not available"
          }
        }
        if (!cancelled) setState({ key, candles, ind, error: null });
      })
      .catch((e) => !cancelled && setState({ key, candles: [], ind: null, error: String(e) }));
    return () => {
      cancelled = true;
    };
  }, [key, trade, tf]);
  return state?.key === key ? state : null;
}

/** M5 indicator rows placed on this timeframe's bars. A value is known at its M5 bar's
 *  close, so on M1 it sits on the last minute of that M5 bar and on M15 on the M15 bar
 *  whose last M5 bar it is — never earlier than the engine could have read it. */
function indicatorLine(ind: IndicatorsResponse, values: (number | null)[], step: number, barTimes: Set<number>): LineData<UTCTimestamp>[] {
  const out: LineData<UTCTimestamp>[] = [];
  ind.time.forEach((t, i) => {
    const v = values[i];
    if (v == null) return;
    const at = t + 300 - step;
    if (barTimes.has(at)) out.push({ time: at as UTCTimestamp, value: v });
  });
  return out;
}

export function ReplayChart({
  trade,
  tf,
  indicators,
  reveal,
  onBars,
}: {
  trade: Trade;
  tf: ReplayTf;
  indicators: Set<IndicatorKey>;
  /** Show bars up to this index (inclusive); null = everything. */
  reveal: number | null;
  /** Reports the loaded bar count and the signal bar's index (replay starts there). */
  onBars?: (count: number, signalIndex: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const data = useTradeWindow(trade, tf);
  const step = TF_SECONDS[tf];
  const long = trade.side > 0;

  const geo = useMemo(() => {
    if (!data?.candles.length) return null;
    const times = data.candles.map((c) => c.time as number);
    const find = (t: number) => {
      const s = snap(t, step);
      const i = times.findIndex((x) => x >= s);
      return i < 0 ? times.length - 1 : i;
    };
    return {
      times,
      signal: find(trade.decision_time - 300),
      entry: find(trade.entry_time),
      exit: find(trade.exit_time),
    };
  }, [data, step, trade]);

  const onBarsRef = useRef(onBars);
  useEffect(() => {
    onBarsRef.current = onBars;
  }, [onBars]);
  useEffect(() => {
    if (geo) onBarsRef.current?.(geo.times.length, geo.signal);
  }, [geo]);

  const api = useRef<{
    chart: IChartApi;
    candles: ISeriesApi<"Candlestick">;
    markers: ISeriesMarkersPluginApi<Time>;
    tp: ISeriesApi<"Baseline"> | null;
    sl: ISeriesApi<"Baseline">;
    entry: ISeriesApi<"Line">;
    lines: { series: ISeriesApi<"Line">; data: LineData<UTCTimestamp>[] }[];
  } | null>(null);

  // Build the chart for this trade / timeframe / indicator set.
  useEffect(() => {
    const host = el.current;
    if (!host || !data?.candles.length || !geo) return;
    const chart = createChart(host, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#a1a1aa",
        fontSize: 11,
        attributionLogo: true,
        panes: { separatorColor: "#2a2620" },
      },
      grid: { vertLines: { color: "#1c1a16" }, horzLines: { color: "#1c1a16" } },
      rightPriceScale: { borderColor: "#2a2620" },
      timeScale: { borderColor: "#2a2620", timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: 0 },
      localization: { timeFormatter: istFormatter({ day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" }) },
    });
    const hm = istFormatter({ hour: "2-digit", minute: "2-digit" });
    const day = istFormatter({ day: "2-digit", month: "short" });
    chart.applyOptions({
      timeScale: { tickMarkFormatter: (t: Time, type: TickMarkType) => (type <= TickMarkType.DayOfMonth ? day(t) : hm(t)) },
    });

    const barTimes = new Set(geo.times);
    const lines: { series: ISeriesApi<"Line">; data: LineData<UTCTimestamp>[] }[] = [];
    if (data.ind) {
      for (const l of LINES) {
        if (!indicators.has(l.key)) continue;
        const s = chart.addSeries(LineSeries, {
          color: l.color,
          lineWidth: l.width,
          lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "",
          autoscaleInfoProvider: () => null, // indicators never rescale the candles
        });
        lines.push({ series: s, data: indicatorLine(data.ind, data.ind.price[l.col], step, barTimes) });
      }
    }

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });

    const zone = (color: string, fill: string) =>
      chart.addSeries(BaselineSeries, {
        baseValue: { type: "price", price: trade.entry_price },
        topLineColor: color,
        bottomLineColor: color,
        topFillColor1: fill,
        topFillColor2: fill,
        bottomFillColor1: fill,
        bottomFillColor2: fill,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    const tp = trade.target != null ? zone(TP, "rgba(52,211,153,0.14)") : null;
    const sl = zone(SL, "rgba(248,113,113,0.14)");
    const entry = chart.addSeries(LineSeries, {
      color: ENTRY,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    // Axis labels only (no full-width lines): Entry / SL / TP prices on the right scale.
    const label = (price: number, color: string, title: string) =>
      candles.createPriceLine({ price, color, lineVisible: false, axisLabelVisible: true, title, lineWidth: 1, lineStyle: LineStyle.Dashed });
    label(trade.entry_price, ENTRY, "Entry");
    label(trade.stop_initial, SL, "SL");
    if (trade.target != null) label(trade.target, TP, "TP");

    if (indicators.has("rsi") && data.ind) {
      const rsi = chart.addSeries(
        LineSeries,
        { color: GOLD, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "RSI", priceFormat: { type: "price", precision: 0, minMove: 1 } },
        1,
      );
      rsi.createPriceLine({ price: 70, color: "#52525b", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      rsi.createPriceLine({ price: 30, color: "#52525b", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
      chart.panes()[1]?.setStretchFactor(0.25);
      lines.push({ series: rsi, data: indicatorLine(data.ind, data.ind.osc.rsi14, step, barTimes) });
    }

    const markers = createSeriesMarkers(candles, []);
    api.current = { chart, candles, markers, tp, sl, entry, lines };
    const n = geo.times.length;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, geo.signal - 50), to: Math.min(n + 4, geo.exit + 25) });
    return () => {
      chart.remove();
      api.current = null;
    };
  }, [data, geo, indicators, step, trade]);

  // Reveal bars up to `reveal` (the replay), or all of them.
  useEffect(() => {
    const a = api.current;
    if (!a || !data || !geo) return;
    const last = reveal == null ? geo.times.length - 1 : Math.max(0, Math.min(reveal, geo.times.length - 1));
    const lastTime = geo.times[last];
    a.candles.setData(data.candles.slice(0, last + 1));
    for (const l of a.lines) l.series.setData(l.data.filter((p) => (p.time as number) <= lastTime));

    const inTrade = last >= geo.entry;
    const span = inTrade ? geo.times.slice(geo.entry, Math.min(last, geo.exit) + 1) : [];
    const flat = (v: number) => span.map((t) => ({ time: t as UTCTimestamp, value: v }));
    a.tp?.setData(trade.target != null ? flat(trade.target) : []);
    a.sl.setData(flat(trade.stop_initial));
    a.entry.setData(flat(trade.entry_price));

    const win = trade.r_net >= 0;
    const m: SeriesMarker<Time>[] = [];
    if (last >= geo.signal)
      m.push({ time: geo.times[geo.signal] as UTCTimestamp, position: long ? "belowBar" : "aboveBar", shape: "circle", color: GOLD, text: "Signal" });
    if (inTrade)
      m.push({
        time: geo.times[geo.entry] as UTCTimestamp,
        position: long ? "belowBar" : "aboveBar",
        shape: long ? "arrowUp" : "arrowDown",
        color: long ? TP : SL,
        text: `${long ? "BUY" : "SELL"} ${trade.entry_price.toFixed(2)}`,
      });
    if (last >= geo.exit)
      m.push({
        time: geo.times[geo.exit] as UTCTimestamp,
        position: long ? "aboveBar" : "belowBar",
        shape: "square",
        color: win ? TP : SL,
        text: `Exit ${trade.r_net >= 0 ? "+" : ""}${trade.r_net.toFixed(2)}R`,
      });
    m.sort((x, y) => (x.time as number) - (y.time as number));
    a.markers.setMarkers(m);
    // `indicators` / `step`: the build effect above made a new chart — fill it again.
  }, [reveal, data, geo, trade, long, indicators, step]);

  return (
    <div className="relative h-full w-full">
      <div ref={el} className="absolute inset-0" />
      {!data && <p className="absolute top-3 left-3 text-xs text-muted-foreground">Chart load ho raha hai…</p>}
      {data?.error && <p className="absolute top-3 left-3 text-xs text-red-300">Candles nahi aaye: {data.error}</p>}
      {data && !data.error && !data.ind && indicators.size > 0 && (
        <p className="absolute top-3 left-3 text-[11px] text-amber-300">Indicators is time ke liye available nahi (sirf candles).</p>
      )}
    </div>
  );
}
