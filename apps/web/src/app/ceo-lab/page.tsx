"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AGENT_NAME, ago, Chip, CopyCommand, MISSION_LABEL } from "@/components/ceo/bits";
import { MissionComposer } from "@/components/ceo/composer";
import { MissionDetail } from "@/components/ceo/mission-detail";
import { Workforce } from "@/components/ceo/workforce";
import { Notice, PageHeader, Stat } from "@/components/research/bits";
import { ACTIVE_MISSION, ceo } from "@/lib/ceo";
import { cn } from "@/lib/utils";

// CEO Work Lab (docs/requirements/2026-09-21_ceo-work-lab.md): the owner's simple front door.
// Write a mission → run /ceo-run in Claude Code → five agents work → the report lands here.

export default function CeoLabPage() {
  return (
    <Suspense>
      <CeoLab />
    </Suspense>
  );
}

function CeoLab() {
  const params = useSearchParams();
  const router = useRouter();
  const selected = params.get("mission");
  const ov = useQuery({ queryKey: ["ceo", "overview"], queryFn: ceo.overview, refetchInterval: 5000, retry: false });
  const list = useQuery({ queryKey: ["ceo", "missions"], queryFn: ceo.missions, refetchInterval: 5000, retry: false });

  const o = ov.data;
  const active = (o ? ACTIVE_MISSION.reduce((n, s) => n + (o.missions[s] ?? 0), 0) : null) ?? null;
  const waitingYou = o ? (o.missions.awaiting_approval ?? 0) + (o.tasks.waiting_ceo ?? 0) : null;

  return (
    <div className="space-y-3 p-3">
      <PageHeader
        title="CEO Work Lab"
        subtitle="Aap CEO ho. Mission likho → Claude Code mein /ceo-run → paanch AI agents research karte hain → report yahin aati hai. Har number engine ke asli run se."
      />

      {ov.isError && (
        <Notice tone="error">
          Local engine se connect nahi ho raha. <b>Start_Candle_Intelligence.bat</b> chalao (ya ci-api), phir page refresh karo.
        </Notice>
      )}

      <HowItWorks />

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Chal rahe missions" value={active ?? "—"} />
        <Stat label="Aapki approval chahiye" value={waitingYou ?? "—"} tone={waitingYou ? "bad" : undefined} />
        <Stat label="Abhi chal rahe kaam" value={o?.tasks.running ?? "—"} />
        <Stat label="Poore missions (report)" value={o?.missions.completed ?? "—"} tone={o?.missions.completed ? "good" : undefined} />
      </div>

      <div className="grid grid-cols-1 gap-3 2xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 space-y-3">
          <MissionComposer onCreated={(m) => router.push(`/ceo-lab?mission=${m.mission_id}`)} />
          <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
            <h2 className="mb-2 text-sm font-semibold">Missions</h2>
            {!list.data?.length && <p className="text-xs text-muted-foreground">Abhi koi mission nahi. Upar pehla mission likho.</p>}
            <ul className="space-y-1.5">
              {list.data?.map((m) => {
                const st = MISSION_LABEL[m.status];
                return (
                  <li key={m.mission_id}>
                    <Link
                      href={`/ceo-lab?mission=${m.mission_id}`}
                      className={cn(
                        "block rounded-lg border px-2.5 py-2 hover:bg-muted/40",
                        selected === m.mission_id && "border-primary/50 bg-muted/30",
                      )}
                    >
                      <p className="line-clamp-2 text-xs leading-snug">{m.objective}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <Chip text={st.text} cls={st.cls} />
                        {m.progress.total > 0 && (
                          <span>
                            {m.progress.completed}/{m.progress.total} kaam
                          </span>
                        )}
                        {m.agents.length > 0 && <span className="truncate">{m.agents.map((a) => AGENT_NAME[a as keyof typeof AGENT_NAME] ?? a).join(" · ")}</span>}
                        <span className="ml-auto">{ago(m.created_at)}</span>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
        <div className="min-w-0">
          {selected ? (
            <MissionDetail id={selected} />
          ) : (
            <Notice>Koi mission chuno (left side) ya naya mission likho — uski poori progress aur report yahan dikhegi.</Notice>
          )}
        </div>
      </div>

      <section className="space-y-2">
        <h2 className="px-1 text-sm font-semibold">AI Workforce — aapke paanch agents</h2>
        {o ? <Workforce agents={o.agents} /> : <p className="px-1 text-xs text-muted-foreground">Loading…</p>}
      </section>
    </div>
  );
}

function HowItWorks() {
  const steps = [
    { n: 1, t: "Mission likho", d: "Neeche box mein apni research ka sawaal." },
    { n: 2, t: "Claude Code mein chalao", d: <>Is project folder mein <CopyCommand command="/ceo-run" /></> },
    { n: 3, t: "Agents kaam karte hain", d: "Director plan banata hai; 4 specialists engine se test karte hain." },
    { n: 4, t: "Report padho", d: "Seedhi Hinglish report, har number ke saath uska source run." },
  ];
  return (
    <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {steps.map((s) => (
        <li key={s.n} className="flex gap-2.5 rounded-xl border border-dashed px-3 py-2">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 font-mono text-xs font-semibold text-primary">
            {s.n}
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold">{s.t}</p>
            <p className="text-[11px] leading-snug text-muted-foreground">{s.d}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
