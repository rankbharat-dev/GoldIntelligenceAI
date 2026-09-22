"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { useJob } from "@/components/research/jobs";
import { Help, Pill, TestProgress } from "@/components/simple/ui";
import { explore, fmtPct, fmtR, research, type ScreenRow, type ScreenRun } from "@/lib/research";

// Simple mode · "Market samjho": the pre-registered behaviour library in plain words —
// does gold do anything special after each pattern, before and after costs?

function plainVerdict(r: ScreenRow): { tone: "good" | "warn" | "bad" | "muted"; text: string; why: string } {
  if (!r.sufficient) return { tone: "muted", text: "Data kam hai", why: `Sirf ${r.n} baar hua — kuch kehne ke liye kam.` };
  if (r.discovery_net) return { tone: "good", text: "Kharche ke baad bhi kaam karta", why: "Luck-correction ke baad bhi kharche ke baad positive. Isse strategy banana layak hai." };
  if (r.discovery_gross) return { tone: "warn", text: "Asar hai, par kharcha kha jaata", why: "Pattern ke baad price sach mein ek disha pakadta hai, par itna kam ki spread + commission usse zyada hai." };
  return { tone: "bad", text: "Koi khaas asar nahi", why: "Is pattern ke baad gold wahi karta hai jo kisi bhi aam candle ke baad — luck se alag nahi." };
}

export default function LearnPage() {
  const qc = useQueryClient();
  const lib = useQuery({ queryKey: ["behaviours"], queryFn: explore.behaviours, retry: false });
  const latest = lib.data?.screens.find((s) => s.tier === "A") ?? null;
  const screen = useQuery({
    queryKey: ["run", latest?.run_id],
    queryFn: () => research.run(latest!.run_id) as unknown as Promise<ScreenRun>,
    enabled: !!latest,
    retry: false,
  });
  const job = useJob({ navigate: false });
  // A screen started earlier (another tab, before a reload) is followed too — never start two.
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: research.jobs, refetchInterval: 3000, retry: false });
  const running = (jobs.data ?? []).find((j) => j.kind === "screen" && (j.status === "queued" || j.status === "running")) ?? null;
  const busy = job.busy || !!running;
  const pct = running ? Math.round(running.progress * 100) : job.job ? Math.round(job.job.progress * 100) : null;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (running) wasRunning.current = true;
    else if (wasRunning.current || job.job?.status === "done") {
      wasRunning.current = false;
      void qc.invalidateQueries({ queryKey: ["behaviours"] });
    }
  }, [running, job.job?.status, qc]);

  const about = new Map((lib.data?.patterns ?? []).map((p) => [p.pattern_id, p]));
  // Enough data first, then the strongest after costs.
  const rows = [...(screen.data?.rows ?? [])].sort(
    (a, b) => Number(b.sufficient) - Number(a.sufficient) || (b.mean_r_net ?? -9) - (a.mean_r_net ?? -9),
  );
  const good = rows.filter((r) => r.discovery_net).length;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 md:px-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-bold">Market samjho</h1>
        <p className="max-w-3xl text-muted-foreground">
          Har chart pattern ke baad gold ne asal mein kya kiya — practice data (2021–2024) pe, asli kharchon ke saath. Yeh patterns test se pehle likh
          diye gaye the, taaki baad mein kahani na badli ja sake.
        </p>
      </header>

      {lib.error && <p className="text-red-300">Engine se connect nahi hua: {String(lib.error)}</p>}

      {screen.data && (
        <section className="rounded-2xl border border-primary/40 bg-primary/10 p-5">
          <p className="text-lg font-semibold">
            {rows.length} patterns mein se {good} kharche ke baad bhi kaam karte hain.
          </p>
          <p className="text-sm text-muted-foreground">
            {good === 0
              ? "Seedhi baat: abhi koi akela pattern trade karne layak nahi. Kuch patterns mein asar hai, par kharcha usse bada hai — isliye bade target ya filter ki zaroorat."
              : "Hare wale patterns pe strategy banana layak hai — phir bhi final check zaroori."}{" "}
            Jaanch ki tareekh: {(latest?.created_at ?? "").slice(0, 10)}
          </p>
        </section>
      )}

      {lib.data && !latest && (
        <section className="space-y-3 rounded-2xl border bg-card p-5">
          <p>Abhi tak patterns ki jaanch nahi hui. Ek click mein saare patterns practice data pe check karo (kuch minute lagte hain).</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void job.start(() => explore.screen("A"))}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-5 font-semibold text-primary-foreground disabled:opacity-60"
          >
            Saare patterns check karo
            <ArrowRight className="size-4" />
          </button>
          <TestProgress busy={busy} pct={pct} error={job.error} label="Jaanch chal rahi hai — har pattern practice data pe, asli kharchon ke saath" />
        </section>
      )}

      {rows.length > 0 && (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {rows.map((r) => {
            const v = plainVerdict(r);
            const p = about.get(r.pattern_id);
            return (
              <li key={r.pattern_id} className="flex flex-col gap-3 rounded-2xl border bg-card p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-base font-semibold">{r.name}</p>
                    <p className="text-sm leading-relaxed text-muted-foreground">{p?.description ?? r.behaviour}</p>
                  </div>
                  <Pill tone={v.tone}>{v.text}</Pill>
                </div>
                <p className="text-sm">{v.why}</p>
                <dl className="grid grid-cols-3 gap-2 text-sm">
                  <div className="rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-xs text-muted-foreground">Kitni baar hua</dt>
                    <dd className="font-mono font-semibold">{r.n.toLocaleString()}</dd>
                  </div>
                  <div className="rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-xs text-muted-foreground">Target pehle laga</dt>
                    <dd className="font-mono font-semibold">
                      {fmtPct(r.target_rate, 0)} <span className="text-xs font-normal text-muted-foreground">aam: {fmtPct(r.baseline_target_rate, 0)}</span>
                    </dd>
                  </div>
                  <div className="rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="flex items-center text-xs text-muted-foreground">
                      Kamai / trade
                      <Help term="r" className="-my-1" />
                    </dt>
                    <dd className="font-mono font-semibold">{fmtR(r.mean_r_net, 2)}</dd>
                  </div>
                </dl>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-sm text-muted-foreground">
        Apna pattern test karna ho, ya kisi feature ka poora distribution dekhna ho:{" "}
        <Link href="/explorer" className="text-primary hover:underline">
          Behaviour Explorer (Expert)
        </Link>
        .
      </p>
    </div>
  );
}
