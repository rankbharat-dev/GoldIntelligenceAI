"use client";

import { ArrowRight, Bot, ChartLine, Clock, Lightbulb, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { TERMS, type TermKey } from "@/lib/plain";
import { cn } from "@/lib/utils";

import { JourneyList } from "./journey-list";
import { STAGES } from "./ui";

const GOALS: { icon: LucideIcon; title: string; body: string; time: string; href: string; cta: string; primary?: boolean }[] = [
  {
    icon: Lightbulb,
    title: "Mera idea test karo",
    body: "5 aasaan sawaal. Koi formula ya code nahi. Aakhir mein seedha jawab: kaam karta hai ya nahi.",
    time: "~5 min",
    href: "/idea",
    cta: "Shuru karo",
    primary: true,
  },
  {
    icon: Bot,
    title: "AI se research karwao",
    body: "Apna sawaal Hinglish mein likho. AI team plan banakar test karegi aur simple report degi.",
    time: "AI kaam karta hai",
    href: "/ceo-lab",
    cta: "Sawaal likho",
  },
  {
    icon: ChartLine,
    title: "Market samjho",
    body: "Kaunse chart patterns ke baad gold sach mein kuch karta hai — bina strategy banaye.",
    time: "seekhne ke liye",
    href: "/learn",
    cta: "Patterns dekho",
  },
];

const LEARN: { term: TermKey; label: string }[] = [
  { term: "r", label: "R kya hai?" },
  { term: "tier", label: "Practice / Check / Final exam data" },
  { term: "costs", label: "Kharcha itna zaroori kyun?" },
];

export function SimpleHome() {
  const [learn, setLearn] = useState<TermKey | null>(null);
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-7 px-4 py-8 md:px-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight md:text-4xl">Namaste! Aaj kya karna hai?</h1>
        <p className="text-base text-muted-foreground">
          Gold ke purane 5 saal ke data pe idea test karo. Kharche ke baad bhi kamai ho, tabhi pass.
        </p>
      </header>

      <section aria-label="Aap kya karna chahte ho" className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {GOALS.map((g) => (
          <Link
            key={g.title}
            href={g.href}
            className={cn(
              "group flex min-h-60 flex-col gap-4 rounded-2xl border p-6 transition-colors",
              g.primary ? "border-primary/40 bg-primary/10 hover:bg-primary/15" : "bg-card hover:bg-muted/40",
            )}
          >
            <span className="flex size-12 items-center justify-center rounded-full bg-primary text-primary-foreground">
              <g.icon className="size-6" strokeWidth={1.8} />
            </span>
            <span className="space-y-1.5">
              <span className="block text-xl font-bold">{g.title}</span>
              <span className="block text-sm leading-relaxed text-muted-foreground">{g.body}</span>
            </span>
            <span className="mt-auto flex items-center justify-between text-sm">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Clock className="size-4" />
                {g.time}
              </span>
              <span className="flex items-center gap-1 font-semibold text-primary">
                {g.cta}
                <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
              </span>
            </span>
          </Link>
        ))}
      </section>

      <section aria-label="Meri strategies" className="overflow-hidden rounded-2xl border bg-card">
        <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-4">
          <h2 className="text-lg font-bold">Meri strategies</h2>
          <span className="text-xs text-muted-foreground">Safar: {STAGES.join(" → ")}</span>
        </div>
        <JourneyList limit={4} />
        <div className="border-t px-4 py-3 text-right">
          <Link href="/my" className="text-sm font-semibold text-primary hover:underline">
            Saari strategies dekho →
          </Link>
        </div>
      </section>

      <section aria-label="Seekho" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">1 minute mein samjho:</span>
          {LEARN.map((l) => (
            <button
              key={l.term}
              type="button"
              aria-pressed={learn === l.term}
              onClick={() => setLearn(learn === l.term ? null : l.term)}
              className={cn(
                "h-9 rounded-full border px-4 text-sm",
                learn === l.term ? "border-primary/60 bg-primary/10 text-primary" : "bg-card hover:bg-muted/40",
              )}
            >
              {l.label}
            </button>
          ))}
        </div>
        {learn && <p className="max-w-3xl rounded-xl border bg-card px-4 py-3 text-sm leading-relaxed">{TERMS[learn].plain}</p>}
      </section>
    </div>
  );
}
