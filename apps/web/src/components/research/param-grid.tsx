"use client";

import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

import { Field, inputCls, NumberInput } from "./bits";

export interface Knob {
  path: string;
  label: string;
  current: number;
}

export interface Range {
  path: string;
  from: number | null;
  to: number | null;
  step: number | null;
}

/** Every numeric knob of a spec, with a readable label. */
export function numericKnobs(spec: StrategySpec): Knob[] {
  const out: Knob[] = [];
  const add = (path: string, label: string, v: unknown) => {
    if (typeof v === "number") out.push({ path, label, current: v });
  };
  add("exit.stop_atr", "Stop (× ATR)", spec.exit.stop_atr);
  add("exit.target_atr", "Target (× ATR)", spec.exit.target_atr);
  add("exit.time_exit_bars", "Time exit (bars)", spec.exit.time_exit_bars);
  add("exit.trail_atr", "Trailing (× ATR)", spec.exit.trail_atr);
  add("filters.max_spread_rel", "Max spread ratio", spec.filters.max_spread_rel);
  spec.entries.forEach((e, i) =>
    e.conditions.forEach((c, j) => {
      const base = `entries.${i}.conditions.${j}.value`;
      if (typeof c.value === "number") add(base, `Rule ${i + 1} (${e.side}) · ${c.feature} ${c.op}`, c.value);
      if (c.op === "between" && Array.isArray(c.value)) {
        add(`${base}.0`, `Rule ${i + 1} · ${c.feature} from`, c.value[0]);
        add(`${base}.1`, `Rule ${i + 1} · ${c.feature} to`, c.value[1]);
      }
    }),
  );
  return out;
}

export function rangeValues(r: Range): number[] {
  const integer = r.path.endsWith("time_exit_bars");
  if (r.from == null || r.to == null || !r.step || r.step <= 0 || r.to < r.from) return [];
  const out: number[] = [];
  for (let v = r.from; v <= r.to + 1e-9 && out.length < 41; v += r.step) out.push(integer ? Math.round(v) : Math.round(v * 1e6) / 1e6);
  return [...new Set(out)];
}

export function toGrid(ranges: Range[]) {
  return ranges.map((r) => ({ path: r.path, values: rangeValues(r) }));
}

export function gridSize(ranges: Range[]) {
  return ranges.length ? ranges.reduce((a, r) => a * Math.max(rangeValues(r).length, 1), 1) : 0;
}

function defaultRange(k: Knob): Range {
  if (k.path.endsWith("time_exit_bars")) {
    return { path: k.path, from: Math.max(1, Math.round(k.current / 2)), to: Math.round(k.current * 1.5), step: Math.max(1, Math.round(k.current / 4)) };
  }
  const base = k.current || 1;
  return { path: k.path, from: +(k.current - Math.abs(base) * 0.5).toFixed(3), to: +(k.current + Math.abs(base) * 0.5).toFixed(3), step: +(Math.abs(base) / 4).toFixed(3) };
}

export function ParamGridEditor({ spec, ranges, onChange }: { spec: StrategySpec; ranges: Range[]; onChange: (r: Range[]) => void }) {
  const knobs = numericKnobs(spec);
  return (
    <div className="space-y-2">
      {ranges.map((r, i) => {
        const k = knobs.find((x) => x.path === r.path);
        const set = (patch: Partial<Range>) => onChange(ranges.map((x, j) => (j === i ? { ...x, ...patch } : x)));
        return (
          <div key={r.path} className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[minmax(0,1.5fr)_repeat(3,minmax(0,1fr))_auto]">
            <p className="col-span-2 truncate text-xs sm:col-span-1 sm:pb-2" title={r.path}>
              {k?.label ?? r.path} <span className="text-muted-foreground">(now {k?.current})</span>
            </p>
            <Field label="From">
              <NumberInput value={r.from} onChange={(v) => set({ from: v })} />
            </Field>
            <Field label="To">
              <NumberInput value={r.to} onChange={(v) => set({ to: v })} />
            </Field>
            <Field label="Step">
              <NumberInput value={r.step} onChange={(v) => set({ step: v })} />
            </Field>
            <Button size="icon-sm" variant="ghost" aria-label="Remove parameter" onClick={() => onChange(ranges.filter((_, j) => j !== i))}>
              <Trash2 />
            </Button>
          </div>
        );
      })}
      {ranges.length < 3 && (
        <select
          className={cn(inputCls, "max-w-md")}
          value=""
          aria-label="Add a parameter"
          onChange={(e) => {
            const k = knobs.find((x) => x.path === e.target.value);
            if (k) onChange([...ranges, defaultRange(k)]);
          }}
        >
          <option value="">+ add a parameter…</option>
          {knobs
            .filter((k) => !ranges.some((r) => r.path === k.path))
            .map((k) => (
              <option key={k.path} value={k.path}>
                {k.label} (now {k.current})
              </option>
            ))}
        </select>
      )}
    </div>
  );
}
