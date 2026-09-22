"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";

import { ago } from "@/components/ceo/bits";

import { useJourneys, type StrategyJourney } from "./strategies";
import { Pill, Tracker, useTestRun } from "./ui";

const btn =
  "inline-flex h-10 items-center gap-1.5 rounded-lg border border-primary/40 px-3.5 text-sm font-semibold text-primary hover:bg-primary/10 disabled:opacity-60";

function Row({ j }: { j: StrategyJourney }) {
  const test = useTestRun();
  return (
    <li className="grid grid-cols-1 items-center gap-3 border-t px-4 py-3.5 md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.4fr)_auto_auto]">
      <div className="min-w-0">
        <Link href={`/strategy?spec=${j.row.spec_hash}`} className="block truncate text-[15px] font-semibold hover:text-primary hover:underline">
          {j.row.name}
        </Link>
        <p className="text-xs text-muted-foreground">
          {j.by} · {ago(j.row.last_run ?? j.row.created_at)}
        </p>
        {test.error && <p className="text-xs text-red-300">{test.error}</p>}
      </div>
      <div>
        <Pill tone={j.status.tone}>{j.status.text}</Pill>
      </div>
      <Tracker states={j.stages} compact />
      <div className="md:justify-self-end">
        {j.next.action.kind === "link" ? (
          <Link href={j.next.action.href} className={btn}>
            {j.next.label}
            <ArrowRight className="size-4" />
          </Link>
        ) : (
          <button type="button" className={btn} disabled={test.busy} onClick={() => void test.run(j.row.spec, "A")}>
            {test.busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {test.busy ? `Test chal raha hai${test.job ? ` · ${Math.round(test.job.progress * 100)}%` : ""}` : j.next.label}
            {!test.busy && <ArrowRight className="size-4" />}
          </button>
        )}
      </div>
    </li>
  );
}

/** Saved strategies with their stage, plain status and one next step. */
export function JourneyList({ limit, search = "" }: { limit?: number; search?: string }) {
  const { rows, loading, error } = useJourneys();
  if (error) return <p className="px-4 pb-4 text-sm text-red-300">Strategies load nahi hui: {String(error)}</p>;
  if (loading) return <p className="px-4 pb-4 text-sm text-muted-foreground">Load ho raha hai…</p>;
  const q = search.trim().toLowerCase();
  const list = rows.filter((r) => !q || r.row.name.toLowerCase().includes(q) || r.row.family.toLowerCase().includes(q));
  if (!list.length)
    return (
      <p className="px-4 pb-4 text-sm text-muted-foreground">
        {q ? "Is naam ki koi strategy nahi mili." : "Abhi koi strategy nahi. "}
        {!q && (
          <Link href="/idea" className="text-primary hover:underline">
            Pehla idea test karo →
          </Link>
        )}
      </p>
    );
  return (
    <ul>
      {list.slice(0, limit).map((j) => (
        <Row key={j.row.spec_hash} j={j} />
      ))}
    </ul>
  );
}
