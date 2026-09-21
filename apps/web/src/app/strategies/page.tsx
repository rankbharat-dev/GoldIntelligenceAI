"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { inputCls, Notice, PageHeader, Section, Stat } from "@/components/research/bits";
import { fmtDate, fmtInt, research, type SpecRow } from "@/lib/research";
import { cn } from "@/lib/utils";

function describe(s: SpecRow) {
  const rules = s.spec.entries
    .map((e) => `${e.side}: ${e.conditions.map((c) => `${c.feature} ${c.op} ${Array.isArray(c.value) ? `[${c.value.join(", ")}]` : c.value}`).join(" & ")}`)
    .join(" | ");
  const x = s.spec.exit;
  const exit = [`stop ${x.stop_atr}`, x.target_atr ? `target ${x.target_atr}` : null, x.time_exit_bars ? `${x.time_exit_bars} bars` : null, x.trail_atr ? `trail ${x.trail_atr}` : null]
    .filter(Boolean)
    .join(" · ");
  return { rules, exit };
}

export default function StrategiesPage() {
  const qc = useQueryClient();
  const lib = useQuery({ queryKey: ["strategies"], queryFn: research.strategies });
  const ov = useQuery({ queryKey: ["overview"], queryFn: research.overview });
  const [filter, setFilter] = useState("");
  const [onlyFav, setOnlyFav] = useState(false);

  const rows = (lib.data ?? []).filter(
    (s) => (!onlyFav || s.favourite) && (filter === "" || `${s.name} ${s.family} ${s.spec_hash}`.toLowerCase().includes(filter.toLowerCase())),
  );
  const fav = async (s: SpecRow) => {
    await research.favourite(s.spec_hash, !s.favourite);
    void qc.invalidateQueries({ queryKey: ["strategies"] });
  };

  return (
    <div className="space-y-3 p-3">
      <PageHeader title="My Strategies" subtitle="Every strategy version ever saved, its runs, and how many variants its family has tried." />
      {lib.isError && <Notice tone="error">Library unavailable: {String(lib.error)}</Notice>}

      {ov.data && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Strategies saved" value={fmtInt(lib.data?.length)} />
          <Stat label="Families" value={fmtInt(ov.data.families.length)} />
          <Stat label="Variants tried (all families)" value={fmtInt(ov.data.families.reduce((a, f) => a + f.trials, 0))} hint="the trial count behind every Deflated Sharpe" />
          <Stat label="Holdouts used" value={fmtInt(ov.data.families.filter((f) => f.holdout_used).length)} hint="one per family, ever" />
        </div>
      )}

      <Section
        title="Library"
        actions={
          <div className="flex items-center gap-2">
            <input className={cn(inputCls, "w-48")} placeholder="Search…" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <button
              onClick={() => setOnlyFav(!onlyFav)}
              aria-pressed={onlyFav}
              className={cn("rounded-md border px-2 py-1 text-xs", onlyFav ? "border-primary/60 text-primary" : "text-muted-foreground")}
            >
              ★ only
            </button>
            <Link href="/strategy-lab" className="rounded-md border border-primary/50 px-2 py-1 text-xs text-primary hover:bg-primary/10">
              + New
            </Link>
          </div>
        }
      >
        {!rows.length ? (
          <p className="text-xs text-muted-foreground">{lib.isLoading ? "Loading…" : "Nothing here yet — build a strategy in the Strategy Lab."}</p>
        ) : (
          <div className="space-y-2">
            {rows.map((s) => {
              const d = describe(s);
              return (
                <div key={s.spec_hash} className="rounded-lg border p-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <button aria-label={s.favourite ? "Unfavourite" : "Favourite"} onClick={() => void fav(s)}>
                      <Star className={cn("size-4", s.favourite ? "fill-primary text-primary" : "text-muted-foreground")} />
                    </button>
                    <span className="text-sm font-medium">{s.name}</span>
                    <span className="rounded border px-1.5 text-[11px] text-muted-foreground">{s.family}</span>
                    <span className="font-mono text-[11px] text-muted-foreground">{s.spec_hash}</span>
                    {s.parent_hash && <span className="text-[11px] text-muted-foreground">from {s.parent_hash.slice(0, 8)}</span>}
                    <span className="ml-auto text-[11px] text-muted-foreground">
                      {fmtDate(s.created_at)} · {s.runs ?? 0} runs · family trials {s.family_trials ?? 0}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">{d.rules}</p>
                  <p className="font-mono text-[11px] text-muted-foreground">exit: {d.exit}</p>
                  <div className="mt-1.5 flex flex-wrap gap-3 text-xs">
                    <Link className="text-primary hover:underline" href={`/strategy-lab?spec=${s.spec_hash}`}>Edit / clone</Link>
                    <Link className="text-primary hover:underline" href={`/backtest?spec=${s.spec_hash}`}>Backtest</Link>
                    <Link className="text-primary hover:underline" href={`/optimize?spec=${s.spec_hash}`}>Optimize</Link>
                    <Link className="text-primary hover:underline" href={`/validate?spec=${s.spec_hash}`}>Validate</Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {ov.data && (
        <Section title="Families" description="A family is one idea and all its variants. The more variants tried, the higher the bar a winner must clear.">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-normal">Family</th>
                <th className="py-1 text-right font-normal">Variants tried</th>
                <th className="py-1 text-right font-normal">Last</th>
                <th className="py-1 text-right font-normal">Holdout (tier C)</th>
              </tr>
            </thead>
            <tbody>
              {ov.data.families.map((f) => (
                <tr key={f.family} className="border-t border-border/60">
                  <td className="py-1">{f.family}</td>
                  <td className="py-1 text-right font-mono">{f.trials}</td>
                  <td className="py-1 text-right font-mono">{fmtDate(f.last_trial)}</td>
                  <td className={cn("py-1 text-right", f.holdout_used ? "text-amber-300" : "text-muted-foreground")}>
                    {f.holdout_used ? `used · ${f.holdout_strategy?.slice(0, 8)}` : "sealed"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Tiers: A {fmtDate(ov.data.tiers.A.start)} → {fmtDate(ov.data.tiers.A.end)} · B → {fmtDate(ov.data.tiers.B.end)} · C from{" "}
            {fmtDate(ov.data.tiers.C.start)} (frozen {fmtDate(ov.data.split.frozen_utc)})
          </p>
        </Section>
      )}
    </div>
  );
}
