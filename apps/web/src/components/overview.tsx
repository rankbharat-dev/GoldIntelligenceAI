"use client";

import { Blocks, Library, PenTool, Sparkles, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { CandleChart, type DisplayZone } from "@/components/candle-chart";
import { DataHealth } from "@/components/data-health";
import { FeaturesPanel } from "@/components/features-panel";
import { LayerToggles, StructureLegend, useStructure, type Layer } from "@/components/structure-layer";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TIMEFRAMES, type Timeframe } from "@/lib/api";

const ZONES: Record<DisplayZone, string> = {
  UTC: "UTC",
  "America/New_York": "New York",
  "Asia/Kolkata": "India (IST)",
};

// Strategy Lab entry points from the reference design. They show what each method will do
// and which phase delivers it — never invented counts (requirement U2).
const METHODS: { title: string; body: string; icon: LucideIcon; phase: number; href?: string }[] = [
  {
    title: "AI Strategy Discovery",
    body: "The engine proposes hypotheses, tests them on the data and keeps both accepted and rejected ones.",
    icon: Sparkles,
    phase: 8,
    href: "/strategy-lab?mode=ai",
  },
  {
    title: "Visual Strategy Builder",
    body: "Entry conditions, filters, exits and sizing from forms — no code. Blocks later.",
    icon: Blocks,
    phase: 5,
    href: "/strategy-lab",
  },
  {
    title: "Chart-Based Creator",
    body: "Mark a pattern on the chart; it becomes measurable rules you review before any test.",
    icon: PenTool,
    phase: 7,
    href: "/strategy-lab?mode=chart",
  },
  {
    title: "Strategy Library",
    body: "Every spec, version and test result saved — continue or compare later.",
    icon: Library,
    phase: 5,
    href: "/strategies",
  },
];

export function OverviewPage() {
  const [tf, setTf] = useState<Timeframe>("M5");
  const [zone, setZone] = useState<DisplayZone>("Asia/Kolkata");
  // The clicked bar belongs to the timeframe it was clicked on; switching timeframe clears it.
  const [selected, setSelected] = useState<{ tf: Timeframe; time: number } | null>(null);
  const asideRef = useRef<HTMLElement>(null);
  const selectedTime = selected?.tf === tf ? selected.time : null;

  const onSelect = useCallback((time: number) => setSelected({ tf, time }), [tf]);
  const [layers, setLayers] = useState<Set<Layer>>(() => new Set<Layer>(["levels", "lines"]));
  const [range, setRange] = useState<[number, number] | null>(null);
  const onRange = useCallback((a: number, b: number) => setRange([a, b]), []);
  const structure = useStructure(range, layers);

  // On a phone the panel sits below the chart: bring it into view after a click.
  useEffect(() => {
    if (selectedTime !== null && window.matchMedia("(max-width: 1023px)").matches) {
      asideRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selectedTime]);

  return (
    <div className="grid grid-cols-1 gap-3 p-3 xl:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-3">
        <section className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
          <div className="flex flex-wrap items-center gap-3 border-b px-3 py-2">
            <div className="mr-auto">
              <h1 className="text-sm font-semibold">XAUUSD</h1>
              <p className="text-xs text-muted-foreground">Gold Spot / U.S. Dollar · research data, not a trading terminal</p>
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
                <ToggleGroupItem
                  key={t}
                  value={t}
                  className="px-3 font-mono text-xs data-pressed:border-primary/60 data-pressed:text-primary"
                >
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
          </div>
          <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
            <span className="text-[11px] text-muted-foreground">Structure (M5 geometry):</span>
            <LayerToggles value={layers} onChange={setLayers} loading={structure.loading} />
            {structure.error && <span className="text-[11px] text-red-400">{structure.error.message}</span>}
          </div>
          <div className="relative h-[60dvh] min-h-[420px]">
            <CandleChart
              timeframe={tf}
              zone={zone}
              selected={selectedTime}
              onSelect={onSelect}
              markers={structure.markers}
              overlays={structure.overlays}
              onRangeChange={onRange}
            />
          </div>
          {layers.size > 0 && (
            <div className="border-t px-3 py-1.5">
              <StructureLegend />
            </div>
          )}
        </section>

        <section aria-label="Strategy Lab" className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-4">
          {METHODS.map((m) => {
            const Icon = m.icon;
            return (
              <div key={m.title} className="flex flex-col gap-2 rounded-xl bg-card p-3 ring-1 ring-foreground/10">
                <div className="flex items-start gap-3">
                  <span className="rounded-lg border border-primary/30 bg-primary/10 p-2">
                    <Icon className="size-5 text-primary" strokeWidth={1.6} aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold">{m.title}</h2>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{m.body}</p>
                  </div>
                </div>
                {m.href ? (
                  <Link
                    href={m.href}
                    className="mt-auto rounded-md border border-primary/40 px-2 py-1.5 text-center text-[11px] text-primary hover:bg-primary/10"
                  >
                    Open
                  </Link>
                ) : (
                  <p className="mt-auto rounded-md border border-dashed px-2 py-1.5 text-center text-[11px] text-muted-foreground">
                    Arrives in Phase {m.phase}
                  </p>
                )}
              </div>
            );
          })}
        </section>
      </div>

      <aside ref={asideRef} className="scroll-mt-2 space-y-3">
        {selectedTime !== null ? (
          <FeaturesPanel time={selectedTime} tf={tf} zone={zone} onClear={() => setSelected(null)} />
        ) : (
          <p className="rounded-lg border border-dashed px-3 py-2.5 text-xs text-muted-foreground">
            Click any candle to see its features — anatomy, sequence, session, volatility, M15/H1 context and hygiene
            flags, each known no later than the bar&apos;s close.
          </p>
        )}
        <DataHealth />
      </aside>
    </div>
  );
}
