"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Catalogue, CatalogueFeature, Condition, Op, Scalar, StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

import { Chips, Field, inputCls, NumberInput, Section } from "./bits";

const NUMERIC_OPS: Op[] = [">", ">=", "<", "<=", "==", "!=", "between", "in", "not_in"];
const CATEGORY_OPS: Op[] = ["==", "!=", "in", "not_in"];
export const OP_LABEL: Record<Op, string> = {
  ">": ">",
  ">=": "≥",
  "<": "<",
  "<=": "≤",
  "==": "=",
  "!=": "≠",
  between: "between",
  in: "is one of",
  not_in: "is not one of",
};
const WEEKDAYS = [1, 2, 3, 4, 5] as const;
const DAY = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

export const BLANK: StrategySpec = {
  meta: { name: "My strategy", family: "my-idea", hypothesis: "", created_by: "owner" },
  entries: [{ side: "long", conditions: [{ feature: "close_loc", op: ">", value: 0.8 }] }],
  filters: {},
  exit: { stop_atr: 1, target_atr: 1.5, time_exit_bars: 24, trail_atr: null, flat_before_weekend: true },
  sizing: { risk_pct: 1, initial_equity_usd: 10000 },
};

// Examples to learn the builder with — starting points, not recommendations.
export const TEMPLATES: { name: string; about: string; spec: StrategySpec }[] = [
  {
    name: "Three-candle reversal",
    about: "Down-down-up closing near the high → long; the mirror → short.",
    spec: {
      meta: { name: "Three-candle reversal", family: "three-candle-reversal", hypothesis: "A strong close after two opposite candles marks a short-term turn.", created_by: "owner" },
      entries: [
        { side: "long", conditions: [{ feature: "dirs_3", op: "==", value: "DDU" }, { feature: "close_loc", op: ">", value: 0.7 }] },
        { side: "short", conditions: [{ feature: "dirs_3", op: "==", value: "UUD" }, { feature: "close_loc", op: "<", value: 0.3 }] },
      ],
      filters: {},
      exit: { stop_atr: 1, target_atr: 1.5, time_exit_bars: 24, trail_atr: null, flat_before_weekend: true },
      sizing: { risk_pct: 1, initial_equity_usd: 10000 },
    },
  },
  {
    name: "London open momentum",
    about: "First hour of London, strong 5-bar push in the H1 trend direction.",
    spec: {
      meta: { name: "London open momentum", family: "london-momentum", hypothesis: "Early-London pushes aligned with the H1 trend continue.", created_by: "owner" },
      entries: [
        {
          side: "long",
          conditions: [
            { feature: "min_since_london_open", op: "between", value: [0, 60] },
            { feature: "ret5_atr", op: ">", value: 1.0 },
            { feature: "h1_trend_atr", op: ">", value: 0 },
          ],
        },
        {
          side: "short",
          conditions: [
            { feature: "min_since_london_open", op: "between", value: [0, 60] },
            { feature: "ret5_atr", op: "<", value: -1.0 },
            { feature: "h1_trend_atr", op: "<", value: 0 },
          ],
        },
      ],
      filters: { sessions: ["london", "london_ny_overlap"] },
      exit: { stop_atr: 1.5, target_atr: 2, time_exit_bars: 36, trail_atr: null, flat_before_weekend: true },
      sizing: { risk_pct: 1, initial_equity_usd: 10000 },
    },
  },
];

export function opsFor(f: CatalogueFeature | undefined): Op[] {
  return f?.numeric ? NUMERIC_OPS : CATEGORY_OPS;
}

export function defaultValue(f: CatalogueFeature | undefined, op: Op): Scalar | Scalar[] {
  if (op === "between") return [0, 1];
  if (op === "in" || op === "not_in") return f?.unit === "bool" ? [true] : f?.numeric ? [1] : [""];
  if (f?.unit === "bool") return true;
  return f?.numeric ? 0 : "";
}

function parseList(text: string, numeric: boolean): Scalar[] {
  return text
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => (numeric ? Number(x) : x === "true" ? true : x === "false" ? false : x));
}

export function ValueInput({
  cond,
  feature,
  catalogue,
  onChange,
}: {
  cond: Condition;
  feature: CatalogueFeature | undefined;
  catalogue: Catalogue;
  onChange: (v: Scalar | Scalar[]) => void;
}) {
  const v = cond.value;
  if (cond.op === "between") {
    const [lo, hi] = Array.isArray(v) ? v : [0, 1];
    return (
      <div className="flex gap-1">
        <NumberInput aria-label="From" value={Number(lo)} onChange={(x) => onChange([x ?? 0, hi])} />
        <NumberInput aria-label="To" value={Number(hi)} onChange={(x) => onChange([lo, x ?? 0])} />
      </div>
    );
  }
  if (cond.op === "in" || cond.op === "not_in") {
    const choices = feature?.name === "session" ? catalogue.sessions : feature?.name === "vol_regime" ? catalogue.vol_regimes : null;
    if (choices) {
      return <Chips options={choices} value={(Array.isArray(v) ? v : []) as string[]} onChange={(x) => onChange(x ?? [])} />;
    }
    return (
      <input
        className={inputCls}
        aria-label="Values, comma separated"
        placeholder="comma separated, e.g. DDU, UUD"
        defaultValue={Array.isArray(v) ? v.join(", ") : String(v)}
        onBlur={(e) => onChange(parseList(e.target.value, !!feature?.numeric))}
      />
    );
  }
  if (feature?.unit === "bool") {
    return (
      <select className={inputCls} aria-label="Value" value={String(v)} onChange={(e) => onChange(e.target.value === "true")}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (feature?.name === "session" || feature?.name === "vol_regime") {
    const choices = feature.name === "session" ? catalogue.sessions : catalogue.vol_regimes;
    return (
      <select className={inputCls} aria-label="Value" value={String(v)} onChange={(e) => onChange(e.target.value)}>
        {choices.map((c) => (
          <option key={c}>{c}</option>
        ))}
      </select>
    );
  }
  if (feature?.numeric) return <NumberInput aria-label="Value" value={Number(v)} onChange={(x) => onChange(x ?? 0)} />;
  return <input className={inputCls} aria-label="Value" value={String(v)} onChange={(e) => onChange(e.target.value)} />;
}

export function FeatureSelect({ value, catalogue, onChange }: { value: string; catalogue: Catalogue; onChange: (v: string) => void }) {
  const groups = Object.entries(catalogue.groups);
  return (
    <select className={inputCls} aria-label="Feature" value={value} onChange={(e) => onChange(e.target.value)}>
      {groups.map(([g, label]) => (
        <optgroup key={g} label={label}>
          {catalogue.features
            .filter((f) => f.group === g)
            .map((f) => (
              <option key={f.name} value={f.name}>
                {f.name}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

export function StrategyForm({
  spec,
  onChange,
  catalogue,
  errors,
}: {
  spec: StrategySpec;
  onChange: (s: StrategySpec) => void;
  catalogue: Catalogue;
  errors: { loc: string; msg: string }[];
}) {
  const byName = new Map(catalogue.features.map((f) => [f.name, f]));
  const set = (patch: Partial<StrategySpec>) => onChange({ ...spec, ...patch });

  const setCond = (ei: number, ci: number, c: Condition) =>
    set({
      entries: spec.entries.map((e, i) =>
        i !== ei ? e : { ...e, conditions: e.conditions.map((x, j) => (j === ci ? c : x)) },
      ),
    });

  return (
    <div className="space-y-3">
      <Section title="1 · Idea" description="Name it, give it a family (variants of one idea share a family and its trial count), and write the hypothesis before you look at results.">
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Name">
            <input className={inputCls} value={spec.meta.name} onChange={(e) => set({ meta: { ...spec.meta, name: e.target.value } })} />
          </Field>
          <Field label="Family" hint="lowercase-with-dashes; the trial counter is per family">
            <input
              className={inputCls}
              value={spec.meta.family}
              onChange={(e) => set({ meta: { ...spec.meta, family: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "-") } })}
            />
          </Field>
          <Field label="Hypothesis (pre-registration)" className="sm:col-span-2">
            <textarea
              className={cn(inputCls, "h-16 py-1.5")}
              value={spec.meta.hypothesis ?? ""}
              placeholder="What behaviour do you expect, and why? Written before testing."
              onChange={(e) => set({ meta: { ...spec.meta, hypothesis: e.target.value } })}
            />
          </Field>
        </div>
      </Section>

      <Section
        title="2 · Entry rules"
        description="Checked at the close of every M5 bar; the entry fills at the next M1 open. Inside a rule every condition must hold; any rule can trigger."
        actions={
          spec.entries.length < 4 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => set({ entries: [...spec.entries, { side: "short", conditions: [{ feature: "close_loc", op: "<", value: 0.2 }] }] })}
            >
              <Plus /> Rule
            </Button>
          )
        }
      >
        <div className="space-y-3">
          {spec.entries.map((e, ei) => (
            <div key={ei} className="rounded-lg border p-2.5">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Rule {ei + 1} · enter</span>
                {(["long", "short"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={e.side === s}
                    onClick={() => set({ entries: spec.entries.map((x, i) => (i === ei ? { ...x, side: s } : x)) })}
                    className={cn(
                      "rounded-md border px-2 py-0.5 text-xs font-medium",
                      e.side === s ? (s === "long" ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-300" : "border-red-500/60 bg-red-500/15 text-red-300") : "text-muted-foreground",
                    )}
                  >
                    {s}
                  </button>
                ))}
                {spec.entries.length > 1 && (
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    className="ml-auto"
                    aria-label="Remove rule"
                    onClick={() => set({ entries: spec.entries.filter((_, i) => i !== ei) })}
                  >
                    <Trash2 />
                  </Button>
                )}
              </div>
              <div className="space-y-2">
                {e.conditions.map((c, ci) => {
                  const f = byName.get(c.feature);
                  const ops = opsFor(f);
                  return (
                    <div key={ci} className="space-y-1">
                      <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,1.2fr)_auto] items-start gap-1.5">
                        <FeatureSelect
                          value={c.feature}
                          catalogue={catalogue}
                          onChange={(name) => {
                            const nf = byName.get(name);
                            const op = opsFor(nf).includes(c.op) ? c.op : opsFor(nf)[0];
                            setCond(ei, ci, { feature: name, op, value: defaultValue(nf, op) });
                          }}
                        />
                        <select
                          className={inputCls}
                          aria-label="Operator"
                          value={c.op}
                          onChange={(ev) => {
                            const op = ev.target.value as Op;
                            setCond(ei, ci, { ...c, op, value: defaultValue(f, op) });
                          }}
                        >
                          {ops.map((o) => (
                            <option key={o} value={o}>
                              {OP_LABEL[o]}
                            </option>
                          ))}
                        </select>
                        <ValueInput cond={c} feature={f} catalogue={catalogue} onChange={(v) => setCond(ei, ci, { ...c, value: v })} />
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label="Remove condition"
                          disabled={e.conditions.length === 1}
                          onClick={() =>
                            set({
                              entries: spec.entries.map((x, i) => (i === ei ? { ...x, conditions: x.conditions.filter((_, j) => j !== ci) } : x)),
                            })
                          }
                        >
                          <Trash2 />
                        </Button>
                      </div>
                      {f && (
                        <p className="text-[11px] leading-snug text-muted-foreground">
                          {f.description} <span className="opacity-70">· {f.unit}</span>
                        </p>
                      )}
                    </div>
                  );
                })}
                {e.conditions.length < 12 && (
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() =>
                      set({
                        entries: spec.entries.map((x, i) =>
                          i === ei ? { ...x, conditions: [...x.conditions, { feature: "range_atr", op: ">", value: 1 }] } : x,
                        ),
                      })
                    }
                  >
                    <Plus /> Condition
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="3 · Filters" description={`Always on: ${catalogue.always_on}. Leave a filter empty for "any".`}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Sessions">
            <Chips options={catalogue.sessions} value={spec.filters.sessions} onChange={(v) => set({ filters: { ...spec.filters, sessions: v } })} />
          </Field>
          <Field label="Volatility regime">
            <Chips options={catalogue.vol_regimes} value={spec.filters.vol_regimes} onChange={(v) => set({ filters: { ...spec.filters, vol_regimes: v } })} />
          </Field>
          <Field label="Weekdays">
            <Chips options={WEEKDAYS} label={(d) => DAY[d]} value={spec.filters.weekdays} onChange={(v) => set({ filters: { ...spec.filters, weekdays: v } })} />
          </Field>
          <Field label="Max spread ÷ its 5-day median" hint="e.g. 1.5 skips bars with an unusually wide spread">
            <NumberInput value={spec.filters.max_spread_rel ?? null} onChange={(v) => set({ filters: { ...spec.filters, max_spread_rel: v } })} placeholder="any" />
          </Field>
          <Field label="Hours (UTC)" className="sm:col-span-2">
            <Chips options={HOURS} value={spec.filters.hours_utc} onChange={(v) => set({ filters: { ...spec.filters, hours_utc: v } })} />
          </Field>
        </div>
      </Section>

      <Section title="4 · Exit" description="Distances are multiples of ATR(14) at the decision bar. Stops and targets are resolved on the M1 path.">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label="Stop (× ATR)">
            <NumberInput value={spec.exit.stop_atr} min={0.1} onChange={(v) => set({ exit: { ...spec.exit, stop_atr: v ?? 1 } })} />
          </Field>
          <Field label="Target (× ATR)" hint="empty = none">
            <NumberInput value={spec.exit.target_atr} min={0.1} placeholder="none" onChange={(v) => set({ exit: { ...spec.exit, target_atr: v } })} />
          </Field>
          <Field label="Time exit (M5 bars)" hint="24 = 2 hours">
            <NumberInput value={spec.exit.time_exit_bars} step={1} min={1} placeholder="none" onChange={(v) => set({ exit: { ...spec.exit, time_exit_bars: v == null ? null : Math.round(v) } })} />
          </Field>
          <Field label="Trailing stop (× ATR)" hint="empty = off">
            <NumberInput value={spec.exit.trail_atr} min={0.1} placeholder="off" onChange={(v) => set({ exit: { ...spec.exit, trail_atr: v } })} />
          </Field>
        </div>
        <label className="mt-2 flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={spec.exit.flat_before_weekend}
            onChange={(e) => set({ exit: { ...spec.exit, flat_before_weekend: e.target.checked } })}
          />
          Close before the weekend (Friday 16:50 New York)
        </label>
      </Section>

      <Section title="5 · Sizing" description="Results are reported in R (independent of size) and in USD with this sizing.">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Risk per trade (% of equity)">
            <NumberInput value={spec.sizing.risk_pct} min={0.1} max={5} onChange={(v) => set({ sizing: { ...spec.sizing, risk_pct: v ?? 1 } })} />
          </Field>
          <Field label="Starting equity (USD)">
            <NumberInput value={spec.sizing.initial_equity_usd} step={1000} min={100} onChange={(v) => set({ sizing: { ...spec.sizing, initial_equity_usd: v ?? 10000 } })} />
          </Field>
        </div>
      </Section>

      {errors.length > 0 && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-2 text-xs text-red-300">
          {errors.map((e, i) => (
            <p key={i}>
              <span className="font-mono">{e.loc}</span>: {e.msg}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
