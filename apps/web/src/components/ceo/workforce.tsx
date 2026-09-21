"use client";

import Link from "next/link";

import type { AgentCard } from "@/lib/ceo";
import { cn } from "@/lib/utils";

import { AGENT_ICON, ago } from "./bits";

const STATUS = {
  working: { text: "Kaam kar raha hai", dot: "bg-primary animate-pulse" },
  waiting: { text: "Agla kaam taiyaar", dot: "bg-sky-400" },
  idle: { text: "Free", dot: "bg-muted-foreground/60" },
} as const;

/** Five agent cards — who is doing what, right now (from the task states). */
export function Workforce({ agents }: { agents: AgentCard[] }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
      {agents.map((a) => {
        const Icon = AGENT_ICON[a.agent];
        const st = STATUS[a.status];
        return (
          <div key={a.agent} className={cn("min-w-0 rounded-xl bg-card p-3 ring-1 ring-foreground/10", a.status === "working" && "ring-primary/40")}>
            <div className="flex items-center gap-2">
              <Icon className="size-5 shrink-0 text-primary" strokeWidth={1.6} aria-hidden />
              <p className="min-w-0 truncate text-[13px] font-semibold">{a.name}</p>
            </div>
            <p className="mt-1 line-clamp-2 min-h-8 text-[11px] leading-snug text-muted-foreground">{a.role}</p>
            <p className="mt-2 flex items-center gap-1.5 text-xs">
              <span className={cn("size-2 rounded-full", st.dot)} aria-hidden />
              {a.agent === "director" ? "Claude Code mein /ceo-run se chalta hai" : st.text}
            </p>
            {a.current_task && (
              <Link
                href={`/ceo-lab?mission=${a.current_task.mission_id}`}
                className="mt-1 block truncate text-xs text-primary hover:underline"
                title={a.current_task.title}
              >
                {a.current_task.title}
              </Link>
            )}
            <div className="mt-2 flex gap-3 text-[11px] text-muted-foreground">
              {a.agent !== "director" && (
                <>
                  <span>✓ {a.completed} kaam</span>
                  {a.failed > 0 && <span className="text-red-300">✗ {a.failed}</span>}
                </>
              )}
              <span className="ml-auto truncate" title={a.last_activity?.message}>
                {a.last_activity ? ago(a.last_activity.created_at) : "abhi tak kuch nahi"}
              </span>
            </div>
            {a.last_error && (
              <p className="mt-1 line-clamp-2 text-[11px] text-red-300" title={a.last_error}>
                {a.last_error}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
