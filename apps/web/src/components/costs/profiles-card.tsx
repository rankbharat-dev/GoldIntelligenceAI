"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { JobProgress, useJob } from "@/components/research/jobs";
import { Button } from "@/components/ui/button";
import { costProfiles, type CostProfileRow } from "@/lib/research";
import { cn } from "@/lib/utils";

const STATUS: Record<string, { text: string; cls: string }> = {
  validated: { text: "✓ validated", cls: "text-emerald-300" },
  provisional: { text: "◐ provisional", cls: "text-amber-200" },
  failed_validation: { text: "✗ failed validation", cls: "text-red-300" },
  missing: { text: "— not built", cls: "text-muted-foreground" },
};

/** Account cost profiles: which account's costs new runs use, and what promotion needs. */
export function ProfilesCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["cost-profiles"], queryFn: costProfiles.get });
  const job = useJob({ navigate: false });
  const [err, setErr] = useState<string | null>(null);
  const [rawTicks, setRawTicks] = useState("");
  if (q.isError) return <p className="px-4 text-xs text-red-400">Cost profiles unavailable: {String(q.error)}</p>;
  if (!q.data) return null;
  const d = q.data;
  const rawArchives = d.raw_archives.filter((a) => a.account_label === "raw" && a.tick_days > 0);
  const switchTo = async (p: string) => {
    setErr(null);
    try {
      await costProfiles.setActive(p);
      await qc.invalidateQueries();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <section className="mx-3 mt-3 rounded-xl bg-card p-3 ring-1 ring-foreground/10">
      <div className="mb-2 flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <h2 className="text-sm font-semibold">Account cost profiles</h2>
          <p className="text-xs text-muted-foreground">
            New backtests, studies and searches use the <b>active</b> profile. Promotion (§15) needs the{" "}
            <b>{d.promotion_profile}</b> profile calibrated from that account&apos;s own ticks — the account you will trade.
          </p>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {d.profiles.map((p: CostProfileRow) => {
          const st = STATUS[p.status] ?? STATUS.missing;
          const active = d.active === p.profile;
          return (
            <div key={p.profile} className={cn("rounded-lg border p-2.5 text-xs", active && "border-primary/50 bg-primary/5")}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{p.profile}</span>
                <span className={st.cls}>{st.text}</span>
                {active ? (
                  <span className="ml-auto rounded border border-primary/50 px-1.5 py-0.5 text-[11px] text-primary">active</span>
                ) : (
                  p.status !== "missing" && (
                    <Button size="xs" variant="outline" className="ml-auto" onClick={() => void switchTo(p.profile)}>
                      Use for new runs
                    </Button>
                  )
                )}
              </div>
              <p className="mt-1 text-muted-foreground">{p.label}</p>
              {p.status !== "missing" && (
                <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
                  <dt className="text-muted-foreground">Commission</dt>
                  <dd className="font-mono">
                    ${p.commission_round_turn_usd?.toFixed(2)} / lot round turn {p.commission_confirmed ? "(stated)" : "(unconfirmed — pessimistic charges $7)"}
                  </dd>
                  <dt className="text-muted-foreground">Spread, last 60 d</dt>
                  <dd className="font-mono">
                    {p.mean_spread_points_last_60_days
                      ? `${p.mean_spread_points_last_60_days.base.toFixed(0)} pts base · ${p.mean_spread_points_last_60_days.pessimistic.toFixed(0)} pess.`
                      : "—"}
                  </dd>
                  <dt className="text-muted-foreground">Spread basis</dt>
                  <dd>{p.spread_basis}</dd>
                  <dt className="text-muted-foreground">Model</dt>
                  <dd className="truncate font-mono">{p.cost_model_id}</dd>
                </dl>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
        <div className="space-y-1.5">
          <p className="text-muted-foreground">
            <b>Provisional Raw</b> (no Raw-account data yet): demo spreads as an upper bound + $10/lot commission. Rebuild
            after changing the commission.
          </p>
          <Button size="xs" variant="outline" disabled={job.busy} onClick={() => job.start(() => costProfiles.build({ action: "provisional-raw", commission_per_lot: 10 }))}>
            Rebuild provisional Raw
          </Button>
        </div>
        <div className="space-y-1.5">
          <p className="text-muted-foreground">
            <b>Calibrate Raw</b> from a Raw Spread demo&apos;s ticks (ingest them first:{" "}
            <code className="font-mono">ci-ingest raw --ticks --account-label raw</code>).
          </p>
          {rawArchives.length ? (
            <div className="flex flex-wrap gap-2">
              <select className="h-7 rounded-md border bg-input/30 px-2" value={rawTicks} onChange={(e) => setRawTicks(e.target.value)} aria-label="Raw tick archive">
                <option value="">choose archive…</option>
                {rawArchives.map((a) => (
                  <option key={a.raw_version} value={a.raw_version}>
                    {a.raw_version} · {a.tick_days} days
                  </option>
                ))}
              </select>
              <Button size="xs" disabled={!rawTicks || job.busy} onClick={() => job.start(() => costProfiles.build({ action: "calibrate-raw", raw_ticks: rawTicks, commission_per_lot: 10 }))}>
                Calibrate Raw
              </Button>
            </div>
          ) : (
            <p className="text-amber-200">No Raw-account tick archive yet (open item A7).</p>
          )}
        </div>
      </div>
      <div className="mt-2">
        <JobProgress job={job.job} error={job.error ?? err} />
      </div>
    </section>
  );
}
