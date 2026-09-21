"use client";

import { useQuery } from "@tanstack/react-query";
import { Blocks, Copy, PenTool, Play, Save, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { CandleChart, type ChartMarker } from "@/components/candle-chart";
import { ChartCreator } from "@/components/research/chart-creator";
import { SearchForm } from "@/components/research/search-form";
import { Notice, PageHeader, Section, Stat } from "@/components/research/bits";
import { JobProgress, useJob } from "@/components/research/jobs";
import { BLANK, StrategyForm, TEMPLATES } from "@/components/research/strategy-form";
import { Button } from "@/components/ui/button";
import { ApiError, fmtPct, research, type StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

const DRAFT_KEY = "ci.strategy-draft.v1";

function loadDraft(): StrategySpec | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? (JSON.parse(raw) as StrategySpec) : null;
  } catch {
    return null;
  }
}

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Mode = "visual" | "ai" | "chart";

function Builder() {
  const params = useSearchParams();
  const fromHash = params.get("spec");
  const source = useQuery({ queryKey: ["strategy", fromHash], queryFn: () => research.strategy(fromHash!), enabled: !!fromHash });
  if (fromHash && !source.data) {
    return source.isError ? (
      <Notice tone="error">Unknown strategy {fromHash}.</Notice>
    ) : (
      <p className="p-4 text-xs text-muted-foreground">Loading strategy…</p>
    );
  }
  // ?spec=<hash> opens a library version; otherwise the last local draft.
  return (
    <Editor
      key={fromHash ?? "draft"}
      initial={fromHash ? source.data!.spec : (loadDraft() ?? BLANK)}
      fromHash={fromHash}
      sourceName={source.data?.name ?? null}
    />
  );
}

function Editor({ initial, fromHash, sourceName }: { initial: StrategySpec; fromHash: string | null; sourceName: string | null }) {
  const router = useRouter();
  const [spec, setSpec] = useState<StrategySpec>(initial);
  const [parent, setParent] = useState<string | null>(fromHash);
  const [saved, setSaved] = useState<string | null>(null);
  const initialMode = useSearchParams().get("mode");
  const [mode, setMode] = useState<Mode>(initialMode === "chart" || initialMode === "ai" ? initialMode : "visual");
  const job = useJob();

  const catalogue = useQuery({ queryKey: ["catalogue"], queryFn: research.catalogue, staleTime: Infinity });

  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(spec));
    } catch {
      /* private mode */
    }
  }, [spec]);

  const debounced = useDebounced(spec, 450);
  const check = useQuery({
    queryKey: ["validate", debounced],
    queryFn: () => research.validate(debounced),
    retry: false,
    enabled: !!catalogue.data,
  });
  const errors = check.error instanceof ApiError ? check.error.details : [];
  const valid = check.data?.ok === true && !check.isFetching;
  const preview = useQuery({
    queryKey: ["preview", debounced],
    queryFn: () => research.preview(debounced),
    retry: false,
    enabled: check.data?.ok === true,
  });

  const markers = useMemo<ChartMarker[]>(
    () =>
      (preview.data?.event_time ?? []).map((t, i) => {
        const long = preview.data!.side[i] > 0;
        return { time: t, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown", color: long ? "#34d399" : "#f87171" };
      }),
    [preview.data],
  );
  const chartAnchor = preview.data?.event_time.length ? preview.data.event_time[preview.data.event_time.length - 1] : null;

  const save = async () => {
    const r = await research.save(spec, parent);
    setSaved(r.spec_hash);
    return r.spec_hash;
  };

  const freq = (t: "A" | "B") =>
    preview.data && preview.data.bars_per_tier[t] ? preview.data.counts[t] / preview.data.bars_per_tier[t] : null;

  if (catalogue.isError) {
    return <Notice tone="error">Strategy catalogue unavailable — is the API running? {String(catalogue.error)}</Notice>;
  }

  return (
    <div className="space-y-3 p-3">
      <PageHeader title="Strategy Lab" subtitle="Three ways to create a strategy — one spec underneath, one honest backtester for all.">
        <div className="flex gap-1">
          {(
            [
              ["visual", "Visual Builder", Blocks, null],
              ["ai", "AI Discovery", Sparkles, null],
              ["chart", "Chart-Based Creator", PenTool, null],
            ] as const
          ).map(([m, label, Icon, phase]) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs",
                mode === m ? "border-primary/60 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" /> {label}
              {phase && <span className="font-mono text-[10px] opacity-70">P{phase}</span>}
            </button>
          ))}
        </div>
      </PageHeader>

      {mode === "ai" && (
        <div className="space-y-3">
          <Notice>
            <b>AI Discovery</b> hands a search to the research engine: it combines building blocks, filters and exits,
            registers every combination, tests them on tier A, validates the best and keeps both accepted and rejected
            ideas with their reasons. Follow it on the{" "}
            <Link className="text-primary hover:underline" href="/pipeline">
              Research Pipeline
            </Link>
            . The AI Assistant can also propose searches; they wait for your approval there.
          </Notice>
          <SearchForm compact onCreated={(s) => router.push(`/pipeline?search=${s.search_id}`)} />
        </div>
      )}
      {mode === "chart" && (
        <ChartCreator
          onUse={(side, conditions, sessions) => {
            setSpec({
              ...spec,
              meta: { ...spec.meta, name: "Chart idea", family: "chart-idea", hypothesis: spec.meta.hypothesis ?? "" },
              entries: [{ side, conditions }],
              filters: { ...spec.filters, sessions },
            });
            setParent(null);
            setMode("visual");
          }}
        />
      )}

      {mode === "visual" && catalogue.data && (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-muted-foreground">Start from:</span>
              <Button size="xs" variant="outline" onClick={() => { setSpec(BLANK); setParent(null); }}>
                Blank
              </Button>
              {TEMPLATES.map((t) => (
                <Button key={t.name} size="xs" variant="outline" title={t.about} onClick={() => { setSpec(t.spec); setParent(null); }}>
                  {t.name}
                </Button>
              ))}
              <span className="text-muted-foreground">(examples to learn with, not recommendations)</span>
            </div>
            {fromHash && sourceName && (
              <Notice>
                Editing a copy of <b>{sourceName}</b> <span className="font-mono">{fromHash}</span>. Any change to the
                rules makes a new version (new hash) in the same family — each one counts as a trial.
              </Notice>
            )}
            <StrategyForm spec={spec} onChange={setSpec} catalogue={catalogue.data} errors={errors} />
          </div>

          <aside className="space-y-3 xl:sticky xl:top-3 xl:self-start">
            <Section title="Check" description="Validated by the engine as you type.">
              <div className="space-y-2 text-xs">
                <p>
                  {check.isFetching ? (
                    <span className="text-muted-foreground">checking…</span>
                  ) : valid ? (
                    <span className="text-emerald-400">✓ valid spec · hash <span className="font-mono">{check.data!.spec_hash}</span></span>
                  ) : (
                    <span className="text-red-400">✗ {check.error ? (check.error as Error).message : "invalid"}</span>
                  )}
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Signals · tier A" value={preview.data?.counts.A.toLocaleString() ?? "—"} hint={`${fmtPct(freq("A"), 2)} of bars`} />
                  <Stat label="Signals · tier B" value={preview.data?.counts.B.toLocaleString() ?? "—"} hint={`${fmtPct(freq("B"), 2)} of bars`} />
                </div>
                <p className="text-muted-foreground">
                  Signals are decisions, not trades (one position at a time). §11 needs ≥ 1,000 trades in A and ≥ 250 in B to
                  promote — a rule firing on less than ~0.5 % of bars rarely gets there.
                </p>
              </div>
            </Section>

            <Section title="Run" description="Save the spec, then test it. Tier C (the newest ~20 %) stays sealed.">
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={!valid} onClick={() => void save()}>
                  <Save /> Save
                </Button>
                {(["A", "B", "AB"] as const).map((t) => (
                  <Button
                    key={t}
                    size="sm"
                    disabled={!valid || job.busy}
                    onClick={() => job.start(async () => { await save(); return research.backtest(spec, t); })}
                  >
                    <Play /> Backtest {t === "AB" ? "A+B" : t}
                  </Button>
                ))}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setSpec({ ...spec, meta: { ...spec.meta, name: `${spec.meta.name} (copy)` } });
                    setParent(check.data?.spec_hash ?? null);
                  }}
                >
                  <Copy /> Clone
                </Button>
              </div>
              {saved && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Saved <span className="font-mono">{saved}</span> ·{" "}
                  <Link className="text-primary hover:underline" href={`/optimize?spec=${saved}`}>Optimize</Link> ·{" "}
                  <Link className="text-primary hover:underline" href={`/validate?spec=${saved}`}>Validate</Link> ·{" "}
                  <button className="text-primary hover:underline" onClick={() => router.push("/strategies")}>Library</button>
                </p>
              )}
              <div className="mt-2">
                <JobProgress job={job.job} error={job.error} />
              </div>
            </Section>

            <Section title="Where it fires" description="Latest signals before the sealed tier. ▲ long · ▼ short (M5).">
              <div className="relative h-[340px] overflow-hidden rounded-lg border">
                {chartAnchor != null ? (
                  <CandleChart timeframe="M5" zone="Asia/Kolkata" markers={markers} anchor={chartAnchor} />
                ) : (
                  <p className="p-3 text-xs text-muted-foreground">{preview.isFetching ? "Finding signals…" : "No signals yet."}</p>
                )}
              </div>
            </Section>
          </aside>
        </div>
      )}
    </div>
  );
}

export default function StrategyLabPage() {
  return (
    <Suspense fallback={<p className="p-4 text-xs text-muted-foreground">Loading…</p>}>
      <Builder />
    </Suspense>
  );
}
