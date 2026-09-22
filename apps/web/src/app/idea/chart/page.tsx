"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ChartCreator } from "@/components/research/chart-creator";
import { IdeaPreview } from "@/components/simple/idea-preview";
import { TestProgress, useTestRun } from "@/components/simple/ui";
import { RISKS, ruleWord } from "@/lib/plain";
import type { Condition, Side, StrategySpec } from "@/lib/research";
import { cn } from "@/lib/utils";

// Create & Discover · "Chart pe mark karo": click the candle you would have entered on, keep
// the facts that describe the setup, pick stop / target, then test — the same engine,
// same family ("chart-idea") as the Expert Chart-Based Creator, so trials stay honest.

interface Rules {
  side: Side;
  conditions: Condition[];
  sessions: string[] | null;
}

function specOf(r: Rules, riskId: string, why: string): StrategySpec {
  const risk = RISKS.find((x) => x.id === riskId) ?? RISKS[1];
  return {
    meta: {
      name: `Chart idea · ${r.side === "long" ? "buy" : "sell"} · ${risk.title.split(":")[0]}`,
      family: "chart-idea",
      hypothesis: why.trim() || "Chart pe mark kiye setup jaisi candles ke baad price usi disha mein chalta hai.",
      created_by: "owner",
    },
    entries: [{ side: r.side, conditions: r.conditions.map((c) => ({ ...c })) }],
    filters: r.sessions ? { sessions: r.sessions } : {},
    exit: { stop_atr: risk.stop, target_atr: risk.target, time_exit_bars: risk.bars, trail_atr: null, flat_before_weekend: true },
    sizing: { risk_pct: 1, initial_equity_usd: 10000 },
  };
}

export default function ChartIdeaPage() {
  const [rules, setRules] = useState<Rules | null>(null);
  const [risk, setRisk] = useState("balanced");
  const [why, setWhy] = useState("");
  const test = useTestRun();
  const spec = rules ? specOf(rules, risk, why) : null;
  const pct = test.job ? Math.round(test.job.progress * 100) : null;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-8 md:px-8">
      <header className="space-y-1">
        <Link href="/idea" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Idea se banao
        </Link>
        <p className="text-xs font-semibold tracking-[0.18em] text-primary">CREATE &amp; DISCOVER</p>
        <h1 className="text-3xl font-bold">Chart pe setup mark karo</h1>
        <p className="max-w-3xl text-muted-foreground">
          Jo setup aap chart pe dekhte ho, wahi candle chuno. Engine us candle ke naapne layak facts dikhayega — aap chuno kaunse aapke
          setup ko batate hain. Phir stop / target chunke test chalao.
        </p>
      </header>

      {!rules && <ChartCreator plain onUse={(side, conditions, sessions) => setRules({ side, conditions, sessions })} />}

      {rules && spec && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(380px,40%)]">
          <section className="space-y-5">
            <div className="rounded-2xl border border-primary/40 bg-primary/10 p-5">
              <p className="mb-2 text-sm font-semibold">Aapka rule — jab yeh sab sach ho, tab {rules.side === "long" ? "BUY" : "SELL"}:</p>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {rules.conditions.map((c, i) => (
                  <li key={i}>{ruleWord(c.feature, c.op, c.value)}</li>
                ))}
                {rules.sessions && <li>Sirf {rules.sessions.join(" / ")} session mein</li>}
              </ul>
              <button type="button" onClick={() => setRules(null)} className="mt-3 text-sm text-primary hover:underline">
                ← Candle / rules badlo
              </button>
            </div>

            <div className="space-y-2">
              <h2 className="text-lg font-bold">Nuksaan kahan kaatna hai, faayda kahan lena hai?</h2>
              <div role="radiogroup" aria-label="Stop aur target" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {RISKS.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    role="radio"
                    aria-checked={risk === r.id}
                    onClick={() => setRisk(r.id)}
                    className={cn("flex flex-col gap-1 rounded-2xl border-2 p-4 text-left", risk === r.id ? "border-primary bg-primary/10" : "bg-card hover:bg-muted/40")}
                  >
                    <span className="font-semibold">{r.title}</span>
                    <span className="text-xs leading-relaxed text-muted-foreground">{r.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="why" className="block text-sm font-semibold">
                Yeh setup kyun chalna chahiye? <span className="font-normal text-muted-foreground">(ek line, test se pehle — imaandari ka niyam)</span>
              </label>
              <textarea
                id="why"
                rows={2}
                value={why}
                onChange={(e) => setWhy(e.target.value)}
                className="w-full resize-none rounded-xl border bg-card px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              />
            </div>

            <p className="text-sm text-muted-foreground">
              Test practice data (2021–2024) pe, mehenge kharche ke saath chalega. Final exam data band rahega. Har chart-idea ek hi family
              (&quot;chart-idea&quot;) mein ginta hai, isliye jitne zyada try, pass ka bar utna ooncha.
            </p>
            <TestProgress busy={test.busy} pct={pct} error={test.error} />
            <button
              type="button"
              disabled={test.busy}
              onClick={() => void test.run(spec, "A")}
              className="inline-flex h-12 items-center gap-2 rounded-xl bg-primary px-6 text-base font-semibold text-primary-foreground disabled:opacity-50"
            >
              {test.busy ? "Test chal raha hai…" : "Test chalao"}
              <ArrowRight className="size-4" />
            </button>
          </section>
          <aside className="space-y-3">
            <p className="text-xs font-semibold tracking-[0.18em] text-primary">YEH RULE CHART PE KAHAN BANTA HAI</p>
            <IdeaPreview spec={spec} />
          </aside>
        </div>
      )}
    </div>
  );
}
