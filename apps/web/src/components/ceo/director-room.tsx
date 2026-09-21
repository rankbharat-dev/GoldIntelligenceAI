"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";

import { inputCls } from "@/components/research/bits";
import { Button } from "@/components/ui/button";
import { ceo, type Mission } from "@/lib/ceo";
import { cn } from "@/lib/utils";

import { AGENT_ICON, ago, CopyCommand } from "./bits";

/** Director Room: an asynchronous thread between the CEO and the Research Director.
 * The Director reads it (read_messages) each time /ceo-run plans or finishes a round. */
export function DirectorRoom({ m }: { m: Mission }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const closed = m.status === "completed" || m.status === "failed" || m.status === "cancelled";
  const q = useQuery({
    queryKey: ["ceo", "messages", m.mission_id],
    queryFn: () => ceo.messages(m.mission_id),
    refetchInterval: closed ? false : 4000,
  });
  const msgs = q.data ?? [];
  const Crown = AGENT_ICON.director;

  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      await ceo.say(m.mission_id, text.trim());
      setText("");
      void qc.invalidateQueries({ queryKey: ["ceo", "messages", m.mission_id] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Crown className="size-4 text-primary" strokeWidth={1.6} aria-hidden /> Director Room
      </h3>
      <p className="mb-2 text-[11px] text-muted-foreground">
        Director se baat karo: extra wish, sawaal ka jawaab, ya koi badlaav. Director agli baar <CopyCommand command="/ceo-run" /> chalne pe
        padhega aur jawaab dega.
      </p>
      <ul className="mb-2 max-h-72 space-y-1.5 overflow-y-auto">
        {!msgs.length && <li className="text-xs text-muted-foreground">Abhi koi message nahi.</li>}
        {msgs.map((e) => {
          const mine = e.actor === "ceo";
          return (
            <li key={e.event_id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
              <div
                className={cn(
                  "max-w-[85%] rounded-lg px-2.5 py-1.5 text-xs leading-relaxed whitespace-pre-line",
                  mine ? "bg-primary/15 text-foreground" : "bg-background/60 ring-1 ring-foreground/10",
                )}
              >
                <p className="mb-0.5 text-[10px] text-muted-foreground">
                  {mine ? "Aap (CEO)" : "Research Director"} · {ago(e.created_at)}
                </p>
                {e.message}
              </div>
            </li>
          );
        })}
      </ul>
      {!closed && (
        <div className="flex gap-2">
          <input
            className={inputCls}
            value={text}
            placeholder="Jaise: 'NY session ko bhi alag se dekhna' ya 'target 2 ATR bhi try karo'"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && text.trim()) void send();
            }}
          />
          <Button size="sm" onClick={() => void send()} disabled={busy || !text.trim()} aria-label="Send">
            <Send />
          </Button>
        </div>
      )}
      {err && <p className="mt-1 text-xs text-red-400">{err}</p>}
    </section>
  );
}
