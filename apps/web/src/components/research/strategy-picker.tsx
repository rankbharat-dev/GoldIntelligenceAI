"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { research } from "@/lib/research";

import { inputCls } from "./bits";

/** Choose a saved strategy (the library), or go build one. */
export function StrategyPicker({ value, onChange }: { value: string | null; onChange: (hash: string) => void }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["strategies"], queryFn: research.strategies });
  if (error) return <p className="text-xs text-red-400">Library unavailable: {String(error)}</p>;
  if (isLoading) return <p className="text-xs text-muted-foreground">Loading library…</p>;
  if (!data?.length)
    return (
      <p className="text-xs text-muted-foreground">
        No saved strategies yet —{" "}
        <Link className="text-primary hover:underline" href="/strategy-lab">
          build one in the Strategy Lab
        </Link>
        .
      </p>
    );
  return (
    <select className={inputCls} aria-label="Strategy" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled>
        Choose a saved strategy…
      </option>
      {data.map((s) => (
        <option key={s.spec_hash} value={s.spec_hash}>
          {s.favourite ? "★ " : ""}
          {s.name} · {s.family} · {s.spec_hash.slice(0, 8)}
        </option>
      ))}
    </select>
  );
}
