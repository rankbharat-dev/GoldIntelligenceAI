"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Bot,
  CandlestickChart,
  ChartLine,
  FlaskConical,
  Library,
  Lightbulb,
  Loader2,
  Lock,
  PlayCircle,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AGENT_ICON, AGENT_NAME, ago, MISSION_LABEL } from "@/components/ceo/bits";
import { ACTIVE_MISSION, ceo, type MissionRow } from "@/lib/ceo";
import { quickVerdict, TERMS, type TermKey } from "@/lib/plain";
import { fmtR, pipeline, research, type Job } from "@/lib/research";
import { cn } from "@/lib/utils";

import { JourneyList } from "./journey-list";
import { useJourneys } from "./strategies";
import { Pill, STAGES } from "./ui";

// Simple-mode Home: a research workstation dashboard — what is running now (tests and AI
// missions), the latest honest results, the one "continue" action, and the four sections.

const SECTIONS: { icon: LucideIcon; tag: string; title: string; body: string; links: { label: string; href: string }[] }[] = [
  {
    icon: ChartLine,
    tag: "Explore Market",
    title: "Gold ko samjho",
    body: "Kaunse patterns ke baad gold sach mein kuch karta hai — chart aur indicators ke saath.",
    links: [
      { label: "Patterns dekho", href: "/learn" },
      { label: "Gold chart", href: "/chart" },
    ],
  },
  {
    icon: Lightbulb,
    tag: "Create & Discover",
    title: "Strategy banao",
    body: "Apna idea 5 sawaal mein, live chart preview ke saath — ya AI team ko research mission do.",
    links: [
      { label: "Idea se banao", href: "/idea" },
      { label: "AI Research", href: "/ceo-lab" },
    ],
  },
  {
    icon: PlayCircle,
    tag: "Test & Analyze",
    title: "Result samjho",
    body: "Seedha jawab, paise ka graph, aur chart pe har trade replay — rules ke saath verify.",
    links: [{ label: "Results & replay", href: "/results" }],
  },
  {
    icon: Library,
    tag: "My Strategy Lab",
    title: "Safar dekho",
    body: "Har strategy kahan tak pahunchi, uske versions, aur agla imaandar kadam.",
    links: [{ label: "Meri strategies", href: "/my" }],
  },
];

const LEARN: { term: TermKey; label: string }[] = [
  { term: "r", label: "R kya hai?" },
  { term: "tier", label: "Practice / Check / Final exam data" },
  { term: "costs", label: "Kharcha itna zaroori kyun?" },
];

const ACTIVE_JOB = new Set(["queued", "running"]);

export function SimpleHome() {
  const [learn, setLearn] = useState<TermKey | null>(null);
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: research.jobs, refetchInterval: 4000, retry: false });
  const missions = useQuery({ queryKey: ["ceo", "missions"], queryFn: ceo.missions, refetchInterval: 6000, retry: false });
  const running = (jobs.data ?? []).filter((j) => ACTIVE_JOB.has(j.status));
  const active = (missions.data ?? []).filter((m) => ACTIVE_MISSION.includes(m.status));

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-8 md:px-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <p className="text-xs font-semibold tracking-[0.18em] text-primary">GOLD STRATEGY DISCOVERY LAB</p>
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">Namaste! Research kahan tak pahunchi?</h1>
          <p className="text-muted-foreground">5 saal ka XAUUSD data · asli kharche · kharche ke baad bhi kamai ho, tabhi pass.</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground">
          <Lock className="size-3.5 text-primary" /> Final exam data (2025–26) band hai — imaandar test ke liye
        </span>
      </header>

      <ContinueCard running={running} active={active} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <LiveResearch running={running} active={active} />
        <RecentResults />
        <LabNumbers />
      </div>

      <section aria-label="Chaar hisse" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {SECTIONS.map((s) => (
          <div key={s.tag} className="flex flex-col gap-3 rounded-2xl border bg-card p-5">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-full bg-primary/15 text-primary">
                <s.icon className="size-5" strokeWidth={1.8} />
              </span>
              <div>
                <p className="text-[10px] font-semibold tracking-[0.16em] text-primary/80 uppercase">{s.tag}</p>
                <p className="font-bold">{s.title}</p>
              </div>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{s.body}</p>
            <div className="mt-auto flex flex-wrap gap-2">
              {s.links.map((l) => (
                <Link key={l.href} href={l.href} className="inline-flex h-9 items-center gap-1 rounded-lg border border-primary/40 px-3 text-sm font-semibold text-primary hover:bg-primary/10">
                  {l.label}
                  <ArrowRight className="size-3.5" />
                </Link>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section aria-label="Meri strategies" className="overflow-hidden rounded-2xl border bg-card">
        <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-4">
          <h2 className="text-lg font-bold">Meri strategies</h2>
          <span className="text-xs text-muted-foreground">Safar: {STAGES.join(" → ")}</span>
        </div>
        <JourneyList limit={4} />
        <div className="border-t px-4 py-3 text-right">
          <Link href="/my" className="text-sm font-semibold text-primary hover:underline">
            Saari strategies dekho →
          </Link>
        </div>
      </section>

      <section aria-label="Seekho" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">1 minute mein samjho:</span>
          {LEARN.map((l) => (
            <button
              key={l.term}
              type="button"
              aria-pressed={learn === l.term}
              onClick={() => setLearn(learn === l.term ? null : l.term)}
              className={cn(
                "h-9 rounded-full border px-4 text-sm",
                learn === l.term ? "border-primary/60 bg-primary/10 text-primary" : "bg-card hover:bg-muted/40",
              )}
            >
              {l.label}
            </button>
          ))}
        </div>
        {learn && <p className="max-w-3xl rounded-xl border bg-card px-4 py-3 text-sm leading-relaxed">{TERMS[learn].plain}</p>}
      </section>
    </div>
  );
}

/** The single most useful next step: a running test, an AI mission, a strategy's next stage, or a first idea. */
function ContinueCard({ running, active }: { running: Job[]; active: MissionRow[] }) {
  const { rows } = useJourneys();
  let title = "Pehla idea test karo";
  let body = "5 aasaan sawaal, live chart preview, aur 5 minute mein seedha jawab — kaam karta hai ya nahi.";
  let href = "/idea";
  let cta = "Shuru karo";
  let Icon: LucideIcon = Sparkles;
  const job = running[0];
  const mission = active[0];
  const next = rows.find((j) => j.next.action.kind === "link");
  if (job) {
    title = `Test chal raha hai: ${job.title}`;
    body = `${Math.round(job.progress * 100)}% ho gaya — ${job.message || "har 5-minute candle pe, asli kharchon ke saath"}. Khatam hote hi result yahan dikhega.`;
    href = "/results";
    cta = "Results dekho";
    Icon = Loader2;
  } else if (mission) {
    title = `AI research: ${mission.objective}`;
    body = `${MISSION_LABEL[mission.status].text}${mission.progress.total ? ` · ${mission.progress.completed}/${mission.progress.total} kaam poore` : ""}. Agents se baat karo ya agla kadam approve karo.`;
    href = `/ceo-lab?mission=${mission.mission_id}`;
    cta = "Research continue karo";
    Icon = Bot;
  } else if (next && next.next.action.kind === "link") {
    title = `${next.row.name}`;
    body = `${next.status.text}. Agla kadam: ${next.next.label.toLowerCase()}.`;
    href = next.next.action.href;
    cta = "Research continue karo";
    Icon = FlaskConical;
  }
  return (
    <section aria-label="Continue research" className="flex flex-col gap-4 rounded-2xl border border-primary/40 bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6 sm:flex-row sm:items-center">
      <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
        <Icon className={cn("size-7", Icon === Loader2 && "animate-spin")} strokeWidth={1.8} />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-xs font-semibold tracking-[0.16em] text-primary uppercase">Wahin se aage badho</p>
        <h2 className="line-clamp-2 text-xl font-bold">{title}</h2>
        <p className="text-sm text-muted-foreground">{body}</p>
      </div>
      <Link href={href} className="inline-flex h-12 shrink-0 items-center gap-2 rounded-xl bg-primary px-6 font-semibold text-primary-foreground hover:bg-primary/90">
        {cta}
        <ArrowRight className="size-4" />
      </Link>
    </section>
  );
}

function Panel({ title, href, cta, children }: { title: string; href: string; cta: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex min-h-64 flex-col rounded-2xl border bg-card">
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <h2 className="font-bold">{title}</h2>
        <Link href={href} className="text-xs font-semibold text-primary hover:underline">
          {cta} →
        </Link>
      </div>
      <div className="flex-1 px-4 pb-4">{children}</div>
    </section>
  );
}

function LiveResearch({ running, active }: { running: Job[]; active: MissionRow[] }) {
  const ov = useQuery({ queryKey: ["ceo", "overview"], queryFn: ceo.overview, refetchInterval: 6000, retry: false });
  const agents = ov.data?.agents ?? [];
  return (
    <Panel title="Abhi kya chal raha hai" href="/ceo-lab" cta="AI Research">
      {!running.length && !active.length && (
        <p className="text-sm text-muted-foreground">
          Abhi kuch nahi chal raha. AI team ko ek sawaal do — jaise &quot;London mein kal ke low ka sweep kaam karta hai?&quot;
        </p>
      )}
      <ul className="space-y-3">
        {running.map((j) => (
          <li key={j.job_id} className="space-y-1">
            <p className="flex items-center gap-2 text-sm">
              <Loader2 className="size-3.5 animate-spin text-primary" />
              <span className="truncate">{j.title}</span>
              <span className="ml-auto font-mono text-xs">{Math.round(j.progress * 100)}%</span>
            </p>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-all" style={{ width: `${Math.max(3, j.progress * 100)}%` }} />
            </div>
          </li>
        ))}
        {active.slice(0, 3).map((m) => {
          const pct = m.progress.total ? (m.progress.completed / m.progress.total) * 100 : 0;
          return (
            <li key={m.mission_id}>
              <Link href={`/ceo-lab?mission=${m.mission_id}`} className="block space-y-1 rounded-lg hover:bg-muted/30">
                <p className="line-clamp-2 text-sm">{m.objective}</p>
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span>{MISSION_LABEL[m.status].text}</span>
                  {m.progress.total > 0 && (
                    <span className="ml-auto font-mono">
                      {m.progress.completed}/{m.progress.total} kaam
                    </span>
                  )}
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full bg-primary/80" style={{ width: `${Math.max(3, pct)}%` }} />
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
      {agents.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5 border-t pt-3">
          {agents.map((a) => {
            const Icon = AGENT_ICON[a.agent];
            return (
              <span
                key={a.agent}
                title={`${AGENT_NAME[a.agent]} · ${a.status === "working" ? `kaam: ${a.current_task?.title ?? ""}` : a.status === "waiting" ? "intezaar" : "khaali"}`}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                  a.status === "working" ? "border-primary/50 text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="size-3" />
                {AGENT_NAME[a.agent].split(" ")[0]}
                {a.status === "working" && <span className="size-1.5 animate-pulse rounded-full bg-primary" />}
              </span>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function RecentResults() {
  const q = useQuery({ queryKey: ["runs", "all"], queryFn: () => research.runs(), retry: false });
  const rows = (q.data ?? []).filter((r) => r.kind === "backtest").slice(0, 5);
  return (
    <Panel title="Taaza results" href="/results" cta="Saare results">
      {q.isLoading && <p className="text-sm text-muted-foreground">Load ho raha hai…</p>}
      {q.data && !rows.length && <p className="text-sm text-muted-foreground">Abhi koi test nahi hua.</p>}
      <ul className="space-y-1">
        {rows.map((r) => {
          const v = quickVerdict(r.summary);
          const e = typeof r.summary.expectancy_r === "number" ? r.summary.expectancy_r : null;
          return (
            <li key={r.run_id}>
              <Link href={`/result?run=${r.run_id}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-muted/40">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{String(r.summary.name ?? r.family)}</span>
                  <span className="text-[11px] text-muted-foreground">{ago(r.created_at)}</span>
                </span>
                <Pill tone={v.tone}>{v.tone === "good" ? "Pass (pehla test)" : v.text}</Pill>
                <span className={cn("w-16 text-right font-mono text-xs", e == null ? "" : e > 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(e, 2)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function LabNumbers() {
  const { rows } = useJourneys();
  const ov = useQuery({ queryKey: ["overview"], queryFn: research.overview, staleTime: 60_000, retry: false });
  const cands = useQuery({ queryKey: ["candidates"], queryFn: pipeline.candidates, retry: false });
  const trials = (ov.data?.families ?? []).reduce((n, f) => n + f.trials, 0);
  const passedFinal = (cands.data ?? []).filter((c) => c.verdict === "candidate").length;
  const tested = rows.filter((r) => r.lastBacktest).length;
  const items: { label: string; value: string; note: string }[] = [
    { label: "Strategies test hui", value: String(tested), note: `${rows.length} saved` },
    { label: "Kul koshishein (trials)", value: trials.toLocaleString(), note: "har koshish pass ka bar ooncha karti hai" },
    { label: "Final check pass", value: String(passedFinal), note: "abhi bhi profitable nahi maana — final exam baaki" },
  ];
  return (
    <Panel title="Lab ka imaandar hisaab" href="/my" cta="Strategy Lab">
      <ul className="space-y-3">
        {items.map((i) => (
          <li key={i.label} className="flex items-baseline gap-3">
            <span className="w-14 text-right font-mono text-2xl font-bold text-primary tabular-nums">{i.value}</span>
            <span className="min-w-0">
              <span className="block text-sm">{i.label}</span>
              <span className="block text-[11px] text-muted-foreground">{i.note}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-4 flex items-start gap-2 rounded-lg bg-muted/40 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
        <CandlestickChart className="mt-0.5 size-3.5 shrink-0 text-primary" />
        Koi bhi strategy tab tak &quot;profitable&quot; nahi kahi jaati jab tak naye data, luck test aur final exam — teeno pass na ho.
      </p>
    </Panel>
  );
}
