"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Catalogue, Condition, Op, StrategySpec } from "@/lib/research";

import { inputCls } from "./bits";
import { BLANK, defaultValue, FeatureSelect, OP_LABEL, opsFor, ValueInput } from "./strategy-form";

const DRAFT_KEY = "ci.strategy-draft.v1"; // same key the Strategy Lab reads its draft from

/** A list of `feature op value` rows (all must hold) — the entry-rule editor without the rest of a spec. */
export function ConditionList({
  conditions,
  onChange,
  catalogue,
  max = 8,
}: {
  conditions: Condition[];
  onChange: (c: Condition[]) => void;
  catalogue: Catalogue;
  max?: number;
}) {
  const byName = new Map(catalogue.features.map((f) => [f.name, f]));
  const set = (i: number, c: Condition) => onChange(conditions.map((x, j) => (j === i ? c : x)));
  return (
    <div className="space-y-2">
      {conditions.map((c, i) => {
        const f = byName.get(c.feature);
        return (
          <div key={i} className="space-y-1">
            <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,1.2fr)_auto] items-start gap-1.5">
              <FeatureSelect
                value={c.feature}
                catalogue={catalogue}
                onChange={(name) => {
                  const nf = byName.get(name);
                  const op = opsFor(nf).includes(c.op) ? c.op : opsFor(nf)[0];
                  set(i, { feature: name, op, value: defaultValue(nf, op) });
                }}
              />
              <select
                className={inputCls}
                aria-label="Operator"
                value={c.op}
                onChange={(e) => {
                  const op = e.target.value as Op;
                  set(i, { ...c, op, value: defaultValue(f, op) });
                }}
              >
                {opsFor(f).map((o) => (
                  <option key={o} value={o}>
                    {OP_LABEL[o]}
                  </option>
                ))}
              </select>
              <ValueInput cond={c} feature={f} catalogue={catalogue} onChange={(v) => set(i, { ...c, value: v })} />
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Remove condition"
                disabled={conditions.length === 1}
                onClick={() => onChange(conditions.filter((_, j) => j !== i))}
              >
                <Trash2 />
              </Button>
            </div>
            {f && <p className="text-[11px] leading-snug text-muted-foreground">{f.description}</p>}
          </div>
        );
      })}
      {conditions.length < max && (
        <Button size="xs" variant="ghost" onClick={() => onChange([...conditions, { feature: "close_loc", op: ">", value: 0.7 }])}>
          <Plus /> Condition
        </Button>
      )}
    </div>
  );
}

export function conditionText(c: Condition) {
  const v = Array.isArray(c.value) ? (c.op === "between" ? `${c.value[0]} … ${c.value[1]}` : c.value.join(", ")) : String(c.value);
  return `${c.feature} ${OP_LABEL[c.op]} ${v}`;
}

export function ConditionChips({ conditions }: { conditions: Condition[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {conditions.map((c, i) => (
        <span key={i} className="rounded border bg-background/40 px-1.5 py-0.5 font-mono text-[10.5px]">
          {conditionText(c)}
        </span>
      ))}
    </span>
  );
}

/** Put a spec built from conditions into the Strategy Lab draft, ready for review. */
export function toBuilderDraft(
  name: string,
  side: "long" | "short",
  conditions: Condition[],
  exit: { stop_atr: number; target_atr: number; horizon_bars: number },
  hypothesis = "",
  filters: StrategySpec["filters"] = {},
): StrategySpec {
  const family = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50) || "chart-idea";
  const spec: StrategySpec = {
    ...BLANK,
    meta: { name: name.slice(0, 80), family, hypothesis, created_by: "owner" },
    entries: [{ side, conditions }],
    filters,
    exit: { stop_atr: exit.stop_atr, target_atr: exit.target_atr, time_exit_bars: exit.horizon_bars, trail_atr: null, flat_before_weekend: true },
  };
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(spec));
  } catch {
    /* private mode: the Strategy Lab starts blank */
  }
  return spec;
}
