"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { CandleChart } from "@/components/candle-chart";
import { Notice, Section } from "@/components/research/bits";
import { conditionText } from "@/components/research/conditions";
import { LayerToggles, StructureLegend, useStructure, type Layer } from "@/components/structure-layer";
import { Button } from "@/components/ui/button";
import { explore, research, type Condition, type Side } from "@/lib/research";
import { cn } from "@/lib/utils";

/** Chart-Based Creator: mark the bar you would have entered on; its measurable features
 *  become a rule draft you tick through, then it goes to the Visual Builder. */
export function ChartCreator({ onUse }: { onUse: (side: Side, conditions: Condition[], sessions: string[] | null) => void }) {
  const [side, setSide] = useState<Side>("long");
  const [bar, setBar] = useState<number | null>(null);
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [useSession, setUseSession] = useState(false);
  const [layers, setLayers] = useState<Set<Layer>>(() => new Set<Layer>(["swings", "levels", "lines", "events"]));
  const [range, setRange] = useState<[number, number] | null>(null);
  const onRange = useCallback((a: number, b: number) => setRange([a, b]), []);
  const structure = useStructure(range, layers);
  // Open just before the sealed tier C: bars there cannot be marked.
  const overview = useQuery({ queryKey: ["overview"], queryFn: research.overview, staleTime: 60_000 });
  const anchor = overview.data ? Math.floor(Date.parse(overview.data.split.c_start + "Z") / 1000) - 3 * 86400 : null;

  const draft = useQuery({
    queryKey: ["draft", bar, side],
    queryFn: () => explore.draft(bar!, "M5", side),
    enabled: bar != null,
    retry: false,
  });
  const chosen = (i: number) => picked[i] ?? draft.data?.suggestions[i]?.selected ?? false;
  const selected = draft.data ? draft.data.suggestions.filter((_, i) => chosen(i)).map((s) => s.condition) : [];

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
      <Section
        title="1 · Mark the entry bar"
        description="The chart opens at the end of tier B (tier C is sealed). Scroll to a setup you like and click the candle where you would have entered (at its close). Overlays show what the structure detectors saw at the time."
      >
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <LayerToggles value={layers} onChange={setLayers} loading={structure.loading} />
          <span className="ml-auto flex gap-1">
            {(["long", "short"] as const).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={side === s}
                onClick={() => setSide(s)}
                className={cn(
                  "rounded-md border px-2 py-0.5 text-xs",
                  side === s
                    ? s === "long"
                      ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-300"
                      : "border-red-500/60 bg-red-500/15 text-red-300"
                    : "text-muted-foreground",
                )}
              >
                {s}
              </button>
            ))}
          </span>
        </div>
        <div className="relative h-[56dvh] min-h-[380px] overflow-hidden rounded-lg border">
          {anchor != null && (
          <CandleChart
            anchor={anchor}
            timeframe="M5"
            zone="Asia/Kolkata"
            selected={bar}
            onSelect={(t) => {
              setBar(t);
              setPicked({});
            }}
            markers={structure.markers}
            overlays={structure.overlays}
            onRangeChange={onRange}
          />
          )}
        </div>
        <div className="mt-2">
          <StructureLegend />
        </div>
      </Section>

      <aside className="space-y-3">
        <Section title="2 · Keep what describes the setup" description="Each line is a measurable fact about the marked bar. Tick 2–4; more than that describes one bar, not a pattern.">
          {bar == null && <p className="text-xs text-muted-foreground">No bar marked yet.</p>}
          {draft.isError && <Notice tone="error">{(draft.error as Error).message}</Notice>}
          {draft.isFetching && <p className="text-xs text-muted-foreground">Reading the bar…</p>}
          {draft.data && (
            <div className="space-y-1.5">
              {draft.data.suggestions.map((s, i) => (
                <label key={i} className="flex cursor-pointer items-start gap-2 rounded-md border px-2 py-1.5 text-xs hover:bg-muted/40">
                  <input type="checkbox" className="mt-0.5" checked={chosen(i)} onChange={(e) => setPicked({ ...picked, [i]: e.target.checked })} />
                  <span className="min-w-0">
                    <span className="block font-mono text-[11px]">{conditionText(s.condition)}</span>
                    <span className="block text-[11px] text-muted-foreground">{s.why}</span>
                  </span>
                </label>
              ))}
              {draft.data.filters.sessions && (
                <label className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={useSession} onChange={(e) => setUseSession(e.target.checked)} />
                  Only in the {draft.data.filters.sessions[0]} session
                </label>
              )}
              <p className="text-[11px] text-muted-foreground">{draft.data.note}</p>
            </div>
          )}
        </Section>
        <Section title="3 · Review in the Visual Builder">
          <p className="mb-2 text-xs text-muted-foreground">
            {selected.length} condition{selected.length === 1 ? "" : "s"} selected · enter {side}. Nothing is tested until you run it there.
          </p>
          <Button size="sm" disabled={!selected.length} onClick={() => onUse(side, selected, useSession ? (draft.data?.filters.sessions ?? null) : null)}>
            Use these rules
          </Button>
        </Section>
      </aside>
    </div>
  );
}
