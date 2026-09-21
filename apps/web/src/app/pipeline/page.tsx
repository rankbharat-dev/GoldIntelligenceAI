"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Notice, PageHeader, Section, Stat } from "@/components/research/bits";
import { SearchForm } from "@/components/research/search-form";
import { Button } from "@/components/ui/button";
import { fmtInt, fmtNum, fmtR, pipeline, type Hypothesis, type SearchRec } from "@/lib/research";
import { cn } from "@/lib/utils";

const DRAFT_KEY = "ci.strategy-draft.v1";

const STATUS: Record<Hypothesis["status"], { label: string; cls: string }> = {
  planned: { label: "registered", cls: "text-muted-foreground" },
  passed_screen: { label: "passed screen", cls: "text-sky-300" },
  rejected: { label: "✗ rejected", cls: "text-red-300" },
  not_selected: { label: "not selected", cls: "text-muted-foreground" },
  candidate: { label: "✓ candidate", cls: "text-emerald-300" },
};

function SearchStatus({ s }: { s: SearchRec }) {
  const running = s.status === "running" || s.status === "queued";
  return (
    <span className={cn("rounded border px-1.5 py-0.5 text-[11px]", running ? "border-primary/50 text-primary" : s.status === "done" ? "text-emerald-300" : "text-muted-foreground")}>
      {s.status}
      {running && s.job ? ` · ${Math.round(s.job.progress * 100)}%` : ""}
    </span>
  );
}

function PipelineInner() {
  const params = useSearchParams();
  const router = useRouter();
  const selected = params.get("search");
  const list = useQuery({
    queryKey: ["searches"],
    queryFn: pipeline.list,
    refetchInterval: (q) => (q.state.data?.some((s) => s.status === "running" || s.status === "queued") ? 2000 : 15000),
  });
  return (
    <div className="space-y-3 p-3">
      <PageHeader
        title="Research Pipeline"
        subtitle="The research engine: hypotheses → pre-registration → tests → accepted and rejected, each with its reason. It can run unattended overnight; the guardrails do not change."
      />
      <div className="grid grid-cols-1 gap-3 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 space-y-3">
          <SearchForm onCreated={(s) => router.push(`/pipeline?search=${s.search_id}`)} />
          <Section title="Searches" description="Newest first. Click one for its hypotheses.">
            {!list.data?.length && <p className="text-xs text-muted-foreground">No searches yet.</p>}
            <ul className="space-y-1 text-xs">
              {list.data?.map((s) => (
                <li key={s.search_id}>
                  <Link
                    href={`/pipeline?search=${s.search_id}`}
                    className={cn("flex flex-wrap items-center gap-2 rounded-md border px-2 py-1.5 hover:bg-muted/40", selected === s.search_id && "border-primary/50")}
                  >
                    <span className="font-medium">{s.name}</span>
                    <SearchStatus s={s} />
                    <span className="text-muted-foreground">
                      {s.summary.registered} hypotheses · {s.summary.candidates ?? 0} candidates · {s.created_by}
                    </span>
                    <span className="ml-auto font-mono text-[10px] text-muted-foreground">{s.created_at.slice(0, 16).replace("T", " ")}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Section>
        </div>
        <div className="min-w-0">{selected ? <SearchDetail id={selected} /> : <HowItWorks />}</div>
      </div>
    </div>
  );
}

function HowItWorks() {
  return (
    <Notice>
      <b>How the engine works.</b> 1) You (or the AI assistant) define a search: building blocks × filters × exits. 2) Every
      combination is written down with a timestamp before any test (pre-registration). 3) Each one is backtested on tier A
      with pessimistic costs — this is a <i>trial</i>. Losers are rejected with the reason. 4) The best few go through the
      full Validate run (tier B, walk-forward, Deflated Sharpe at the true trial count, §15 checklist). 5) Anything that
      passes everything except the sealed holdout becomes a <b>candidate</b>; you decide whether to spend its one-time
      tier-C look. Most searches end with zero candidates — that is the honest result, not a bug.
    </Notice>
  );
}

function SearchDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const s = useQuery({
    queryKey: ["search", id],
    queryFn: () => pipeline.get(id),
    refetchInterval: (q) => (q.state.data && (q.state.data.status === "running" || q.state.data.status === "queued") ? 2000 : false),
  });
  const [filter, setFilter] = useState<"all" | Hypothesis["status"]>("all");
  if (s.isError) return <Notice tone="error">Unknown search {id}.</Notice>;
  if (!s.data) return <p className="text-xs text-muted-foreground">Loading…</p>;
  const d = s.data;
  const live = d.live;
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      void qc.invalidateQueries({ queryKey: ["search", id] });
      void qc.invalidateQueries({ queryKey: ["searches"] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  const hyps = d.hypotheses.filter((h) => filter === "all" || h.status === filter);
  const def = d.definition;
  return (
    <div className="space-y-3">
      <Section
        title={d.name}
        description={
          <>
            family <span className="font-mono">{d.family}</span> · {def.method} · {def.blocks.length} blocks · budget {def.max_trials} trials / {def.max_minutes} min · validate top{" "}
            {def.top_k} · by {d.created_by}
            {def.hypothesis ? <> · “{def.hypothesis}”</> : null}
          </>
        }
        actions={
          <div className="flex gap-2">
            {d.status === "proposed" && (
              <Button size="sm" onClick={() => act(() => pipeline.approve(id))}>
                <Play /> Approve & run
              </Button>
            )}
            {(d.status === "running" || d.status === "queued") && (
              <Button size="sm" variant="outline" onClick={() => act(() => pipeline.pause(id))}>
                <Pause /> Pause
              </Button>
            )}
            {d.resumable && (
              <Button size="sm" onClick={() => act(() => pipeline.resume(id))}>
                <RotateCcw /> Resume
              </Button>
            )}
          </div>
        }
      >
        {err && <p className="mb-2 text-xs text-red-400">{err}</p>}
        {d.job && (d.status === "running" || d.status === "queued") && (
          <div className="mb-2 space-y-1 text-xs">
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-all" style={{ width: `${Math.max(3, Math.round(d.job.progress * 100))}%` }} />
            </div>
            <p className="text-muted-foreground">{d.job.message}</p>
          </div>
        )}
        {d.status === "proposed" && (
          <p className="mb-2 text-xs text-amber-200">
            Waiting for your approval. {live.registered} hypotheses are registered (below) — nothing has been tested yet.
          </p>
        )}
        {live.note && <p className="mb-2 text-xs text-muted-foreground">Stopped: {live.note}.</p>}
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <Stat label="Registered" value={fmtInt(live.registered)} hint={`of ${fmtInt(live.space_size)} possible`} />
          <Stat label="Rejected" value={fmtInt(live.counts?.rejected ?? 0)} tone="muted" />
          <Stat label="Not selected" value={fmtInt(live.counts?.not_selected ?? 0)} tone="muted" />
          <Stat label="Candidates" value={fmtInt(live.counts?.candidate ?? 0)} tone={(live.counts?.candidate ?? 0) > 0 ? "good" : undefined} />
          <Stat label="Family trials" value={fmtInt(live.family_trials)} hint="every screened variant" />
          <Stat
            label="Luck bar (SR0)"
            value={fmtNum(live.sr0_expected_max, 3)}
            hint="best per-trade Sharpe luck alone gives at this many trials"
          />
        </div>
      </Section>
      <Section
        title="Hypotheses"
        description="A = tier-A result at pessimistic costs (the screen). B and walk-forward come from the Validate run of the top ones."
        actions={
          <select className="h-7 rounded-md border bg-input/30 px-2 text-xs" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} aria-label="Filter">
            <option value="all">all</option>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        }
      >
        <div className="max-h-[70dvh] overflow-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr className="text-left">
                <th className="py-1 pr-2 font-normal">Hypothesis</th>
                <th className="py-1 pr-2 font-normal">Status</th>
                <th className="py-1 pr-2 text-right font-normal">A trades</th>
                <th className="py-1 pr-2 text-right font-normal">A net R</th>
                <th className="py-1 pr-2 text-right font-normal">B net R</th>
                <th className="py-1 pr-2 text-right font-normal">WF net R</th>
                <th className="py-1 font-normal">Why</th>
              </tr>
            </thead>
            <tbody>
              {hyps.map((h) => {
                const st = STATUS[h.status];
                return (
                  <tr key={h.spec_hash} className="border-t border-border/60 align-top">
                    <td className="py-1.5 pr-2">
                      <p>{h.label}</p>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        {h.spec_hash} · gen {h.generation} ·{" "}
                        <button
                          className="text-primary hover:underline"
                          onClick={() => {
                            try {
                              localStorage.setItem(DRAFT_KEY, JSON.stringify(h.spec));
                            } catch {
                              /* private mode */
                            }
                            router.push("/strategy-lab");
                          }}
                        >
                          open in builder
                        </button>
                        {h.validate_run && (
                          <>
                            {" · "}
                            <Link className="text-primary hover:underline" href={`/validate?run=${h.validate_run}`}>
                              validation
                            </Link>
                          </>
                        )}
                      </p>
                    </td>
                    <td className={cn("py-1.5 pr-2 whitespace-nowrap", st.cls)}>{st.label}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{fmtInt(h.metrics.n)}</td>
                    <td className={cn("py-1.5 pr-2 text-right font-mono", (h.metrics.expectancy_r ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>
                      {h.metrics.expectancy_r == null ? "—" : fmtR(h.metrics.expectancy_r)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">{h.metrics.B_expectancy_r == null ? "—" : fmtR(h.metrics.B_expectancy_r)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{h.metrics.oos_expectancy_r == null ? "—" : fmtR(h.metrics.oos_expectancy_r)}</td>
                    <td className="max-w-[320px] py-1.5 text-[11px] text-muted-foreground">{h.reasons.join(" · ") || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

export default function PipelinePage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <PipelineInner />
    </Suspense>
  );
}
