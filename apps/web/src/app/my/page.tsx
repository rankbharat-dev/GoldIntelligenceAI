"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { JourneyList } from "@/components/simple/journey-list";
import { STAGES } from "@/components/simple/ui";

// Simple mode · "Meri strategies": every saved strategy as a journey with one next step.

export default function MyStrategies() {
  const [q, setQ] = useState("");
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 md:px-8">
      <header className="flex flex-wrap items-end gap-3">
        <div className="mr-auto space-y-1">
          <h1 className="text-3xl font-bold">Meri strategies</h1>
          <p className="text-muted-foreground">Aapki, AI ki aur engine ki har strategy — kahan tak pahunchi aur agla step kya hai.</p>
        </div>
        <Link href="/idea" className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-5 font-semibold text-primary-foreground">
          <Plus className="size-4" />
          Naya idea
        </Link>
      </header>

      <div className="rounded-2xl border bg-card px-4 py-3 text-sm text-muted-foreground">
        <b className="text-foreground">Safar:</b> {STAGES.join(" → ")}. Hari = pass, laal = fail, sona = abhi yahan. Har strategy ko har kadam imaandari se paar karna hota hai.
      </div>

      <section aria-label="Strategies" className="overflow-hidden rounded-2xl border bg-card">
        <div className="flex items-center gap-2 px-4 py-3">
          <Search className="size-4 text-muted-foreground" />
          <label htmlFor="q" className="sr-only">
            Strategy dhoondo
          </label>
          <input
            id="q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Naam se dhoondo…"
            className="h-9 flex-1 bg-transparent text-sm outline-none"
          />
        </div>
        <JourneyList search={q} />
      </section>

      <p className="text-sm text-muted-foreground">
        Versions, families aur saari technical history:{" "}
        <Link href="/strategies" className="text-primary hover:underline">
          Expert library
        </Link>
        .
      </p>
    </div>
  );
}
