"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, MessageSquare, Send, Sparkles, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ceo, runHref, type CeoEvent, type Mission, type Task } from "@/lib/ceo";
import { cn } from "@/lib/utils";

import { AGENT_ICON, AGENT_NAME, ago, CopyCommand } from "./bits";

// Research chat: one conversation per mission — the CEO's messages, the Director's replies,
// each agent's finished work (with its source runs) and the final report, in time order.
// Messages are stored in the mission store; the Director reads them on its next /ceo-run
// round, so replies are asynchronous (never simulated here).

const QUICK: string[] = [
  "Result simple Hinglish mein samjhao",
  "Yahi test New York session pe bhi karo",
  "Bada target (1:3) bhi try karo",
  "Kis saal / session mein fail hua, woh dikhao",
];

type AgentKey = keyof typeof AGENT_ICON;
const isAgent = (a: string): a is AgentKey => a in AGENT_ICON;

function Bubble({ side, who, time, icon, children, tone }: { side: "left" | "right"; who: string; time: string; icon: React.ReactNode; children: React.ReactNode; tone?: "gold" | "bad" }) {
  return (
    <li className={cn("flex gap-2", side === "right" && "flex-row-reverse")}>
      <span className={cn("mt-5 flex size-7 shrink-0 items-center justify-center rounded-full", side === "right" ? "bg-primary text-primary-foreground" : "bg-muted text-primary")}>{icon}</span>
      <div className={cn("max-w-[85%] min-w-0", side === "right" && "text-right")}>
        <p className="mb-0.5 text-[10px] text-muted-foreground">
          {who} · {time}
        </p>
        <div
          className={cn(
            "inline-block rounded-2xl px-3.5 py-2 text-left text-sm leading-relaxed whitespace-pre-line",
            side === "right" ? "rounded-tr-sm bg-primary/15" : "rounded-tl-sm bg-background/70 ring-1 ring-foreground/10",
            tone === "gold" && "ring-primary/50",
            tone === "bad" && "ring-red-500/40",
          )}
        >
          {children}
        </div>
      </div>
    </li>
  );
}

function TaskResult({ t }: { t: Task }) {
  const o = t.output;
  return (
    <>
      <b>✓ {t.title}</b>
      {o?.summary && <span className="mt-1 block">{o.summary}</span>}
      {!!o?.findings.length && (
        <span className="mt-2 block space-y-1">
          {o.findings.slice(0, 4).map((f, i) => (
            <span key={i} className="block text-xs text-muted-foreground">
              • {f.text}
              {f.source?.run_id && (
                <Link href={runHref(f.source.run_id)} className="ml-1 font-mono text-[10px] text-primary hover:underline">
                  [{f.source.run_id.slice(0, 14)}…]
                </Link>
              )}
            </span>
          ))}
        </span>
      )}
    </>
  );
}

export function ResearchChat({ m }: { m: Mission }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const closed = m.status === "completed" || m.status === "failed" || m.status === "cancelled";
  const tasks = new Map(m.tasks.map((t) => [t.task_id, t]));
  const events = m.events.filter((e) => showLogs || e.kind !== "log");
  const lastId = events[events.length - 1]?.event_id;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [lastId]);
  const bridge = useQuery({ queryKey: ["ceo", "bridge"], queryFn: ceo.bridge, refetchInterval: 10000, retry: false });
  const working = m.tasks.filter((t) => t.state === "running");
  const lastCeo = [...m.events].reverse().find((e) => e.kind === "message" && e.actor === "ceo");
  const answered = lastCeo && m.events.some((e) => e.event_id > lastCeo.event_id && e.kind === "message" && e.actor !== "ceo");

  const send = async (msg: string) => {
    if (!msg.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await ceo.say(m.mission_id, msg.trim());
      setText("");
      void qc.invalidateQueries({ queryKey: ["ceo", "mission", m.mission_id] });
      void qc.invalidateQueries({ queryKey: ["ceo", "messages", m.mission_id] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const render = (e: CeoEvent) => {
    const time = ago(e.created_at);
    const task = e.task_id ? tasks.get(e.task_id) : undefined;
    if (e.kind === "mission_created")
      return (
        <Bubble key={e.event_id} side="right" who="Aap (CEO) · mission" time={time} icon={<User className="size-3.5" />}>
          {m.objective}
        </Bubble>
      );
    if (e.kind === "plan" && m.plan_note) {
      const Icon = AGENT_ICON.director;
      return (
        <Bubble key={e.event_id} side="left" who="Research Director · plan" time={time} icon={<Icon className="size-3.5" />}>
          <b>Plan: </b>
          {m.plan_note}
          {m.tasks.length > 0 && (
            <span className="mt-2 block space-y-0.5 text-xs text-muted-foreground">
              {m.tasks.map((t) => (
                <span key={t.task_id} className="block">
                  {t.seq}. {AGENT_NAME[t.agent]} — {t.title}
                </span>
              ))}
            </span>
          )}
        </Bubble>
      );
    }
    if (e.kind === "message") {
      const mine = e.actor === "ceo";
      const Icon = isAgent(e.actor) ? AGENT_ICON[e.actor] : AGENT_ICON.director;
      return (
        <Bubble key={e.event_id} side={mine ? "right" : "left"} who={mine ? "Aap (CEO)" : isAgent(e.actor) ? AGENT_NAME[e.actor] : e.actor} time={time} icon={mine ? <User className="size-3.5" /> : <Icon className="size-3.5" />}>
          {e.message}
        </Bubble>
      );
    }
    if (e.kind === "task_completed" && task && isAgent(task.agent)) {
      const Icon = AGENT_ICON[task.agent];
      return (
        <Bubble key={e.event_id} side="left" who={AGENT_NAME[task.agent]} time={time} icon={<Icon className="size-3.5" />}>
          <TaskResult t={task} />
        </Bubble>
      );
    }
    if (e.kind === "task_failed" && task && isAgent(task.agent)) {
      const Icon = AGENT_ICON[task.agent];
      return (
        <Bubble key={e.event_id} side="left" who={AGENT_NAME[task.agent]} time={time} icon={<Icon className="size-3.5" />} tone="bad">
          ✗ {task.title}: {task.error ?? e.message}
        </Bubble>
      );
    }
    if (e.kind === "report" && m.report) {
      const Icon = AGENT_ICON.director;
      return (
        <Bubble key={e.event_id} side="left" who="Research Director · final report" time={time} icon={<Icon className="size-3.5" />} tone="gold">
          <b>{m.report.headline}</b>
          <span className="mt-1 block">{m.report.summary}</span>
        </Bubble>
      );
    }
    return (
      <li key={e.event_id} className="px-10 text-center text-[11px] text-muted-foreground">
        {isAgent(e.actor) ? AGENT_NAME[e.actor] : e.actor === "ceo" ? "Aap" : e.actor}: {e.message} · {time}
      </li>
    );
  };

  return (
    <section aria-label="Research chat" className="flex flex-col rounded-xl bg-card ring-1 ring-primary/30">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <MessageSquare className="size-4 text-primary" />
        <h3 className="mr-auto text-sm font-semibold">Research chat — Director aur agents se baat</h3>
        <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <input type="checkbox" checked={showLogs} onChange={(e) => setShowLogs(e.target.checked)} className="accent-[var(--primary)]" />
          Chhote updates bhi
        </label>
      </div>

      {working.length > 0 && (
        <div className="flex flex-wrap gap-2 border-b bg-primary/5 px-3 py-2">
          {working.map((t) => {
            const Icon = AGENT_ICON[t.agent];
            return (
              <span key={t.task_id} className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary/40 px-2.5 py-1 text-xs">
                <Icon className="size-3.5 text-primary" />
                <b>{AGENT_NAME[t.agent]}</b>
                <span className="truncate text-muted-foreground">{t.title}</span>
                <Loader2 className="size-3 animate-spin text-primary" />
              </span>
            );
          })}
        </div>
      )}

      <ul className="max-h-[520px] min-h-48 space-y-3 overflow-y-auto px-3 py-3">
        {events.map(render)}
        {lastCeo && !answered && !closed && (
          <li className="px-10 text-center text-[11px] text-amber-200/80">
            Aapka message Director ke paas hai — agli baar agents chalne pe (
            {bridge.data?.alive ? "bridge on hai, jaldi" : <>Claude Code mein <CopyCommand command="/ceo-run" /></>}) jawab yahan aayega.
          </li>
        )}
        <div ref={end} />
      </ul>

      {!closed ? (
        <div className="space-y-2 border-t px-3 py-3">
          <div className="flex flex-wrap gap-1.5">
            {QUICK.map((qk) => (
              <button
                key={qk}
                type="button"
                disabled={busy}
                onClick={() => void send(qk)}
                className="rounded-full border px-2.5 py-1 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-foreground"
              >
                {qk}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              className="h-10 min-w-0 flex-1 rounded-lg border bg-background/60 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              value={text}
              placeholder="Sawaal poocho ya naya idea do — jaise 'stop 2× karke dekho'"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void send(text);
              }}
            />
            <button type="button" onClick={() => void send(text)} disabled={busy || !text.trim()} aria-label="Bhejo" className="inline-flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground disabled:opacity-50">
              <Send className="size-4" />
            </button>
          </div>
          {err && <p className="text-xs text-red-400">{err}</p>}
        </div>
      ) : (
        <FollowUps m={m} />
      )}
    </section>
  );
}

/** A finished mission's recommendations become one-click new missions (new hypotheses). */
function FollowUps({ m }: { m: Mission }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ideas = (m.report?.recommendations ?? []).slice(0, 4);
  const start = async (objective: string) => {
    setBusy(true);
    setErr(null);
    try {
      const nm = await ceo.create({
        objective: `${objective.trim()}\n\n(Follow-up — pichhla mission ${m.mission_id}: ${m.objective.slice(0, 160)})`,
        require_plan_approval: false,
      });
      void qc.invalidateQueries({ queryKey: ["ceo"] });
      router.push(`/ceo-lab?mission=${nm.mission_id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 border-t px-3 py-3">
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        <Sparkles className="size-4 text-primary" /> Mission poora. Agla sawaal (naya, independent test):
      </p>
      {ideas.length > 0 && (
        <ul className="space-y-1.5">
          {ideas.map((r) => (
            <li key={r}>
              <button
                type="button"
                disabled={busy}
                onClick={() => void start(r)}
                className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs hover:border-primary/40 hover:bg-primary/5 disabled:opacity-60"
              >
                <span className="min-w-0 flex-1">{r}</span>
                <span className="inline-flex shrink-0 items-center gap-1 font-semibold text-primary">
                  Isko test karwao <ArrowRight className="size-3.5" />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input
          className="h-10 min-w-0 flex-1 rounded-lg border bg-background/60 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
          value={text}
          placeholder="Apna follow-up sawaal likho…"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && text.trim().length >= 10) void start(text);
          }}
        />
        <button type="button" disabled={busy || text.trim().length < 10} onClick={() => void start(text)} className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          Naya mission
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Har follow-up ek naya mission hai — naye tests apni koshish (trial) ginte hain, taaki bar imaandar rahe.
      </p>
      {err && <p className="text-xs text-red-400">{err}</p>}
    </div>
  );
}
