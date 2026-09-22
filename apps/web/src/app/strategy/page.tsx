"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, Check, CircleDashed, GitBranch, Lock, PlayCircle, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ago } from "@/components/ceo/bits";
import { journey } from "@/components/simple/strategies";
import { Pill, TestProgress, Tracker, useTestRun } from "@/components/simple/ui";
import { reasonsOf } from "@/components/simple/why";
import { ceo } from "@/lib/ceo";
import { checkPlain, CREATED_BY, quickVerdict, ruleWord, SESSION_PLAIN, TIER_PLAIN, VALIDATE_PLAIN, verdictOf, widerExits } from "@/lib/plain";
import { fmtInt, fmtR, research, type BacktestRun, type RunRow, type SpecRow, type StrategySpec, type ValidateRun } from "@/lib/research";
import { cn } from "@/lib/utils";

// My Strategy Lab · one strategy's improvement journey: where it stands, what it is (in
// words), every test it has had, its versions, the final-check status item by item, why
// it failed, and the next honest step. Numbers come from the stored engine runs.

export default function StrategyPage() {
  return (
    <Suspense>
      <StrategyJourneyPage />
    </Suspense>
  );
}

const MIN_PER_BAR = 5;

function specWords(s: StrategySpec): string[] {
  const out: string[] = [];
  for (const e of s.entries) out.push(`${e.side === "long" ? "BUY" : "SELL"} jab: ${e.conditions.map((c) => ruleWord(c.feature, c.op, c.value)).join(" + ")}`);
  const sessions = s.filters.sessions;
  out.push(sessions ? `Sirf ${sessions.map((x) => SESSION_PLAIN[x] ?? x).join(" / ")} session` : "Poora din (koi time filter nahi)");
  const x = s.exit;
  const hold = x.time_exit_bars ? ` · max ${x.time_exit_bars} candles (~${Math.round((x.time_exit_bars * MIN_PER_BAR) / 60)} ghante)` : "";
  out.push(`Stop ${x.stop_atr}× aam candle · target ${x.target_atr ?? "—"}×${hold}`);
  return out;
}

/** What changed from the parent version, in words. */
function diffWords(a: StrategySpec, b: StrategySpec): string[] {
  const out: string[] = [];
  if (a.exit.stop_atr !== b.exit.stop_atr || a.exit.target_atr !== b.exit.target_atr)
    out.push(`stop/target ${a.exit.stop_atr}×/${a.exit.target_atr ?? "—"}× → ${b.exit.stop_atr}×/${b.exit.target_atr ?? "—"}×`);
  if (JSON.stringify(a.filters.sessions ?? null) !== JSON.stringify(b.filters.sessions ?? null)) out.push("session badla");
  if (JSON.stringify(a.entries) !== JSON.stringify(b.entries)) out.push("entry rules badle");
  if (a.exit.time_exit_bars !== b.exit.time_exit_bars) out.push("max time badla");
  return out.length ? out : ["chhota badlaav"];
}

function StrategyJourneyPage() {
  const hash = useSearchParams().get("spec");
  const s = useQuery({ queryKey: ["strategy", hash], queryFn: () => research.strategy(hash!), enabled: !!hash, retry: false });
  const all = useQuery({ queryKey: ["strategies"], queryFn: research.strategies, retry: false });
  if (!hash)
    return (
      <Shell>
        <p className="text-muted-foreground">
          Koi strategy nahi chuni.{" "}
          <Link href="/my" className="text-primary hover:underline">
            Meri strategies
          </Link>{" "}
          se ek kholo.
        </p>
      </Shell>
    );
  if (s.isLoading) return <Shell><p className="text-muted-foreground">Load ho raha hai…</p></Shell>;
  if (s.error || !s.data) return <Shell><p className="text-red-300">Strategy nahi mili: {String(s.error ?? "")}</p></Shell>;
  const row = s.data as SpecRow & { runs: RunRow[]; family_trials: number; holdout: { strategy_id?: string } | null };
  const versions = (all.data ?? []).filter((x) => x.family === row.family);
  return <View row={row} runs={row.runs} trials={row.family_trials} holdoutUsed={!!row.holdout} versions={versions} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-6xl px-4 py-8 md:px-8">{children}</div>;
}

function View({ row, runs, trials, holdoutUsed, versions }: { row: SpecRow; runs: RunRow[]; trials: number; holdoutUsed: boolean; versions: SpecRow[] }) {
  const j = journey(row, runs);
  const bt = j.lastBacktest;
  const va = j.lastValidate;
  const btRun = useQuery({ queryKey: ["run", bt?.run_id], queryFn: () => research.run<BacktestRun>(bt!.run_id), enabled: !!bt });
  const vaRun = useQuery({ queryKey: ["run", va?.run_id], queryFn: () => research.run<ValidateRun>(va!.run_id), enabled: !!va });

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 md:px-8">
      <div className="text-sm text-muted-foreground">
        <Link href="/my" className="hover:text-foreground">
          Meri strategies
        </Link>{" "}
        / <span className="text-foreground">{row.name}</span>
      </div>

      <header className="flex flex-col gap-4 rounded-2xl border bg-card p-6">
        <div className="flex flex-wrap items-start gap-3">
          <div className="mr-auto min-w-0 space-y-1">
            <p className="text-xs font-semibold tracking-[0.18em] text-primary">MY STRATEGY LAB</p>
            <h1 className="text-2xl font-bold md:text-3xl">{row.name}</h1>
            <p className="text-sm text-muted-foreground">
              {CREATED_BY[row.created_by] ?? row.created_by} · {ago(row.created_at)} · idea-family &quot;{row.family}&quot; · {fmtInt(trials)} koshishein (trials)
            </p>
          </div>
          <Pill tone={j.status.tone}>{j.status.text}</Pill>
        </div>
        <Tracker states={j.stages} />
        <ul className="space-y-1 text-sm">
          {specWords(row.spec).map((w) => (
            <li key={w} className="flex gap-2">
              <span className="text-primary">•</span>
              {w}
            </li>
          ))}
        </ul>
        {row.spec.meta.hypothesis && <p className="rounded-xl bg-muted/40 px-4 py-2 text-sm italic text-muted-foreground">&quot;{row.spec.meta.hypothesis}&quot;</p>}
      </header>

      <NextActions row={row} j={j} bt={btRun.data ?? null} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {btRun.data && <FailWhy run={btRun.data} />}
        <Validation va={vaRun.data ?? null} holdoutUsed={holdoutUsed} passedFirst={j.stages[1] === "done"} />
      </div>

      <History runs={runs} />
      <Versions current={row} versions={versions} />
    </div>
  );
}

function NextActions({ row, j, bt }: { row: SpecRow; j: ReturnType<typeof journey>; bt: BacktestRun | null }) {
  const test = useTestRun();
  const router = useRouter();
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const pct = test.job ? Math.round(test.job.progress * 100) : null;
  const v = bt ? verdictOf(bt.results.pessimistic) : null;
  const card = "flex min-h-32 flex-col gap-2 rounded-2xl border p-5 text-left";
  const cta = "mt-auto inline-flex items-center gap-1.5 text-sm font-semibold text-primary";

  const askAI = async () => {
    setErr(null);
    const why = bt ? reasonsOf(bt.results.pessimistic, v!).map((r) => `- ${r.text}`).join("\n") : "";
    try {
      const m = await ceo.create({
        objective: `Strategy "${row.name}" (spec ${row.spec_hash}, family ${row.family}) ko sudhaaro. Pehle test ka haal:\n${why}\nEk independent, pehle se likhi hypothesis banao (naya version, same family taaki trials gine jaayein), practice data pe test karo aur simple Hinglish mein batao ki kya badla aur kyun.`,
        require_plan_approval: true,
      });
      void qc.invalidateQueries({ queryKey: ["ceo"] });
      router.push(`/ceo-lab?mission=${m.mission_id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const items: { key: string; title: string; body: string; cta: string; primary?: boolean; href?: string; onClick?: () => void; icon: typeof PlayCircle }[] = [];
  if (!bt)
    items.push({ key: "test", icon: PlayCircle, title: "Pehla test chalao", body: "Practice data (2021–2024) pe, mehenge kharche ke saath. 1 koshish ginegi.", cta: "Test chalao", primary: true, onClick: () => void test.run(row.spec, "A") });
  if (bt) items.push({ key: "chart", icon: PlayCircle, title: "Chart pe trades dekho", body: "Har trade ki entry, SL, TP aur rule check — verify karo ki trades aapke rules se hi bane.", cta: "Result + chart", href: `/result?run=${bt.run_id}`, primary: v?.kind !== "pass" && j.next.action.kind !== "link" });
  if (j.next.action.kind === "link" && j.next.label !== "Result dekho")
    items.push({ key: "next", icon: ArrowRight, title: j.next.label, body: j.status.text, cta: j.next.label, href: j.next.action.href, primary: true });
  if (bt && v && v.kind !== "pass" && (row.spec.exit.target_atr ?? 99) < 6)
    items.push({ key: "wide", icon: GitBranch, title: "Naya version: bada target (1:3)", body: "Same idea, bada target — kharcha kamai ka chhota hissa ban jaata hai. Naya version, nayi koshish.", cta: "Version banao + test", onClick: () => void test.run(widerExits(row.spec), "A", row.spec_hash) });
  if (bt && v && v.kind !== "pass")
    items.push({ key: "ai", icon: Bot, title: "AI team se sudhaar karwao", body: "Director fail hone ki wajah padh kar ek independent hypothesis banayega. Plan pehle aapko dikhega.", cta: "AI mission banao", onClick: () => void askAI() });

  return (
    <section aria-label="Agla kadam" className="space-y-3">
      <h2 className="text-lg font-bold">Agla kadam</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.slice(0, 3).map((o) => {
          const cls = cn(card, o.primary ? "border-primary/40 bg-primary/10 hover:bg-primary/15" : "bg-card hover:bg-muted/40");
          const body = (
            <>
              <o.icon className="size-5 text-primary" />
              <span className="text-base font-semibold">{o.title}</span>
              <span className="text-sm leading-relaxed text-muted-foreground">{o.body}</span>
              <span className={cta}>
                {o.cta}
                <ArrowRight className="size-4" />
              </span>
            </>
          );
          return o.href ? (
            <Link key={o.key} href={o.href} className={cls}>
              {body}
            </Link>
          ) : (
            <button key={o.key} type="button" disabled={test.busy} onClick={o.onClick} className={cn(cls, "disabled:opacity-60")}>
              {body}
            </button>
          );
        })}
      </div>
      <TestProgress busy={test.busy} pct={pct} error={test.error ?? err} />
    </section>
  );
}

function FailWhy({ run }: { run: BacktestRun }) {
  const m = run.results.pessimistic;
  const v = verdictOf(m);
  const rs = reasonsOf(m, v);
  return (
    <section aria-label="Pehle test ka haal" className="space-y-3 rounded-2xl border bg-card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">Pehla test: {v.kind === "pass" ? "pass" : "kyun nahi chala?"}</h2>
        <span className={cn("font-mono font-bold", (m.expectancy_r ?? 0) > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(m.expectancy_r, 2)} / trade</span>
      </div>
      <p className="text-sm">{v.title}</p>
      <ul className="space-y-2">
        {rs.map((r, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm leading-relaxed">
            <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", r.tone === "good" && "bg-emerald-400", r.tone === "bad" && "bg-red-400", r.tone === "warn" && "bg-amber-400")} />
            {r.text}
          </li>
        ))}
      </ul>
      <Link href={`/result?run=${run.run_id}`} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
        Poora result, graph aur chart replay <ArrowRight className="size-4" />
      </Link>
    </section>
  );
}

function Validation({ va, holdoutUsed, passedFirst }: { va: ValidateRun | null; holdoutUsed: boolean; passedFirst: boolean }) {
  return (
    <section aria-label="Final check" className="space-y-3 rounded-2xl border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Final check (validation)</h2>
        {va && <Pill tone={VALIDATE_PLAIN[va.checklist.verdict]?.tone ?? "warn"}>{VALIDATE_PLAIN[va.checklist.verdict]?.text ?? va.checklist.verdict}</Pill>}
      </div>
      {!va && (
        <p className="text-sm text-muted-foreground">
          {passedFirst
            ? "Abhi final check nahi hua. Naya data (check data), walk-forward aur luck test — teeno yahan dikhenge."
            : "Final check tab hota hai jab pehla test pass ho. Tab tak yeh strategy profitable nahi maani jaati."}
        </p>
      )}
      {va && (
        <ul className="space-y-1.5">
          {va.checklist.items.map((it) => (
            <li key={it.key} className="flex items-start gap-2 text-sm">
              <span
                className={cn(
                  "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full",
                  it.passed === true && "bg-emerald-500 text-background",
                  it.passed === false && "bg-red-500 text-background",
                  it.passed == null && "border text-muted-foreground",
                )}
              >
                {it.passed === true ? <Check className="size-3" strokeWidth={3} /> : it.passed === false ? <X className="size-3" strokeWidth={3} /> : <CircleDashed className="size-3" />}
              </span>
              <span className="min-w-0">
                {checkPlain(it.key)}
                {it.why && <span className="block text-xs text-muted-foreground">{it.why}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="flex items-start gap-2 rounded-lg bg-muted/40 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
        <Lock className="mt-0.5 size-3.5 shrink-0 text-primary" />
        Final exam data (Sep 2025 se) {holdoutUsed ? "is idea-family ke liye ek baar khul chuka hai — dobara nahi khulega." : "band hai. Sab kuch pass hone ke baad hi, sirf ek baar khulega."}
      </p>
    </section>
  );
}

function History({ runs }: { runs: RunRow[] }) {
  const list = runs.filter((r) => r.kind === "backtest" || r.kind === "validate" || r.kind === "optimize" || r.kind === "ml");
  const KIND: Record<string, string> = { backtest: "Test", validate: "Final check", optimize: "Settings sudhaar", ml: "AI filter" };
  return (
    <section aria-label="Research history" className="overflow-hidden rounded-2xl border bg-card">
      <h2 className="px-5 pt-4 pb-2 text-lg font-bold">Research history — har test</h2>
      {!list.length && <p className="px-5 pb-4 text-sm text-muted-foreground">Abhi koi test nahi hua.</p>}
      <ol className="relative mx-5 mb-4 border-l pl-5">
        {list.map((r) => {
          const pill = r.kind === "validate" ? (VALIDATE_PLAIN[String(r.summary.verdict)] ?? { text: String(r.summary.verdict), tone: "warn" as const }) : r.kind === "backtest" ? quickVerdict(r.summary) : { text: "dekho", tone: "muted" as const };
          const href = r.kind === "backtest" ? `/result?run=${r.run_id}` : r.kind === "validate" ? `/validate?run=${r.run_id}` : r.kind === "ml" ? `/ml?run=${r.run_id}` : `/optimize?run=${r.run_id}`;
          const e = typeof r.summary.expectancy_r === "number" ? r.summary.expectancy_r : null;
          return (
            <li key={r.run_id} className="relative py-2">
              <span className="absolute top-3.5 -left-[25px] size-2.5 rounded-full bg-primary" />
              <Link href={href} className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1 hover:bg-muted/40">
                <span className="font-semibold">{KIND[r.kind] ?? r.kind}</span>
                <span className="text-xs text-muted-foreground">
                  {TIER_PLAIN[r.tier] ?? r.tier} · {ago(r.created_at)}
                </span>
                <Pill tone={pill.tone}>{pill.text}</Pill>
                {e != null && <span className={cn("font-mono text-xs", e > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(e, 2)}</span>}
                <ArrowRight className="ml-auto size-4 text-primary" />
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Versions({ current, versions }: { current: SpecRow; versions: SpecRow[] }) {
  if (versions.length <= 1) return null;
  const byHash = new Map(versions.map((v) => [v.spec_hash, v]));
  const list = [...versions].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <section aria-label="Versions" className="overflow-hidden rounded-2xl border bg-card">
      <div className="px-5 pt-4 pb-2">
        <h2 className="text-lg font-bold">Versions — is idea ke {versions.length} roop</h2>
        <p className="text-sm text-muted-foreground">Har version ek alag koshish hai. Jitne zyada versions, pass ka bar utna ooncha (luck test).</p>
      </div>
      <ul>
        {list.map((v, i) => {
          const parent = v.parent_hash ? byHash.get(v.parent_hash) : null;
          const cur = v.spec_hash === current.spec_hash;
          return (
            <li key={v.spec_hash} className={cn("border-t", cur && "bg-primary/10")}>
              <Link href={`/strategy?spec=${v.spec_hash}`} className="flex flex-wrap items-center gap-2 px-5 py-2.5 hover:bg-muted/30">
                <span className="font-mono text-xs text-muted-foreground">v{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {v.name} {cur && <span className="text-xs text-primary">(yeh)</span>}
                  </span>
                  {parent && <span className="block text-xs text-muted-foreground">v{list.indexOf(parent) + 1} se: {diffWords(parent.spec, v.spec).join(", ")}</span>}
                </span>
                <span className="text-xs text-muted-foreground">{v.runs ?? 0} tests</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
