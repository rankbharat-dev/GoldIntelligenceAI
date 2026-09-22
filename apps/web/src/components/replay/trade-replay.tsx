"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Eye, Pause, Play, StepForward, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EXIT_PLAIN, FEATURE_PLAIN, FILTER_PLAIN, REGIME_PLAIN, ruleWord, SESSION_PLAIN, valueWord } from "@/lib/plain";
import { research, type BacktestRun, type Explain, type Trade } from "@/lib/research";
import { cn } from "@/lib/utils";

import { INDICATOR_LEGEND, ReplayChart, type IndicatorKey, type ReplayTf } from "./replay-chart";

// "Chart pe verify karo": every trade of a backtest on the real chart, bar-by-bar replay,
// and the engine's own check of each rule on the signal candle — so the owner can see
// that the trade was taken exactly by their rules.

const SPEEDS = [
  { label: "1×", ms: 450 },
  { label: "2×", ms: 220 },
  { label: "5×", ms: 90 },
];
const PAGE = 2000; // the trades endpoint's maximum page

const ist = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
const istShort = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
const when = (t: number) => `${ist.format(new Date(t * 1000))} IST`;
const hhmm = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
const px = (x: number | null | undefined) => (x == null ? "—" : x.toFixed(2));
const signed = (x: number, d = 2) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;

type Filter = "all" | "win" | "loss";

export function TradeReplay({ run }: { run: BacktestRun }) {
  const q = useQuery({
    queryKey: ["trades", run.run_id, "pessimistic", "replay"],
    queryFn: () => research.trades(run.run_id, "pessimistic", 0, PAGE),
    staleTime: Infinity,
  });
  const [filter, setFilter] = useState<Filter>("all");
  const [pick, setPick] = useState(0);
  const [tf, setTf] = useState<ReplayTf>("M5");
  const [ind, setInd] = useState<Set<IndicatorKey>>(() => new Set<IndicatorKey>(["ema"]));
  const [reveal, setReveal] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(0);
  const [bars, setBars] = useState<{ count: number; signal: number } | null>(null);

  const all = useMemo(() => (q.data?.trades ?? []).map((t, i) => ({ t, n: i + 1 })), [q.data]);
  const list = useMemo(
    () => all.filter(({ t }) => filter === "all" || (filter === "win" ? t.r_net > 0 : t.r_net <= 0)),
    [all, filter],
  );
  const cur = list[Math.min(pick, Math.max(list.length - 1, 0))] ?? null;

  const select = useCallback((i: number) => {
    setPick(i);
    setReveal(null);
    setPlaying(false);
    setBars(null);
  }, []);

  const onBars = useCallback((count: number, signal: number) => setBars({ count, signal }), []);

  // Replay clock: one bar per tick until the last bar.
  useEffect(() => {
    if (!playing || !bars) return;
    const id = setInterval(() => setReveal((r) => Math.min((r ?? bars.signal - 1) + 1, bars.count - 1)), SPEEDS[speed].ms);
    return () => clearInterval(id);
  }, [playing, bars, speed]);
  if (playing && bars && reveal === bars.count - 1) setPlaying(false); // reached the last bar

  const play = () => {
    if (!bars) return;
    if (reveal == null) setReveal(Math.max(0, bars.signal - 1));
    setPlaying((p) => !p);
  };

  const wins = all.filter(({ t }) => t.r_net > 0).length;

  if (q.isLoading) return <p className="text-sm text-muted-foreground">Trades load ho rahe hain…</p>;
  if (q.error) return <p className="text-sm text-red-300">Trades nahi aaye: {String(q.error)}</p>;
  if (!all.length) return <p className="text-sm text-muted-foreground">Is test mein koi trade nahi bana — chart pe dikhane ko kuch nahi.</p>;

  const toggle = (k: IndicatorKey) => {
    const s = new Set(ind);
    if (s.has(k)) s.delete(k);
    else s.add(k);
    setInd(s);
  };

  return (
    <div className="space-y-3">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Candle size" className="flex rounded-lg border p-0.5">
          {(["M1", "M5", "M15"] as const).map((x) => (
            <button
              key={x}
              type="button"
              role="radio"
              aria-checked={tf === x}
              onClick={() => {
                setTf(x);
                setReveal(null);
                setPlaying(false);
                setBars(null);
              }}
              className={cn("h-8 rounded-md px-3 text-xs font-semibold", tf === x ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}
            >
              {x === "M1" ? "1 min" : x === "M5" ? "5 min" : "15 min"}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1" aria-label="Indicators">
          {(Object.keys(INDICATOR_LEGEND) as IndicatorKey[]).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={ind.has(k)}
              onClick={() => toggle(k)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs",
                ind.has(k) ? "border-primary/50 bg-primary/10 text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="flex gap-0.5">
                {INDICATOR_LEGEND[k].swatches.map((c) => (
                  <span key={c} className="h-2.5 w-1 rounded-full" style={{ background: c }} />
                ))}
              </span>
              {INDICATOR_LEGEND[k].label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" onClick={play} disabled={!bars} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-semibold text-primary-foreground disabled:opacity-50">
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            {playing ? "Roko" : reveal == null ? "Replay" : "Chalao"}
          </button>
          <button
            type="button"
            aria-label="Ek candle aage"
            title="Ek candle aage"
            disabled={!bars}
            onClick={() => {
              setPlaying(false);
              setReveal((r) => (r == null ? Math.max(0, (bars?.signal ?? 1) - 1) : Math.min(r + 1, (bars?.count ?? 1) - 1)));
            }}
            className="inline-flex size-8 items-center justify-center rounded-lg border hover:bg-muted disabled:opacity-50"
          >
            <StepForward className="size-3.5" />
          </button>
          <button
            type="button"
            aria-label="Poora dikhao"
            title="Poora dikhao"
            onClick={() => {
              setPlaying(false);
              setReveal(null);
            }}
            className="inline-flex size-8 items-center justify-center rounded-lg border hover:bg-muted"
          >
            <Eye className="size-3.5" />
          </button>
          <div role="radiogroup" aria-label="Replay speed" className="flex rounded-lg border p-0.5">
            {SPEEDS.map((s, i) => (
              <button
                key={s.label}
                type="button"
                role="radio"
                aria-checked={speed === i}
                onClick={() => setSpeed(i)}
                className={cn("h-7 rounded-md px-2 text-[11px] font-semibold", speed === i ? "bg-muted text-foreground" : "text-muted-foreground")}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-2">
          <div className="relative h-[460px] overflow-hidden rounded-xl border bg-background/40">
            {cur && <ReplayChart key={`${cur.t.entry_time}:${cur.t.side}`} trade={cur.t} tf={tf} indicators={ind} reveal={reveal} onBars={onBars} />}
          </div>
          <ChartKey />
        </div>
        {cur && <TradeStory run={run} trade={cur.t} n={cur.n} total={q.data?.total ?? all.length} />}
      </div>

      {/* trade list */}
      <div className="rounded-xl border">
        <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
          <span className="text-sm font-semibold">Saare trades</span>
          <span className="text-xs text-muted-foreground">
            {all.length.toLocaleString()} trades{q.data && q.data.total > all.length ? ` (pehle ${all.length.toLocaleString()} of ${q.data.total.toLocaleString()})` : ""} · {wins} jeete · {all.length - wins} haare
          </span>
          <div role="radiogroup" aria-label="Trades filter" className="ml-auto flex rounded-lg border p-0.5">
            {(
              [
                ["all", "Sab"],
                ["win", "Jeete"],
                ["loss", "Haare"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={filter === k}
                onClick={() => {
                  setFilter(k);
                  select(0);
                }}
                className={cn("h-7 rounded-md px-2.5 text-xs", filter === k ? "bg-muted font-semibold text-foreground" : "text-muted-foreground")}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button type="button" aria-label="Pichhla trade" disabled={pick <= 0} onClick={() => select(pick - 1)} className="inline-flex size-8 items-center justify-center rounded-lg border disabled:opacity-40">
              <ChevronLeft className="size-4" />
            </button>
            <span className="min-w-16 text-center font-mono text-xs tabular-nums">
              {list.length ? Math.min(pick, list.length - 1) + 1 : 0} / {list.length}
            </span>
            <button type="button" aria-label="Agla trade" disabled={pick >= list.length - 1} onClick={() => select(pick + 1)} className="inline-flex size-8 items-center justify-center rounded-lg border disabled:opacity-40">
              <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left font-normal">#</th>
                <th className="px-3 py-1.5 text-left font-normal">Kab (IST)</th>
                <th className="px-3 py-1.5 text-left font-normal">Disha</th>
                <th className="px-3 py-1.5 text-left font-normal">Kaise band hua</th>
                <th className="px-3 py-1.5 text-left font-normal">Session</th>
                <th className="px-3 py-1.5 text-right font-normal">Result</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {list.map(({ t, n }, i) => (
                <tr
                  key={`${t.entry_time}-${t.side}`}
                  onClick={() => select(i)}
                  aria-selected={cur?.n === n}
                  className={cn("cursor-pointer border-t border-border/60 hover:bg-muted/40", cur?.n === n && "bg-primary/10")}
                >
                  <td className="px-3 py-1.5 font-mono text-muted-foreground">{n}</td>
                  <td className="px-3 py-1.5 font-mono">{istShort.format(new Date(t.entry_time * 1000))}</td>
                  <td className={cn("px-3 py-1.5 font-semibold", t.side > 0 ? "text-emerald-400" : "text-red-400")}>{t.side > 0 ? "BUY" : "SELL"}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{EXIT_PLAIN[t.exit_reason]?.word ?? t.exit_reason}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{t.session ? (SESSION_PLAIN[t.session] ?? t.session) : "—"}</td>
                  <td className={cn("px-3 py-1.5 text-right font-mono font-semibold", t.r_net > 0 ? "text-emerald-400" : "text-red-400")}>
                    {signed(t.r_net)} R
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ChartKey() {
  const item = (color: string, label: string, box = false) => (
    <span className="inline-flex items-center gap-1.5">
      <span className={box ? "h-3 w-4 rounded-sm" : "h-0.5 w-4"} style={{ background: color }} />
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
      {item("#e0b04a", "● Signal = rule sach hua (candle band hone pe)")}
      {item("#60a5fa", "Entry")}
      {item("rgba(52,211,153,0.5)", "Target (TP) zone", true)}
      {item("rgba(248,113,113,0.5)", "Stop-loss (SL) zone", true)}
      <span>Samay IST mein · indicators engine ke apne values</span>
    </div>
  );
}

function TradeStory({ run, trade, n, total }: { run: BacktestRun; trade: Trade; n: number; total: number }) {
  const long = trade.side > 0;
  const ex = useQuery({
    queryKey: ["explain", run.spec_hash, trade.decision_time],
    queryFn: () => research.explain(run.spec, trade.decision_time),
    staleTime: Infinity,
    retry: false,
  });
  const exit = EXIT_PLAIN[trade.exit_reason] ?? { word: trade.exit_reason, tone: "muted" as const };
  const risk = Math.abs(trade.entry_price - trade.stop_initial);
  const win = trade.r_net > 0;
  return (
    <aside aria-label="Is trade ki kahani" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-muted-foreground">
            Trade {n} / {total}
          </p>
          <p className="text-lg font-bold">
            <span className={long ? "text-emerald-400" : "text-red-400"}>{long ? "BUY" : "SELL"}</span> · {istShort.format(new Date(trade.entry_time * 1000))}
          </p>
        </div>
        <span className={cn("rounded-lg px-2.5 py-1 text-right font-mono text-sm font-bold", win ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300")}>
          {signed(trade.r_net)} R
          <span className="block text-[11px] font-normal">{trade.pnl_usd >= 0 ? "+" : "−"}${Math.abs(trade.pnl_usd).toFixed(0)}</span>
        </span>
      </div>

      <RuleCheck ex={ex.data} error={ex.error ? String(ex.error) : null} loading={ex.isLoading} side={long ? "long" : "short"} />

      <ol className="space-y-2 text-sm leading-relaxed">
        <li>
          <b>1 · Signal:</b> {when(trade.decision_time - 300)} wali 5-min candle {hhmm.format(new Date(trade.decision_time * 1000))} pe band hui — rules sach hue.
        </li>
        <li>
          <b>2 · Entry:</b> agle minute {px(trade.entry_price)} pe {long ? "buy" : "sell"} (spread + slippage ke saath — asli jaisa).
        </li>
        <li>
          <b>3 · Stop / Target:</b> SL <span className="font-mono text-red-300">{px(trade.stop_initial)}</span> ({risk.toFixed(2)} door = 1 R) · TP{" "}
          <span className="font-mono text-emerald-300">{px(trade.target)}</span>
        </li>
        <li>
          <b>4 · Exit:</b> <span className={cn(exit.tone === "good" && "text-emerald-300", exit.tone === "bad" && "text-red-300")}>{exit.word}</span> —{" "}
          {px(trade.exit_price)} pe, {trade.bars_held_m1} minute baad.
          {trade.ambiguous && <span className="text-amber-300"> (Ek hi minute mein SL aur TP dono chhue — engine ne bura wala maana.)</span>}
        </li>
        <li>
          <b>5 · Hisaab:</b> kharche se pehle {signed(trade.r_before_costs)} R → kharche ke baad <b>{signed(trade.r_net)} R</b>. Beech mein sabse zyada faayda {signed(trade.mfe_r)} R, sabse zyada nuksaan −{Math.abs(trade.mae_r).toFixed(2)} R.
        </li>
      </ol>
      <p className="text-[11px] text-muted-foreground">
        {trade.session ? SESSION_PLAIN[trade.session] ?? trade.session : "—"} session · {trade.vol_regime ? REGIME_PLAIN[trade.vol_regime] ?? trade.vol_regime : "—"} · {trade.lots} lot · run{" "}
        <span className="font-mono">{run.run_id}</span>
      </p>
    </aside>
  );
}

function Tick({ ok }: { ok: boolean }) {
  return (
    <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full", ok ? "bg-emerald-500 text-background" : "bg-red-500 text-background")}>
      {ok ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" strokeWidth={3} />}
    </span>
  );
}

/** The engine's check of every rule on the signal candle. */
function RuleCheck({ ex, error, loading, side }: { ex?: Explain; error: string | null; loading: boolean; side: "long" | "short" }) {
  const cat = useQuery({ queryKey: ["catalogue"], queryFn: research.catalogue, staleTime: Infinity });
  const desc = new Map((cat.data?.features ?? []).map((f) => [f.name, f.description]));
  if (loading) return <p className="text-xs text-muted-foreground">Rules check ho rahe hain…</p>;
  if (error || !ex) return <p className="text-xs text-amber-300">Rule check nahi mila: {error}</p>;
  const rules = ex.entries.filter((e) => e.side === side);
  const used = rules.find((e) => e.passed) ?? rules[0];
  const ok = ex.fires && !!used?.passed && ex.filters.every((f) => f.passed);
  return (
    <div className={cn("rounded-lg border p-3", ok ? "border-emerald-500/40 bg-emerald-500/5" : "border-red-500/40 bg-red-500/5")}>
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Tick ok={ok} />
        {ok ? "Aapke saare rules is candle pe sach the" : "Is candle pe koi rule sach nahi tha"}
      </p>
      <ul className="space-y-1.5 text-xs">
        {used?.conditions.map((c, i) => (
          <li key={i} className="flex items-start gap-2">
            <Tick ok={c.passed} />
            <span className="min-w-0">
              {ruleWord(c.feature, c.op, c.value)}
              {!FEATURE_PLAIN[c.feature] && desc.get(c.feature) && <span className="block text-[11px] text-muted-foreground/80">{desc.get(c.feature)}</span>}
              <span className="block text-muted-foreground">
                is candle pe: <b className="font-mono text-foreground">{valueWord(c.actual)}</b>
              </span>
            </span>
          </li>
        ))}
        {ex.filters.map((f) => (
          <li key={f.key} className="flex items-start gap-2">
            <Tick ok={f.passed} />
            <span className="min-w-0">
              {FILTER_PLAIN[f.key] ?? f.key}
              {f.key !== "hygiene" && (
                <span className="block text-muted-foreground">
                  chahiye: {Array.isArray(f.value) ? f.value.map((v) => SESSION_PLAIN[String(v)] ?? String(v)).join(", ") : valueWord(f.value)} · is candle pe:{" "}
                  <b className="text-foreground">{SESSION_PLAIN[String(f.actual)] ?? valueWord(f.actual)}</b>
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

