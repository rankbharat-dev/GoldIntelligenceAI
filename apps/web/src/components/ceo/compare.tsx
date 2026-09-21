"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { fmtInt, fmtNum, fmtPct, fmtR, research, type RunRow, type StrategySpec } from "@/lib/research";
import { runHref } from "@/lib/ceo";
import { cn } from "@/lib/utils";

const MAX = 4;

function rules(s: StrategySpec) {
  return s.entries
    .map((e) => `${e.side.toUpperCase()}: ${e.conditions.map((c) => `${c.feature} ${c.op} ${JSON.stringify(c.value)}`).join(" · ")}`)
    .join(" | ");
}

function latest(runs: RunRow[], tier: string) {
  return runs.find((r) => r.kind === "backtest" && r.tier === tier) ?? null;
}

/** Strategy versions side by side: the rules and the latest engine result per tier. Only
 * numbers from stored runs (pessimistic costs — the headline the engine records). */
export function StrategyCompare({ hashes }: { hashes: string[] }) {
  const all = useQuery({ queryKey: ["strategies"], queryFn: research.strategies });
  const families = useMemo(
    () => new Set((all.data ?? []).filter((s) => hashes.includes(s.spec_hash)).map((s) => s.family)),
    [all.data, hashes],
  );
  const versions = (all.data ?? []).filter((s) => families.has(s.family));
  const [picked, setPicked] = useState<string[] | null>(null);
  const chosen = (picked ?? hashes).slice(0, MAX);
  const details = useQueries({
    queries: chosen.map((h) => ({ queryKey: ["strategy", h], queryFn: () => research.strategy(h) })),
  });
  if (!hashes.length) return null;

  const rows: { label: string; get: (d: NonNullable<(typeof details)[number]["data"]>) => React.ReactNode }[] = [
    { label: "Family · version", get: (d) => `${d.family} · ${d.spec_hash}` },
    { label: "Banaya", get: (d) => `${d.created_by}${d.parent_hash ? ` (parent ${d.parent_hash})` : ""}` },
    { label: "Entry rules", get: (d) => <span className="font-mono text-[11px]">{rules(d.spec)}</span> },
    { label: "Sessions", get: (d) => d.spec.filters.sessions?.join(", ") ?? "sab" },
    {
      label: "Stop / target / time",
      get: (d) => `${d.spec.exit.stop_atr} ATR / ${d.spec.exit.target_atr ?? "—"} ATR / ${d.spec.exit.time_exit_bars ?? "—"} bars`,
    },
    { label: "Family trials", get: (d) => fmtInt(d.family_trials) },
    ...(["A", "B", "AB"] as const).flatMap((tier) => [
      {
        label: `Tier ${tier}: trades · expectancy`,
        get: (d: NonNullable<(typeof details)[number]["data"]>) => {
          const r = latest(d.runs, tier);
          if (!r) return <span className="text-muted-foreground">test nahi hua</span>;
          const s = r.summary as Record<string, number | null>;
          return (
            <Link href={runHref(r.run_id)} className="hover:underline">
              {fmtInt(s.n)} · <span className={cn((s.expectancy_r ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(s.expectancy_r)}</span>
            </Link>
          );
        },
      },
      {
        label: `Tier ${tier}: PF · max DD · win`,
        get: (d: NonNullable<(typeof details)[number]["data"]>) => {
          const r = latest(d.runs, tier);
          if (!r) return "—";
          const s = r.summary as Record<string, number | null>;
          return `${fmtNum(s.profit_factor)} · ${fmtNum(s.max_dd_r, 1)} R · ${fmtPct(s.win_rate, 0)}`;
        },
      },
    ]),
  ];

  return (
    <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
      <h3 className="text-sm font-semibold">Strategies compare (versions)</h3>
      <p className="mb-2 text-[11px] text-muted-foreground">
        Same family ke saare versions. {MAX} tak chuno. Numbers engine ke stored runs se (pessimistic costs).
      </p>
      {versions.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {versions.map((v) => {
            const on = chosen.includes(v.spec_hash);
            return (
              <button
                key={v.spec_hash}
                type="button"
                aria-pressed={on}
                onClick={() => {
                  const cur = picked ?? hashes;
                  setPicked(on ? cur.filter((h) => h !== v.spec_hash) : [...cur, v.spec_hash].slice(-MAX));
                }}
                className={cn(
                  "rounded-md border px-2 py-0.5 text-[11px]",
                  on ? "border-primary/60 bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {v.name}
              </button>
            );
          })}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-xs">
          <thead>
            <tr className="text-left">
              <th className="w-40 py-1 pr-2 font-normal text-muted-foreground"></th>
              {details.map((d, i) => (
                <th key={chosen[i]} className="py-1 pr-2 font-semibold">
                  {d.data?.name ?? chosen[i]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-border/60 align-top">
                <td className="py-1 pr-2 text-muted-foreground">{row.label}</td>
                {details.map((d, i) => (
                  <td key={chosen[i]} className="py-1 pr-2 tabular-nums">
                    {d.data ? row.get(d.data) : "…"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
