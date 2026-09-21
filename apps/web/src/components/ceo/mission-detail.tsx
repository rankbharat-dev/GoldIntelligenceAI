"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Pause, Pencil, Play, RotateCcw, ThumbsUp, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { inputCls, Notice } from "@/components/research/bits";
import { Button } from "@/components/ui/button";
import { ACTIVE_MISSION, ceo, EDITABLE, runHref, type Finding, type Mission, type Report, type Task } from "@/lib/ceo";
import { cn } from "@/lib/utils";

import { AGENT_ICON, AGENT_NAME, ago, Chip, CopyCommand, MISSION_LABEL, TASK_LABEL } from "./bits";
import { StrategyCompare } from "./compare";
import { DirectorRoom } from "./director-room";
import { LiveDot, RunAgents, UsagePanel, useMissionStream } from "./live";

const VERDICT: Record<Report["verdict"], { text: string; cls: string }> = {
  promising: { text: "Aage research karne layak", cls: "border-emerald-500/50 text-emerald-300" },
  inconclusive: { text: "Abhi pakka nahi keh sakte", cls: "border-amber-500/50 text-amber-300" },
  rejected: { text: "Edge nahi mila", cls: "border-red-500/40 text-red-300" },
  blocked: { text: "Data / tool ki kami se ruka", cls: "text-muted-foreground" },
};

export function MissionDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const [streamOn, setStreamOn] = useState(true);
  const live = useMissionStream(id, streamOn);
  const q = useQuery({
    queryKey: ["ceo", "mission", id],
    queryFn: () => ceo.mission(id),
    // with the live stream on, refetches happen on change; polling is the fallback
    refetchInterval: (s) => (s.state.data && ACTIVE_MISSION.includes(s.state.data.status) ? (live ? 30000 : 3000) : false),
  });
  const closedNow = !!q.data && !ACTIVE_MISSION.includes(q.data.status);
  if (closedNow && streamOn) setStreamOn(false);
  if (q.isError) return <Notice tone="error">Mission {id} nahi mila.</Notice>;
  const m = q.data;
  if (!m) return <p className="text-xs text-muted-foreground">Loading…</p>;

  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try {
      await fn();
      void qc.invalidateQueries({ queryKey: ["ceo"] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  const st = MISSION_LABEL[m.status];
  const p = m.progress;
  const editable = m.status === "awaiting_approval" || m.status === "running" || m.status === "paused";
  const canSendBack = (m.status === "awaiting_approval" || m.status === "running") && p.running === 0 && p.total > p.done;
  const hashes = [
    ...new Set([
      ...(m.report?.strategies ?? []),
      ...m.tasks.flatMap((t) => (t.output?.artifacts ?? []).filter((a) => a.kind === "spec").map((a) => a.ref)),
    ]),
  ];

  return (
    <div className="space-y-3">
      <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
        <div className="flex flex-wrap items-start gap-2">
          <p className="mr-auto min-w-0 flex-1 text-sm leading-relaxed">{m.objective}</p>
          <Chip text={st.text} cls={st.cls} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="font-mono">{m.mission_id}</span>
          <span>· {ago(m.created_at)}</span>
          {ACTIVE_MISSION.includes(m.status) && <LiveDot live={live} />}
          {p.total > 0 && (
            <span>
              · {p.completed}/{p.total} kaam poore{p.running ? ` · ${p.running} chal rahe` : ""}
              {p.failed ? ` · ${p.failed} fail` : ""}
            </span>
          )}
        </div>
        {p.total > 0 && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-label={`${p.done} of ${p.total} tasks finished`}>
            <div className="h-full bg-primary transition-all" style={{ width: `${(p.done / p.total) * 100}%` }} />
          </div>
        )}
        <div className="mt-2">
          <UsagePanel m={m} />
        </div>
        <NextStep m={m} />
        {(m.status === "draft" || m.status === "running") && (
          <div className="mt-2">
            <RunAgents m={m} act={act} />
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {m.status === "awaiting_approval" && (
            <Button size="sm" onClick={() => void act(() => ceo.approve(m.mission_id))}>
              <ThumbsUp /> Plan approve karo
            </Button>
          )}
          {canSendBack && <SendBack id={m.mission_id} act={act} />}
          {(m.status === "running" || m.status === "draft" || m.status === "awaiting_approval") && (
            <Button size="sm" variant="outline" onClick={() => void act(() => ceo.pause(m.mission_id))}>
              <Pause /> Pause
            </Button>
          )}
          {m.status === "paused" && (
            <Button size="sm" variant="outline" onClick={() => void act(() => ceo.resume(m.mission_id))}>
              <Play /> Resume
            </Button>
          )}
          {ACTIVE_MISSION.includes(m.status) && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => {
                if (confirm("Is mission ko band karna hai? Chal rahe kaam cancel ho jayenge.")) void act(() => ceo.cancel(m.mission_id));
              }}
            >
              <X /> Cancel
            </Button>
          )}
        </div>
        {err && <p className="mt-2 text-xs text-red-400">{err}</p>}
      </section>

      {m.report && <ReportCard r={m.report} />}

      <DirectorRoom m={m} />

      {m.plan_note && (
        <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
          <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
            <AgentIcon agent="director" /> Director ka plan
          </h3>
          <p className="text-xs leading-relaxed whitespace-pre-line text-muted-foreground">{m.plan_note}</p>
        </section>
      )}

      {m.tasks.length > 0 && (
        <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
          <h3 className="mb-2 text-sm font-semibold">Kaam ki list (kaun kya kar raha hai)</h3>
          <ol className="space-y-2">
            {m.tasks.map((t) => (
              <TaskRow
                key={t.task_id}
                t={t}
                tasks={m.tasks}
                editable={editable && EDITABLE.includes(t.state)}
                act={act}
              />
            ))}
          </ol>
        </section>
      )}

      {hashes.length > 0 && <StrategyCompare hashes={hashes} />}

      <Activity m={m} />
    </div>
  );
}

function AgentIcon({ agent }: { agent: keyof typeof AGENT_ICON }) {
  const Icon = AGENT_ICON[agent];
  return <Icon className="size-4 shrink-0 text-primary" strokeWidth={1.6} aria-hidden />;
}

function NextStep({ m }: { m: Mission }) {
  if (m.status === "draft")
    return (
      <div className="mt-2">
        <Notice>
          <b>Agla step:</b> Claude Code is folder mein kholo aur <CopyCommand command="/ceo-run" /> chalao. Research Director plan banayega aur baaki
          agents ko kaam dega. Progress yahin live dikhega.
        </Notice>
      </div>
    );
  if (m.status === "awaiting_approval")
    return (
      <div className="mt-2">
        <Notice tone="warn">
          Director ne plan bana diya hai. Neeche padho, theek lage to <b>Plan approve karo</b> dabao, phir Claude Code mein{" "}
          <CopyCommand command="/ceo-run" /> dobara chalao.
        </Notice>
      </div>
    );
  if (m.status === "running" && m.progress.running === 0 && m.progress.waiting_ceo === 0)
    return (
      <div className="mt-2">
        <Notice>
          Abhi koi agent kaam nahi kar raha. Agar Claude Code band ho gaya tha to <CopyCommand command="/ceo-run" /> dobara chalao — mission wahin se aage badhega.
        </Notice>
      </div>
    );
  return null;
}

type Act = (fn: () => Promise<unknown>) => Promise<void>;

function SendBack({ id, act }: { id: string; act: Act }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  if (!open)
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <RotateCcw /> Plan badlo
      </Button>
    );
  return (
    <div className="flex w-full flex-wrap gap-2">
      <input
        className={inputCls}
        autoFocus
        value={text}
        placeholder="Director ko batao kya badalna hai (plan dobara banega)"
        onChange={(e) => setText(e.target.value)}
      />
      <Button size="sm" disabled={text.trim().length < 5} onClick={() => void act(() => ceo.sendBack(id, text.trim())).then(() => setOpen(false))}>
        Wapas bhejo
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Rehne do
      </Button>
    </div>
  );
}

function TaskRow({ t, tasks, editable, act }: { t: Task; tasks: Task[]; editable: boolean; act: Act }) {
  const [open, setOpen] = useState(t.state === "running" || t.state === "failed");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(t.instructions);
  const st = TASK_LABEL[t.state];
  const deps = t.depends_on.map((d) => tasks.find((x) => x.task_id === d)?.seq).filter(Boolean);
  return (
    <li className={cn("rounded-lg border px-2.5 py-2", t.state === "running" && "border-primary/40")}>
      <button type="button" className="flex w-full flex-wrap items-center gap-2 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="font-mono text-[11px] text-muted-foreground">#{t.seq}</span>
        <AgentIcon agent={t.agent} />
        <span className="text-xs text-muted-foreground">{AGENT_NAME[t.agent]}</span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{t.title}</span>
        <Chip text={st.text} cls={st.cls} />
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {deps.length > 0 && <p className="mt-0.5 pl-6 text-[11px] text-muted-foreground">#{deps.join(", #")} ke baad</p>}
      {t.state === "waiting_ceo" && (
        <div className="mt-2 pl-6">
          <Button size="xs" onClick={() => void act(() => ceo.approveTask(t.task_id))}>
            <ThumbsUp /> Is kaam ko approve karo
          </Button>
        </div>
      )}
      {editable && !editing && (
        <div className="mt-1.5 flex gap-2 pl-6">
          <Button
            size="xs"
            variant="ghost"
            onClick={() => {
              setDraft(t.instructions);
              setEditing(true);
              setOpen(true);
            }}
          >
            <Pencil /> Badlo
          </Button>
          <Button
            size="xs"
            variant="ghost"
            onClick={() => {
              if (confirm(`"${t.title}" hata dein? Is par depend karne wale kaam bhi cancel honge.`)) void act(() => ceo.dropTask(t.task_id));
            }}
          >
            <Trash2 /> Hatao
          </Button>
        </div>
      )}
      {editing && (
        <div className="mt-2 space-y-1.5 pl-6">
          <textarea className={`${inputCls} h-auto min-h-20 py-1.5 text-xs`} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <div className="flex gap-2">
            <Button
              size="xs"
              disabled={draft.trim().length < 10}
              onClick={() => void act(() => ceo.editTask(t.task_id, { instructions: draft })).then(() => setEditing(false))}
            >
              Save
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setEditing(false)}>
              Rehne do
            </Button>
          </div>
        </div>
      )}
      {open && (
        <div className="mt-2 space-y-2 pl-6 text-xs">
          <details>
            <summary className="cursor-pointer text-muted-foreground">Director ke instructions</summary>
            <p className="mt-1 leading-relaxed whitespace-pre-line text-muted-foreground">{t.instructions}</p>
          </details>
          {t.error && <p className="text-red-300">{t.error}</p>}
          {t.attempt > 1 && <p className="text-muted-foreground">Koshish {t.attempt} / {t.max_attempts}</p>}
          {t.output && (
            <>
              <p className="leading-relaxed whitespace-pre-line">{t.output.summary}</p>
              <Findings items={t.output.findings} />
              {t.output.artifacts.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {t.output.artifacts.map((a) => (
                    <ArtifactLink key={`${a.kind}:${a.ref}`} kind={a.kind} refId={a.ref} title={a.title} />
                  ))}
                </div>
              )}
              <Bullets title="Limitations" items={t.output.limitations} />
              <Bullets title="Aage kya" items={t.output.next_steps} />
            </>
          )}
        </div>
      )}
    </li>
  );
}

function ArtifactLink({ kind, refId, title }: { kind: string; refId: string; title?: string }) {
  const href = kind === "run" ? runHref(refId) : kind === "spec" ? "/strategies" : kind === "search" ? `/pipeline?search=${refId}` : null;
  const label = `${kind} · ${title || refId}`;
  return href ? (
    <Link href={href} className="rounded border border-primary/30 px-1.5 py-0.5 font-mono text-[11px] text-primary hover:bg-primary/10">
      {label}
    </Link>
  ) : (
    <span className="rounded border px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{label}</span>
  );
}

function Findings({ items }: { items: Finding[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((f, i) => (
        <li key={i} className="rounded-md bg-background/40 px-2 py-1.5">
          <p>{f.text}</p>
          {Object.keys(f.metrics).length > 0 && (
            <p className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[11px] text-muted-foreground">
              {Object.entries(f.metrics).map(([k, v]) => (
                <span key={k}>
                  {k}: <span className="text-foreground">{v ?? "—"}</span>
                </span>
              ))}
            </p>
          )}
          {f.source && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Source:{" "}
              {f.source.run_id ? (
                <Link className="text-primary hover:underline" href={runHref(f.source.run_id)}>
                  {f.source.run_id}
                </Link>
              ) : f.source.job_id ? (
                <span className="font-mono">{f.source.job_id}</span>
              ) : (
                <span className="font-mono">
                  {f.source.dataset_id} · {f.source.query}
                </span>
              )}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Bullets({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="text-[11px] font-medium text-muted-foreground">{title}</p>
      <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

function ReportCard({ r }: { r: Report }) {
  const v = VERDICT[r.verdict];
  return (
    <section className="rounded-xl bg-card p-3 ring-1 ring-primary/40">
      <div className="flex flex-wrap items-start gap-2">
        <h3 className="mr-auto flex items-center gap-2 text-sm font-semibold">
          <AgentIcon agent="director" /> Final report: {r.headline}
        </h3>
        <Chip text={v.text} cls={v.cls} />
      </div>
      <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{r.summary}</p>
      <div className="mt-3 space-y-3 text-xs">
        <Findings items={r.findings} />
        {r.strategies.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">Strategies:</span>
            {r.strategies.map((h) => (
              <ArtifactLink key={h} kind="spec" refId={h} />
            ))}
          </div>
        )}
        <Bullets title="Aage kya karein (research)" items={r.recommendations} />
        <Bullets title="Limitations (dhyan rakhein)" items={r.limitations} />
        <p className="text-[11px] text-muted-foreground">Yeh research hai, trading advice nahi. Har number upar diye run se aata hai.</p>
      </div>
    </section>
  );
}

const ACTOR_LABEL: Record<string, string> = { ...AGENT_NAME, ceo: "Aap (CEO)", director: "Director", system: "System" };

function Activity({ m }: { m: Mission }) {
  const [all, setAll] = useState(false);
  const ev = [...m.events].reverse();
  const shown = all ? ev : ev.slice(0, 12);
  return (
    <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
      <h3 className="mb-2 text-sm font-semibold">Live activity</h3>
      <ul className="space-y-1 text-xs">
        {shown.map((e) => (
          <li key={e.event_id} className="flex gap-2">
            <span className="w-20 shrink-0 text-[11px] text-muted-foreground">{ago(e.created_at)}</span>
            <span className="w-28 shrink-0 truncate font-medium">{ACTOR_LABEL[e.actor] ?? e.actor}</span>
            <span className={cn("min-w-0 flex-1 break-words text-muted-foreground", (e.kind === "task_failed" || e.kind === "deadline") && "text-red-300")}>
              {e.message}
            </span>
          </li>
        ))}
      </ul>
      {ev.length > 12 && (
        <button className="mt-2 text-[11px] text-primary hover:underline" onClick={() => setAll((a) => !a)}>
          {all ? "Kam dikhao" : `Sab dikhao (${ev.length})`}
        </button>
      )}
    </section>
  );
}
