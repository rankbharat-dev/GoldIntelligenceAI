"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";

import { inputCls } from "@/components/research/bits";
import { Button } from "@/components/ui/button";
import { ceo, type Mission } from "@/lib/ceo";

const EXAMPLES = [
  "XAUUSD M5 data mein check karo ki previous-day high/low ke liquidity sweep ke baad London aur New York session mein koi repeatable intraday trade banta hai ya nahi.",
  "M5 intraday strategies dhoondo: London + New York session, 1:3 risk-reward, max drawdown 15% se kam, kam se kam 500 historical trades.",
  "Data ki health check karo: kitne saal ka data hai, gaps kahan hain, aur kaunse session mein volatility sabse zyada hai.",
];

/** The one thing the CEO has to do: write the objective in their own words. */
export function MissionComposer({ onCreated }: { onCreated: (m: Mission) => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [approve, setApprove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const m = await ceo.create({ objective: text.trim(), require_plan_approval: approve });
      setText("");
      void qc.invalidateQueries({ queryKey: ["ceo"] });
      onCreated(m);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl bg-card p-3 ring-1 ring-primary/30">
      <h2 className="text-sm font-semibold text-primary">Naya research mission</h2>
      <p className="mb-2 text-xs text-muted-foreground">Apne shabdon mein likho kya research karwana hai. Hindi, Hinglish ya English — sab chalega.</p>
      <textarea
        className={`${inputCls} h-auto min-h-24 resize-y py-2 leading-relaxed`}
        placeholder="Jaise: London session mein previous-day low ka sweep hone ke baad long trade ka edge hai ya nahi?"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim().length >= 10) void submit();
        }}
      />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {EXAMPLES.map((x) => (
          <button
            key={x}
            type="button"
            onClick={() => setText(x)}
            className="max-w-full truncate rounded-md border px-2 py-0.5 text-left text-[11px] text-muted-foreground hover:border-primary/40 hover:text-foreground"
            title={x}
          >
            {x.length > 70 ? `${x.slice(0, 70)}…` : x}
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} className="accent-[var(--primary)]" />
          Kaam shuru hone se pehle plan mujhe dikhao (approve karunga)
        </label>
        <Button className="ml-auto" onClick={() => void submit()} disabled={busy || text.trim().length < 10}>
          <Send /> Mission do
        </Button>
      </div>
      {err && <p className="mt-2 text-xs text-red-400">{err}</p>}
    </section>
  );
}
