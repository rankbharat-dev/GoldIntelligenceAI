"use client";

import { ArrowLeft, ArrowRight, CircleHelp, PenTool } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { IdeaPreview } from "@/components/simple/idea-preview";
import { TestProgress, useTestRun } from "@/components/simple/ui";
import { byId, PATTERNS, previewSpecOf, RISKS, SESSIONS, SIDES, sentenceOf, specOf, TERMS, type Choice, type WizardAnswers } from "@/lib/plain";
import { cn } from "@/lib/utils";

// Simple mode · "Mera idea test karo": five plain questions → a real strategy spec →
// saved and backtested on tier A (practice data) → the plain result page.

type Key = "pattern" | "session" | "side" | "risk";

const STEPS: { key: Key | "review"; name: string; q: string; help: string }[] = [
  { key: "pattern", name: "Idea", q: "Aapka idea kis cheez pe hai?", help: "Jo pattern aap chart pe dekhte ho, woh chuno. Engine use exact rules mein badal dega." },
  { key: "session", name: "Kab", q: "Din ke kis time trade karein?", help: "Gold alag time pe alag behave karta hai. Pata na ho to \"Poora din\" chuno." },
  { key: "side", name: "Disha", q: "Kis taraf trade lena hai?", help: "Buy = price upar jaaye to kamai. Sell = neeche jaaye to kamai." },
  { key: "risk", name: "Nuksaan / Faayda", q: "Nuksaan kahan kaatna hai, faayda kahan lena hai?", help: "Bada target = kharcha kamai ka chhota hissa. Chhota target = kharcha zyada chubhta hai." },
  { key: "review", name: "Check", q: "Yeh rahi aapki strategy — sahi hai?", help: "Aam bhasha mein padho. Kuch galat ho to \"Peeche\" jaake badlo." },
];

const OPTIONS: Record<Key, Choice[]> = { pattern: PATTERNS, session: SESSIONS, side: SIDES, risk: RISKS };

export default function IdeaWizard() {
  const [step, setStep] = useState(0);
  const [a, setA] = useState<WizardAnswers>({ pattern: null, session: null, side: null, risk: null, why: "" });
  const test = useTestRun();
  const pattern = byId(PATTERNS, a.pattern);
  const fixedSession = !!pattern?.fixedSessions;
  const cur = STEPS[step];
  const review = cur.key === "review";
  const chosen = review ? null : a[cur.key as Key];
  const canNext = review || !!chosen || (cur.key === "session" && fixedSession);
  const spec = specOf(a);
  const preview = previewSpecOf(a);

  const go = (d: number) => {
    let s = step + d;
    if (STEPS[s]?.key === "session" && fixedSession) s += d; // momentum idea is London-only
    setStep(Math.min(Math.max(s, 0), STEPS.length - 1));
  };

  const summary: { label: string; value: string | null }[] = [
    { label: "Idea", value: pattern?.title ?? null },
    { label: "Kab", value: fixedSession ? "London session (is idea ke saath fix)" : (byId(SESSIONS, a.session)?.title ?? null) },
    { label: "Disha", value: byId(SIDES, a.side)?.title ?? null },
    { label: "Nuksaan / Faayda", value: byId(RISKS, a.risk)?.title ?? null },
  ];
  const pct = test.job ? Math.round(test.job.progress * 100) : null;

  return (
    <div className="grid min-h-full grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(380px,40%)]">
      <section className="flex flex-col gap-6 px-4 py-8 md:px-10">
        <div className="space-y-2">
          <div className="flex justify-between text-sm text-muted-foreground">
            <span>
              Sawaal {step + 1} / {STEPS.length}
            </span>
            <span>{cur.name}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
          </div>
        </div>

        <div className="space-y-1.5">
          <h1 className="text-2xl font-bold md:text-3xl">{cur.q}</h1>
          <p className="text-muted-foreground">{cur.help}</p>
        </div>

        {!review && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="radiogroup" aria-label={cur.q}>
            {OPTIONS[cur.key as Key].map((o) => {
              const on = chosen === o.id;
              return (
                <button
                  key={o.id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setA({ ...a, [cur.key]: o.id })}
                  className={cn(
                    "flex min-h-28 flex-col gap-1.5 rounded-2xl border-2 p-5 text-left transition-colors",
                    on ? "border-primary bg-primary/10" : "border-border bg-card hover:bg-muted/40",
                  )}
                >
                  <span className="text-base font-semibold">{o.title}</span>
                  <span className="text-sm leading-relaxed text-muted-foreground">{o.desc}</span>
                </button>
              );
            })}
            {cur.key === "pattern" && (
              <Link
                href="/idea/chart"
                className="flex min-h-28 flex-col gap-1.5 rounded-2xl border-2 border-dashed p-5 text-left hover:bg-muted/40"
              >
                <span className="flex items-center gap-2 text-base font-semibold">
                  <PenTool className="size-4 text-primary" />
                  Chart pe khud dikhaunga
                </span>
                <span className="text-sm leading-relaxed text-muted-foreground">
                  Asli chart pe us candle pe click karo jahan aap entry lete — engine us candle ke facts se rules bana dega.
                </span>
              </Link>
            )}
          </div>
        )}

        {review && (
          <div className="space-y-4">
            <p className="rounded-2xl border border-primary/40 bg-primary/10 px-5 py-4 text-lg leading-relaxed">{sentenceOf(a)}</p>
            <div className="space-y-1.5">
              <label htmlFor="why" className="block text-sm font-semibold">
                Yeh idea kyun chalna chahiye?{" "}
                <span className="font-normal text-muted-foreground">(ek line — test se pehle likhna imaandari ka niyam hai; khaali chhodo to hum ek default likh denge)</span>
              </label>
              <textarea
                id="why"
                rows={3}
                value={a.why}
                onChange={(e) => setA({ ...a, why: e.target.value })}
                placeholder={pattern?.hypothesis}
                className="w-full resize-none rounded-xl border bg-card px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              />
            </div>
            <p className="flex items-start gap-2 text-sm text-muted-foreground">
              <CircleHelp className="mt-0.5 size-4 shrink-0 text-primary" />
              Test practice data (2021–2024) pe chalega, mehenge kharche ke saath. Final exam data band rahega. Yeh test is idea ki ek &quot;koshish&quot; gina jaayega.
            </p>
            <TestProgress busy={test.busy} pct={pct} error={test.error} />
          </div>
        )}

        <div className="mt-auto flex items-center justify-between gap-3 pt-4">
          <button
            type="button"
            onClick={() => go(-1)}
            disabled={step === 0 || test.busy}
            className="inline-flex h-12 items-center gap-2 rounded-xl border px-5 text-sm disabled:opacity-40"
          >
            <ArrowLeft className="size-4" />
            Peeche
          </button>
          {review ? (
            <button
              type="button"
              disabled={!spec || test.busy}
              onClick={() => spec && void test.run(spec, "A")}
              className="inline-flex h-12 items-center gap-2 rounded-xl bg-primary px-6 text-base font-semibold text-primary-foreground disabled:opacity-50"
            >
              {test.busy ? "Test chal raha hai…" : "Test chalao"}
              <ArrowRight className="size-4" />
            </button>
          ) : (
            <button
              type="button"
              disabled={!canNext}
              onClick={() => go(1)}
              className="inline-flex h-12 items-center gap-2 rounded-xl bg-primary px-6 text-base font-semibold text-primary-foreground disabled:bg-muted disabled:text-muted-foreground"
            >
              Aage
              <ArrowRight className="size-4" />
            </button>
          )}
        </div>
      </section>

      <aside aria-label="Aapki strategy abhi tak" className="flex flex-col gap-4 border-t bg-sidebar px-5 py-8 lg:sticky lg:top-0 lg:max-h-dvh lg:overflow-y-auto lg:border-t-0 lg:border-l">
        <p className="text-xs font-semibold tracking-[0.18em] text-primary">AAPKI STRATEGY — LIVE</p>
        <p className={cn("rounded-xl border px-4 py-3 text-[15px] leading-relaxed", pattern ? "border-primary/40 bg-primary/10" : "text-muted-foreground")}>
          {pattern ? sentenceOf(a) : "Jaise-jaise aap chunoge, aapki strategy yahan aam bhasha mein banti jaayegi."}
        </p>
        <IdeaPreview spec={preview} />
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {summary.map((s) => (
            <div key={s.label} className="border-b pb-2">
              <p className="text-[11px] text-muted-foreground">{s.label}</p>
              <p className={cn("text-sm font-medium", !s.value && "text-muted-foreground/60")}>{s.value ?? "abhi chuna nahi"}</p>
            </div>
          ))}
        </div>
        <div className="rounded-xl bg-card p-4 text-sm leading-relaxed">
          <p className="mb-1 flex items-center gap-2 font-semibold text-primary">
            <CircleHelp className="size-4" />
            &quot;× aam candle&quot; kya hai?
          </p>
          {TERMS.atr.plain} (Expert naam: ATR)
        </div>
      </aside>
    </div>
  );
}
