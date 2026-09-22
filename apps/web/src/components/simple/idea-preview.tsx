"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { CandleChart, type ChartMarker } from "@/components/candle-chart";
import { research, type StrategySpec } from "@/lib/research";

// Live preview for the idea builder: where the rules fire on real XAUUSD candles (practice
// + check data only; the sealed final-exam data is never shown). Not a backtest — no trial.

export function IdeaPreview({ spec }: { spec: StrategySpec | null }) {
  const key = spec ? JSON.stringify({ e: spec.entries, f: spec.filters }) : null;
  const q = useQuery({
    queryKey: ["preview", key],
    queryFn: () => research.preview(spec!, 400),
    enabled: !!spec,
    staleTime: Infinity,
    retry: false,
  });
  const markers = useMemo<ChartMarker[]>(
    () =>
      (q.data?.event_time ?? []).map((t, i) => {
        const long = q.data!.side[i] > 0;
        return { time: t, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: long ? "#34d399" : "#f87171" };
      }),
    [q.data],
  );
  const last = q.data?.event_time.length ? q.data.event_time[q.data.event_time.length - 1] : null;
  const perMonth = q.data ? Math.round((q.data.counts.A / Math.max(1, q.data.bars_per_tier.A)) * 288 * 21) : null; // M5 bars ≈ 288/day, ~21 trading days

  return (
    <div className="space-y-2">
      <div className="relative h-72 overflow-hidden rounded-xl border bg-background/40">
        {!spec && (
          <p className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
            Pehla sawaal chuno — chart pe turant dikhega ki aapka pattern kahan-kahan banta hai.
          </p>
        )}
        {spec && q.isLoading && <p className="p-3 text-xs text-muted-foreground">Pattern dhoondh rahe hain…</p>}
        {spec && q.error && <p className="p-3 text-xs text-red-300">Preview nahi bana: {String(q.error)}</p>}
        {spec && q.data && !last && <p className="p-3 text-xs text-amber-300">In rules pe ek bhi candle fit nahi hui — filter dheela karo.</p>}
        {last != null && <CandleChart key={last} timeframe="M5" zone="Asia/Kolkata" anchor={last} markers={markers} />}
      </div>
      {q.data && (
        <div className="grid grid-cols-3 gap-2 text-center">
          <Stat label="Practice data mein" value={q.data.counts.A.toLocaleString()} />
          <Stat label="Check data mein" value={q.data.counts.B.toLocaleString()} />
          <Stat label="~ har mahine" value={perMonth != null ? String(perMonth) : "—"} />
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        ▲ hara = buy signal, ▼ laal = sell signal (candle band hone pe). Yeh sirf dikhata hai ki rule kab sach hota hai — kamai ka pata
        &quot;Test chalao&quot; ke baad chalega. Preview koshish (trial) nahi ginta.
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card px-2 py-1.5">
      <p className="font-mono text-lg font-bold tabular-nums">{value}</p>
      <p className="text-[10px] text-muted-foreground">{label}</p>
    </div>
  );
}
