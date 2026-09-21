"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Radio } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ceo, type Mission } from "@/lib/ceo";
import { cn } from "@/lib/utils";

import { CopyCommand } from "./bits";

/** Live updates for one mission over Server-Sent Events. When the stream is up the page
 * refetches only on a change; if it drops, the queries fall back to polling. */
export function useMissionStream(id: string, enabled: boolean) {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const es = new EventSource(ceo.streamUrl(id));
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.addEventListener("change", () => {
      setLive(true);
      void qc.invalidateQueries({ queryKey: ["ceo", "mission", id] });
      void qc.invalidateQueries({ queryKey: ["ceo", "messages", id] });
      void qc.invalidateQueries({ queryKey: ["ceo", "overview"] });
      void qc.invalidateQueries({ queryKey: ["ceo", "missions"] });
    });
    return () => {
      es.close();
      setLive(false);
    };
  }, [id, enabled, qc]);
  return live;
}

export function LiveDot({ live }: { live: boolean }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-[11px]", live ? "text-emerald-400" : "text-muted-foreground")}
      title={live ? "Live stream on (Server-Sent Events)" : "Polling every few seconds"}
    >
      <Radio className="size-3" /> {live ? "Live" : "Auto-refresh"}
    </span>
  );
}

/** "Agents ko abhi chalao": asks the local bridge to start the Director in Claude Code's
 * headless mode. Without a running bridge the owner uses /ceo-run by hand. */
export function RunAgents({ m, act }: { m: Mission; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const b = useQuery({ queryKey: ["ceo", "bridge"], queryFn: ceo.bridge, refetchInterval: 10000, retry: false });
  const active = m.runs.find((r) => r.status === "requested" || r.status === "running");
  const bridge = b.data;
  const ready = !!bridge?.alive && !!bridge.info.cli;

  if (active)
    return (
      <p className="text-xs text-primary">
        {active.status === "requested" ? "Bridge ko request bheji — agents shuru hone wale hain…" : "Agents Claude Code (headless) mein kaam kar rahe hain…"}
      </p>
    );
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Button size="sm" disabled={!ready} onClick={() => void act(() => ceo.run(m.mission_id))} title={ready ? "" : "Bridge band hai"}>
        <Play /> Agents ko abhi chalao
      </Button>
      {!bridge?.alive && (
        <span className="text-muted-foreground">
          Bridge band hai — Claude Code mein <CopyCommand command="/ceo-run" /> chalao (ya <b>Start_CEO_Bridge.bat</b> chalao)
        </span>
      )}
      {bridge?.alive && !bridge.info.cli && (
        <span className="text-amber-300">Bridge chal raha hai, par Claude Code CLI install nahi hai (npm install -g @anthropic-ai/claude-code)</span>
      )}
      {ready && <span className="text-emerald-400">Bridge on · {bridge?.info.cli_version ?? "claude"}</span>}
    </div>
  );
}

export function UsagePanel({ m }: { m: Mission }) {
  const u = m.usage;
  const items: [string, string][] = [
    ["Kaam (tasks)", `${u.tasks}`],
    ["Koshishein", `${u.attempts}`],
    ["Engine runs (cited)", `${u.engine_runs_cited}`],
    ["Strategies", `${u.strategies}`],
    ["Samay", u.minutes == null ? "—" : `${u.minutes} min`],
    [
      "Claude tokens",
      u.bridge_runs_measured
        ? `${((u.input_tokens ?? 0) / 1000).toFixed(0)}k in · ${((u.output_tokens ?? 0) / 1000).toFixed(1)}k out`
        : "measure nahi (manual /ceo-run)",
    ],
  ];
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-background/40 px-3 py-2 text-[11px] sm:grid-cols-3">
      {items.map(([k, v]) => (
        <p key={k} className="flex justify-between gap-2">
          <span className="text-muted-foreground">{k}</span>
          <span className="font-mono tabular-nums">{v}</span>
        </p>
      ))}
      {u.bridge_runs_measured > 0 && u.cost_usd != null && (
        <p className="col-span-full text-muted-foreground">
          Claude Code ka reported notional cost: ${u.cost_usd.toFixed(2)} (Pro plan pe yeh bill nahi hota — sirf usage ka andaaza).
        </p>
      )}
    </div>
  );
}
