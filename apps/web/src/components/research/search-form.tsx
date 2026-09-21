"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Field, inputCls, Notice, NumberInput, Section } from "@/components/research/bits";
import { ConditionChips } from "@/components/research/conditions";
import { Button } from "@/components/ui/button";
import { pipeline, type SearchBlock, type SearchRec, type SearchSpaceDef } from "@/lib/research";
import { cn } from "@/lib/utils";

// Filter options offered as whole choices; each chosen option becomes one axis value.
const SESSION_OPTIONS: { key: string; label: string; value: string[] | null }[] = [
  { key: "any", label: "any session", value: null },
  { key: "london", label: "London + overlap", value: ["london", "london_ny_overlap"] },
  { key: "ny", label: "New York + overlap", value: ["new_york", "london_ny_overlap"] },
  { key: "asian", label: "Asian", value: ["asian"] },
];
const VOL_OPTIONS: { key: string; label: string; value: string[] | null }[] = [
  { key: "any", label: "any volatility", value: null },
  { key: "high", label: "high only", value: ["high"] },
  { key: "lowmid", label: "low + mid", value: ["low", "mid"] },
];

function parseNums(text: string, int = false): number[] {
  return text
    .split(",")
    .map((x) => Number(x.trim()))
    .filter((x) => Number.isFinite(x) && x > 0)
    .map((x) => (int ? Math.round(x) : x));
}

function Toggle<T extends string>({ options, value, onChange }: { options: { key: T; label: string }[]; value: Set<T>; onChange: (v: Set<T>) => void }) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((o) => {
        const on = value.has(o.key);
        return (
          <button
            key={o.key}
            type="button"
            aria-pressed={on}
            onClick={() => {
              const n = new Set(value);
              if (on) n.delete(o.key);
              else n.add(o.key);
              if (n.size) onChange(n);
            }}
            className={cn(
              "rounded-md border px-2 py-0.5 text-xs",
              on ? "border-primary/60 bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);

/** Define a search: which building blocks, which filters and exits to combine, the budget. */
export function SearchForm({ onCreated, compact = false }: { onCreated: (s: SearchRec) => void; compact?: boolean }) {
  const space = useQuery({ queryKey: ["search-space"], queryFn: pipeline.space, staleTime: 60_000 });
  const [name, setName] = useState("Behaviour library × sessions × exits");
  const [hyp, setHyp] = useState("Registered structure / candle behaviours, filtered by session and volatility, with wider exits so costs are a smaller share of 1 R.");
  const [picked, setPicked] = useState<Set<number> | null>(null);
  const [sessions, setSessions] = useState<Set<string>>(new Set(["any", "london", "ny"]));
  const [vols, setVols] = useState<Set<string>>(new Set(["any"]));
  const [align, setAlign] = useState<Set<"off" | "on">>(new Set(["off", "on"]));
  const [stops, setStops] = useState("1.5, 2.5");
  const [targets, setTargets] = useState("2, 3");
  const [times, setTimes] = useState("24, 48");
  const [method, setMethod] = useState<SearchSpaceDef["method"]>("random");
  const [maxTrials, setMaxTrials] = useState(120);
  const [maxMinutes, setMaxMinutes] = useState(90);
  const [minTrades, setMinTrades] = useState(300);
  const [topK, setTopK] = useState(3);
  const [mode, setMode] = useState<"approve" | "auto">("approve");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const blocks: SearchBlock[] = space.data?.blocks ?? [];
  const chosen = picked ?? new Set(blocks.map((_, i) => i).filter((i) => !/compression/.test(blocks[i].behaviour ?? "")));
  const def: SearchSpaceDef = {
      name,
      family: `engine-${slug(name)}`.slice(0, 60),
      hypothesis: hyp,
      blocks: blocks.filter((_, i) => chosen.has(i)).map((b) => ({ label: b.label, side: b.side, conditions: b.conditions, pattern_id: b.pattern_id })),
      sessions: SESSION_OPTIONS.filter((o) => sessions.has(o.key)).map((o) => o.value),
      vol_regimes: VOL_OPTIONS.filter((o) => vols.has(o.key)).map((o) => o.value),
      htf_align: [...align].map((a) => a === "on"),
      stop_atr: parseNums(stops),
      target_atr: parseNums(targets),
      time_exit_bars: parseNums(times, true),
      method,
      max_trials: maxTrials,
      max_minutes: maxMinutes,
      min_trades_a: minTrades,
      top_k: topK,
  };
  const size =
    def.blocks.length * def.sessions.length * def.vol_regimes.length * def.htf_align.length * def.stop_atr.length * def.target_atr.length * def.time_exit_bars.length;
  const tested = Math.min(size, maxTrials);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      onCreated(await pipeline.create(def, mode));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (space.isError) return <Notice tone="error">Search space unavailable: {String(space.error)}</Notice>;
  return (
    <Section
      title="New search"
      description="The engine tests every combination you allow (up to the budget) on tier A, then runs the best through full validation. Every hypothesis is registered before it is tested and counts as a trial."
    >
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Name" hint={`family: ${def.family}`}>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Hypothesis (why should any of this work?)">
            <input className={inputCls} value={hyp} onChange={(e) => setHyp(e.target.value)} />
          </Field>
        </div>
        <Field label={`Building blocks · ${chosen.size} of ${blocks.length} registered behaviours`}>
          <div className={cn("grid gap-1 overflow-y-auto rounded-md border p-1.5", compact ? "max-h-40" : "max-h-64", "sm:grid-cols-2")}>
            {blocks.map((b, i) => (
              <label key={b.pattern_id ?? i} className="flex cursor-pointer items-start gap-2 rounded px-1 py-0.5 text-xs hover:bg-muted/40">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={chosen.has(i)}
                  onChange={(e) => {
                    const n = new Set(chosen);
                    if (e.target.checked) n.add(i);
                    else n.delete(i);
                    setPicked(n);
                  }}
                />
                <span className="min-w-0">
                  <span className="block">
                    {b.label} <span className={b.side === "long" ? "text-emerald-300" : "text-red-300"}>{b.side}</span>
                  </span>
                  {!compact && <ConditionChips conditions={b.conditions} />}
                </span>
              </label>
            ))}
          </div>
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Sessions to try">
            <Toggle options={SESSION_OPTIONS} value={sessions} onChange={setSessions} />
          </Field>
          <Field label="Volatility to try">
            <Toggle options={VOL_OPTIONS} value={vols} onChange={setVols} />
          </Field>
          <Field label="H1 swing-trend alignment">
            <Toggle
              options={[
                { key: "off" as const, label: "without" },
                { key: "on" as const, label: "with (long only in H1 uptrend…)" },
              ]}
              value={align}
              onChange={setAlign}
            />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Field label="Stops (× ATR)" hint="comma separated">
            <input className={inputCls} value={stops} onChange={(e) => setStops(e.target.value)} />
          </Field>
          <Field label="Targets (× ATR)">
            <input className={inputCls} value={targets} onChange={(e) => setTargets(e.target.value)} />
          </Field>
          <Field label="Time exits (M5 bars)">
            <input className={inputCls} value={times} onChange={(e) => setTimes(e.target.value)} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Field label="Method">
            <select className={inputCls} value={method} onChange={(e) => setMethod(e.target.value as SearchSpaceDef["method"])}>
              <option value="grid">grid (all)</option>
              <option value="random">random sample</option>
              <option value="evolutionary">evolutionary</option>
            </select>
          </Field>
          <Field label="Max trials">
            <NumberInput value={maxTrials} step={10} min={1} max={600} onChange={(v) => setMaxTrials(Math.round(v ?? 120))} />
          </Field>
          <Field label="Max minutes">
            <NumberInput value={maxMinutes} step={10} min={1} max={720} onChange={(v) => setMaxMinutes(Math.round(v ?? 90))} />
          </Field>
          <Field label="Screen floor (trades in A)">
            <NumberInput value={minTrades} step={50} min={10} onChange={(v) => setMinTrades(Math.round(v ?? 300))} />
          </Field>
          <Field label="Validate top">
            <NumberInput value={topK} step={1} min={0} max={10} onChange={(v) => setTopK(Math.round(v ?? 3))} />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span>
            Space: <b className="font-mono">{size.toLocaleString()}</b> combinations → <b className="font-mono">{tested}</b> trials on family{" "}
            <span className="font-mono">{def.family}</span>
          </span>
          <span className="text-muted-foreground">More trials = a higher bar: the Deflated Sharpe compares the winner with the best that luck alone would give after {tested} tries.</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className={cn(inputCls, "w-auto")} value={mode} onChange={(e) => setMode(e.target.value as "approve" | "auto")} aria-label="Mode">
            <option value="approve">register, I approve before it runs</option>
            <option value="auto">register and run now (unattended)</option>
          </select>
          <Button size="sm" disabled={busy || !def.blocks.length || !size} onClick={() => void submit()}>
            Register search
          </Button>
          {error && <span className="text-xs text-red-400">{error}</span>}
        </div>
      </div>
    </Section>
  );
}
