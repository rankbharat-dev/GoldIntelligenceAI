"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, Send, Terminal, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { inputCls, Notice, PageHeader, Section } from "@/components/research/bits";
import { Button } from "@/components/ui/button";
import { assistant, research, type ChatReply, type ChatTurn, type StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

const HISTORY_KEY = "ci.assistant-chat.v1";
const DRAFT_KEY = "ci.strategy-draft.v1";

interface Msg extends ChatTurn {
  proposal?: ChatReply["proposal"];
  model?: string;
}

function load<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

const EXAMPLES = [
  "Liquidity sweep ke baad London session mein long ka ek idea do — spec ke saath.",
  "Mere last backtest ka result simple Hinglish mein samjhao: costs kitna kha gaye?",
  "Behaviour screen mein kuch bhi discovery kyun nahi aaya? Aage kya try karein?",
];

export default function AssistantPage() {
  const [mode, setMode] = useState<"chat" | "noapi">("chat");
  return (
    <div className="space-y-3 p-3">
      <PageHeader title="AI Assistant" subtitle="Ideas in Hinglish → proposed specs you review; plain explanations of results. It only proposes — the engine does every number.">
        <div className="flex gap-1">
          {(
            [
              ["chat", "Chat (API mode)", Bot],
              ["noapi", "Claude Code / Desktop (no API)", Terminal],
            ] as const
          ).map(([m, label, Icon]) => (
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
            </button>
          ))}
        </div>
      </PageHeader>
      {mode === "chat" ? <Chat /> : <NoApi />}
    </div>
  );
}

function Chat() {
  const router = useRouter();
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: assistant.status });
  const runsQ = useQuery({ queryKey: ["runs"], queryFn: () => research.runs() });
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [runId, setRunId] = useState("");
  const [withDraft, setWithDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = load<Msg[]>(HISTORY_KEY);
    if (saved) setMsgs(saved); // eslint-disable-line react-hooks/set-state-in-effect -- restore once after mount
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(msgs.slice(-40)));
    } catch {
      /* private mode */
    }
    end.current?.scrollIntoView({ block: "end" });
  }, [msgs]);

  const send = async (q: string) => {
    if (!q.trim() || busy) return;
    setErr(null);
    setBusy(true);
    const history: ChatTurn[] = msgs.map(({ role, content }) => ({ role, content }));
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setText("");
    try {
      const r = await assistant.chat({
        question: q,
        history,
        run_id: runId || null,
        spec: withDraft ? load<StrategySpec>(DRAFT_KEY) : null,
      });
      setMsgs((m) => [...m, { role: "assistant", content: r.reply, proposal: r.proposal, model: r.model }]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const runs = (runsQ.data ?? []).filter((r) => r.tier !== "C").slice(0, 40);
  const st = status.data;
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Section title="Chat" description={st ? `${st.provider ?? "router"} · ${st.base_url_host ?? "—"} · model ${st.model}` : undefined}>
        {st && !st.configured && (
          <Notice tone="warn">API mode is not configured. Add CI_LLM_BASE_URL and CI_LLM_API_KEY to .env and restart ci-api — or use the no-API mode.</Notice>
        )}
        <div className="max-h-[60dvh] min-h-[240px] space-y-3 overflow-y-auto py-2">
          {!msgs.length && (
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground">Try:</p>
              {EXAMPLES.map((e) => (
                <button key={e} onClick={() => void send(e)} className="block rounded-md border px-2 py-1.5 text-left text-xs hover:bg-muted/40">
                  {e}
                </button>
              ))}
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={cn("rounded-lg px-3 py-2 text-sm", m.role === "user" ? "ml-8 bg-primary/10" : "mr-8 border bg-background/40")}>
              <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
              {m.proposal && (
                <div className="mt-2 rounded-md border border-primary/30 p-2 text-xs">
                  {m.proposal.valid ? (
                    <>
                      <p>
                        Proposed spec · <span className="font-mono">{m.proposal.spec_hash}</span> · validated by the engine
                      </p>
                      <Button
                        size="xs"
                        className="mt-1.5"
                        onClick={() => {
                          try {
                            localStorage.setItem(DRAFT_KEY, JSON.stringify(m.proposal!.spec));
                          } catch {
                            /* private mode */
                          }
                          router.push("/strategy-lab");
                        }}
                      >
                        Open in Visual Builder
                      </Button>
                    </>
                  ) : (
                    <>
                      <p className="text-amber-200">The proposed spec is not valid yet:</p>
                      {m.proposal.errors.map((e, j) => (
                        <p key={j} className="font-mono text-[11px]">
                          {e.loc}: {e.msg}
                        </p>
                      ))}
                    </>
                  )}
                </div>
              )}
              {m.model && <p className="mt-1 text-[10px] text-muted-foreground">{m.model}</p>}
            </div>
          ))}
          {busy && <p className="text-xs text-muted-foreground">Thinking…</p>}
          <div ref={end} />
        </div>
        {err && <p className="mb-2 text-xs text-red-400">{err}</p>}
        <div className="flex gap-2">
          <textarea
            className={cn(inputCls, "h-16 py-1.5")}
            placeholder="Apna sawaal ya idea likhiye…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(text);
              }
            }}
          />
          <div className="flex flex-col gap-1">
            <Button size="sm" disabled={busy || !text.trim()} onClick={() => void send(text)}>
              <Send /> Send
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMsgs([])} aria-label="Clear chat">
              <Trash2 />
            </Button>
          </div>
        </div>
      </Section>
      <aside className="space-y-3">
        <Section title="Attach context" description="What the assistant may read with your next question. Tier C results are never sent.">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">A result (backtest, validate, study, search…)</span>
            <select className={inputCls} value={runId} onChange={(e) => setRunId(e.target.value)}>
              <option value="">none</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.kind} · {String(r.summary.name ?? r.spec_hash)} · {r.tier}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-2 flex items-center gap-2 text-xs">
            <input type="checkbox" checked={withDraft} onChange={(e) => setWithDraft(e.target.checked)} />
            The strategy currently in the Visual Builder
          </label>
        </Section>
        <Notice>
          Sent to the router: your question, recent chat turns, the feature list and what you attach. Never sent: keys, account
          data, tier C. A proposed spec is only a draft — saving, backtesting and every trial count happen when <b>you</b> run it.
        </Notice>
      </aside>
    </div>
  );
}

function NoApi() {
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Section title="Use Claude Code or Claude Desktop (no API key needed)" description="The research engine is exposed as MCP tools. Claude runs them; Python does every number.">
        <ol className="list-decimal space-y-1.5 pl-5 text-xs leading-relaxed">
          <li>
            Start the research API: <code className="font-mono">ci-api</code> (port 8000).
          </li>
          <li>
            Open Claude Code in <code className="font-mono">C:\Gold_Intelligence_AI</code>. The project&apos;s{" "}
            <code className="font-mono">.mcp.json</code> registers <code className="font-mono">candle-intelligence-research</code> (and the read-only
            MT5 market data server). Approve it when asked.
          </li>
          <li>
            For Claude Desktop, add the same server to its config: command{" "}
            <code className="font-mono">C:\Gold_Intelligence_AI\.venv\Scripts\python.exe</code>, args{" "}
            <code className="font-mono">-m ci_api.research_mcp</code>.
          </li>
          <li>Ask in Hinglish, e.g. “behaviour library dekho aur ek search propose karo”.</li>
        </ol>
      </Section>
      <Section title="What the tools can and cannot do">
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <div>
            <p className="mb-1 font-medium text-emerald-300">Can</p>
            <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
              <li>read features, behaviours, results, candidates</li>
              <li>propose strategies (saved as “assistant”)</li>
              <li>backtest on tiers A / B / A∪B (counted as trials)</li>
              <li>run exploratory event studies on tier A</li>
              <li>propose searches — they wait for your approval</li>
            </ul>
          </div>
          <div>
            <p className="mb-1 font-medium text-red-300">Cannot</p>
            <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
              <li>see or unseal tier C</li>
              <li>approve or resume its own searches</li>
              <li>delete anything or change thresholds</li>
              <li>see account data or place any order</li>
            </ul>
          </div>
        </div>
      </Section>
    </div>
  );
}
