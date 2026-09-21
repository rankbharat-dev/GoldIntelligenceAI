"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  CandlestickChart,
  Database,
  FlaskConical,
  History,
  LayoutDashboard,
  Library,
  Menu,
  ScanSearch,
  ShieldCheck,
  SlidersHorizontal,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { JobTray } from "@/components/research/jobs";
import { fetchSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  hint: string;
  icon: LucideIcon;
  href?: string; // absent = not built yet
  phase?: number; // roadmap phase that builds it (MASTER_PROMPT §8)
}

// Navigation from new_reference_image.png, extended with the owner's four additions
// (requirements/2026-09-21_ui-redesign-research-workspace.md). Unbuilt pages stay visible
// but disabled, labelled with the phase that delivers them.
const NAV: NavItem[] = [
  { label: "Overview", hint: "Chart workspace", icon: LayoutDashboard, href: "/" },
  { label: "Data Center", hint: "Data health · costs", icon: Database, href: "/costs" },
  { label: "Behaviour Explorer", hint: "Sequences · regimes · S/R", icon: ScanSearch, phase: 7 },
  { label: "Strategy Lab", hint: "AI · Visual · From chart", icon: FlaskConical, href: "/strategy-lab" },
  { label: "Backtest", hint: "Test performance", icon: History, href: "/backtest" },
  { label: "Optimize", hint: "Parameter tuning", icon: SlidersHorizontal, href: "/optimize" },
  { label: "Validate", hint: "Out-of-sample · robustness", icon: ShieldCheck, href: "/validate" },
  { label: "Research Pipeline", hint: "Hypotheses · runs", icon: Workflow, phase: 8 },
  { label: "My Strategies", hint: "Library · versions · trials", icon: Library, href: "/strategies" },
  { label: "AI Assistant", hint: "Ideas · explanations", icon: Bot, phase: 10 },
];

function isActive(href: string, pathname: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <CandlestickChart className="size-7 text-primary" strokeWidth={1.6} aria-hidden />
      <div className="leading-tight">
        <p className="text-sm font-semibold tracking-wide text-primary">CANDLE INTELLIGENCE</p>
        <p className="text-[10px] tracking-[0.14em] text-muted-foreground">XAUUSD STRATEGY RESEARCH LAB</p>
      </div>
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Pages" className="space-y-0.5">
      {NAV.map((item) => {
        const Icon = item.icon;
        const body = (
          <>
            <Icon className="mt-0.5 size-[18px] shrink-0" strokeWidth={1.6} aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium">{item.label}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{item.hint}</span>
            </span>
            {item.phase !== undefined && (
              <span className="mt-0.5 rounded border px-1 font-mono text-[10px] text-muted-foreground">P{item.phase}</span>
            )}
          </>
        );
        if (!item.href) {
          return (
            <div
              key={item.label}
              aria-disabled
              title={`Arrives in Phase ${item.phase}`}
              className="flex cursor-default items-start gap-3 rounded-lg px-3 py-2 text-sidebar-foreground/45"
            >
              {body}
            </div>
          );
        }
        const active = isActive(item.href, pathname);
        return (
          <Link
            key={item.label}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-start gap-3 rounded-lg px-3 py-2 transition-colors",
              active
                ? "bg-sidebar-accent text-sidebar-accent-foreground ring-1 ring-primary/35 [&_svg]:text-primary"
                : "text-sidebar-foreground hover:bg-muted",
            )}
          >
            {body}
          </Link>
        );
      })}
    </nav>
  );
}

function EngineStatus() {
  const { data, isError, isLoading } = useQuery({ queryKey: ["summary"], queryFn: () => fetchSummary() });
  const ok = !!data && !isError;
  return (
    <div className="space-y-1.5 rounded-lg border bg-background/40 px-3 py-2.5 text-[11px]">
      <p className="flex items-center gap-2 text-xs font-medium">
        <span
          className={cn("size-2 rounded-full", isLoading ? "bg-muted-foreground" : ok ? "bg-emerald-500" : "bg-red-500")}
          aria-hidden
        />
        {isLoading ? "Connecting…" : ok ? "Local engine connected" : "Engine offline"}
      </p>
      <p className="truncate text-muted-foreground" title={ok ? data.dataset_id : undefined}>
        {ok ? `${data.broker_server} · ${data.bars.M1.toLocaleString()} M1 bars` : "Start the API with ci-api"}
      </p>
      <p className="text-muted-foreground">Research only · no trading</p>
    </div>
  );
}

function DataRange() {
  const { data } = useQuery({ queryKey: ["summary"], queryFn: () => fetchSummary() });
  if (!data) return null;
  const [from, to] = data.quality.coverage.research_window_utc;
  const years = data.quality.coverage.years;
  return (
    <span className="rounded-md border px-2.5 py-1 font-mono text-xs" title={`${data.broker} · ${data.broker_server}`}>
      {from.slice(0, 7)} → {to.slice(0, 7)} <span className="text-muted-foreground">({years.toFixed(1)} y)</span>
    </span>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex min-h-dvh lg:h-dvh">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col gap-5 border-r bg-sidebar p-3 lg:flex">
        <div className="px-2 pt-1">
          <Brand />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <NavList />
        </div>
        <EngineStatus />
      </aside>

      {/* Phone drawer */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button aria-label="Close menu" className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="relative flex h-full w-72 max-w-[85vw] flex-col gap-4 overflow-y-auto border-r bg-sidebar p-3">
            <div className="flex items-center justify-between px-2 pt-1">
              <Brand />
              <button aria-label="Close menu" className="rounded-md p-1 hover:bg-muted" onClick={() => setOpen(false)}>
                <X className="size-5" />
              </button>
            </div>
            <NavList onNavigate={() => setOpen(false)} />
            <EngineStatus />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
        <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <button
            aria-label="Open menu"
            className="-ml-1 rounded-md p-1 hover:bg-muted lg:hidden"
            onClick={() => setOpen(true)}
          >
            <Menu className="size-5" />
          </button>
          <p className="mr-auto hidden text-[11px] tracking-[0.25em] text-muted-foreground italic md:block">
            PAST DATA · NEW IDEAS · HONEST EDGE
          </p>
          <JobTray />
          <span className="rounded-md border border-primary/40 px-2.5 py-1 text-xs font-semibold text-primary">XAUUSD</span>
          <DataRange />
        </header>
        <div className="flex-1 lg:min-h-0 lg:overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
