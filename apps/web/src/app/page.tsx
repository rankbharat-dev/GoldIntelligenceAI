"use client";

import { useState } from "react";

import { CandleChart, type DisplayZone } from "@/components/candle-chart";
import { DataHealth } from "@/components/data-health";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TIMEFRAMES, type Timeframe } from "@/lib/api";

const ZONES: Record<DisplayZone, string> = {
  UTC: "UTC",
  "America/New_York": "New York",
  "Asia/Kolkata": "India (IST)",
};

export default function ChartViewerPage() {
  const [tf, setTf] = useState<Timeframe>("M5");
  const [zone, setZone] = useState<DisplayZone>("Asia/Kolkata");

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2.5">
        <div className="mr-auto">
          <h1 className="text-sm font-semibold tracking-tight">Candle Intelligence</h1>
          <p className="text-xs text-muted-foreground">XAUUSD · Chart Viewer · research data, not a trading terminal</p>
        </div>

        <ToggleGroup
          variant="outline"
          size="sm"
          spacing={0}
          value={[tf]}
          onValueChange={(v) => v[0] && setTf(v[0] as Timeframe)}
          aria-label="Timeframe"
        >
          {TIMEFRAMES.map((t) => (
            <ToggleGroupItem key={t} value={t} className="px-3 font-mono text-xs">
              {t}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        <Select items={ZONES} value={zone} onValueChange={(v) => v && setZone(v as DisplayZone)}>
          <SelectTrigger size="sm" className="w-36" aria-label="Time zone">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(ZONES) as DisplayZone[]).map((z) => (
              <SelectItem key={z} value={z}>
                {ZONES[z]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_340px]">
        <section className="relative min-h-[420px] border-b lg:border-b-0 lg:border-r">
          <CandleChart timeframe={tf} zone={zone} />
        </section>
        <aside className="overflow-y-auto p-3">
          <DataHealth />
        </aside>
      </main>
    </div>
  );
}
