"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  BrainCircuit,
  Briefcase,
  CandlestickChart,
  Database,
  FlaskConical,
  ChartLine,
  History,
  House,
  LayoutDashboard,
  Library,
  Lightbulb,
  Menu,
  PlayCircle,
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
import { setMode, useMode, type Mode } from "@/lib/mode";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  hint: string;
  icon: LucideIcon;
  href?: string; // absent = not built yet
  phase?: number; // roadmap phase that builds it (MASTER_PROMPT §8)
  match?: string[]; // extra paths that highlight this item
}

interface NavSection {
  title: string | null; // null = the top item(s) without a heading
  hint?: string;
  items: NavItem[];
}

// Both modes share the four primary sections (requirement 2026-09-22_discovery-lab-ui.md):
// Explore Market → Create & Discover → Test & Analyze → My Strategy Lab.
// Simple mode: goal-first pages in plain Hinglish.
const SIMPLE_NAV: NavSection[] = [
  { title: null, items: [{ label: "Home", hint: "Aaj kya karna hai?", icon: House, href: "/" }] },
  {
    title: "Explore Market",
    hint: "Gold ko samjho",
    items: [
      { label: "Market samjho", hint: "Pattern ke baad gold kya karta", icon: ChartLine, href: "/learn" },
      { label: "Gold chart", hint: "Candles · indicators · levels", icon: CandlestickChart, href: "/chart" },
    ],
  },
  {
    title: "Create & Discover",
    hint: "Strategy banao ya AI se dhoondho",
    items: [
      { label: "Idea se banao", hint: "5 sawaal · live chart preview", icon: Lightbulb, href: "/idea", match: ["/idea/chart"] },
      { label: "AI Research", hint: "AI team ko mission do, baat karo", icon: Bot, href: "/ceo-lab" },
    ],
  },
  {
    title: "Test & Analyze",
    hint: "Result, graph, chart pe trades",
    items: [{ label: "Results & replay", hint: "Har test · chart pe verify", icon: PlayCircle, href: "/results", match: ["/result"] }],
  },
  {
    title: "My Strategy Lab",
    hint: "Safar, versions, agla step",
    items: [{ label: "Meri strategies", hint: "Kahan tak pahunchi, agla step", icon: Library, href: "/my", match: ["/strategy"] }],
  },
];

// Expert mode: every research page (new_reference_image.png + the owner's additions,
// requirements/2026-09-21_ui-redesign-research-workspace.md), grouped the same way.
const NAV: NavSection[] = [
  {
    title: "Explore Market",
    items: [
      { label: "Overview", hint: "Chart workspace", icon: LayoutDashboard, href: "/", match: ["/chart"] },
      { label: "Data Center", hint: "Data health · costs", icon: Database, href: "/costs" },
      { label: "Behaviour Explorer", hint: "Sequences · regimes · S/R", icon: ScanSearch, href: "/explorer" },
    ],
  },
  {
    title: "Create & Discover",
    items: [
      { label: "CEO Work Lab", hint: "Mission do · AI agents research karein", icon: Briefcase, href: "/ceo-lab" },
      { label: "Strategy Lab", hint: "AI · Visual · From chart", icon: FlaskConical, href: "/strategy-lab" },
      { label: "Research Pipeline", hint: "Hypotheses · runs", icon: Workflow, href: "/pipeline" },
      { label: "AI Assistant", hint: "Ideas · explanations", icon: Bot, href: "/assistant" },
    ],
  },
  {
    title: "Test & Analyze",
    items: [
      { label: "Backtest", hint: "Test performance", icon: History, href: "/backtest" },
      { label: "Optimize", hint: "Parameter tuning", icon: SlidersHorizontal, href: "/optimize" },
      { label: "Validate", hint: "Out-of-sample · robustness", icon: ShieldCheck, href: "/validate" },
      { label: "ML Lab", hint: "Filters vs rule baseline", icon: BrainCircuit, href: "/ml" },
    ],
  },
  {
    title: "My Strategy Lab",
    items: [{ label: "My Strategies", hint: "Library · versions · trials", icon: Library, href: "/strategies" }],
  },
];

function isActive(item: NavItem, pathname: string) {
  const hit = (h: string) => (h === "/" ? pathname === "/" : pathname === h || pathname.startsWith(`${h}/`));
  return hit(item.href!) || (item.match ?? []).some(hit);
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
  const mode = useMode();
  const sections = mode === "simple" ? SIMPLE_NAV : NAV;
  return (
    <nav aria-label="Pages" className="space-y-3">
      {sections.map((sec, si) => (
        <div key={sec.title ?? si} className="space-y-0.5">
          {sec.title && (
            <p className="px-3 pt-1 pb-0.5 text-[10px] font-semibold tracking-[0.16em] text-primary/80 uppercase" title={sec.hint}>
              {sec.title}
            </p>
          )}
          {sec.items.map((item) => (
            <NavLink key={item.label} item={item} pathname={pathname} onNavigate={onNavigate} />
          ))}
        </div>
      ))}
    </nav>
  );
}

function NavLink({ item, pathname, onNavigate }: { item: NavItem; pathname: string; onNavigate?: () => void }) {
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
        aria-disabled
        title={`Arrives in Phase ${item.phase}`}
        className="flex cursor-default items-start gap-3 rounded-lg px-3 py-2 text-sidebar-foreground/45"
      >
        {body}
      </div>
    );
  }
  const active = isActive(item, pathname);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-start gap-3 rounded-lg px-3 py-1.5 transition-colors",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground ring-1 ring-primary/35 [&_svg]:text-primary"
          : "text-sidebar-foreground hover:bg-muted",
      )}
    >
      {body}
    </Link>
  );
}

/** Simple ↔ Expert. Expert shows every research page; nothing is removed either way. */
function ModeSwitch() {
  const mode = useMode();
  const opt = (m: Mode, label: string) => (
    <button
      type="button"
      role="radio"
      aria-checked={mode === m}
      onClick={() => setMode(m)}
      className={cn(
        "h-8 flex-1 rounded-md text-xs font-semibold transition-colors",
        mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
  return (
    <div className="space-y-1.5 rounded-lg border bg-background/40 px-3 py-2.5">
      <p className="text-[11px] text-muted-foreground">Mode</p>
      <div role="radiogroup" aria-label="Mode" className="flex gap-1 rounded-lg bg-muted/50 p-0.5">
        {opt("simple", "Simple")}
        {opt("expert", "Expert")}
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">
        {mode === "simple" ? "Expert mein saare advanced research tools (backtest, optimize, validate, pipeline…) milenge." : "Simple mein aasaan Hinglish pages — wahi engine, wahi numbers."}
      </p>
    </div>
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
        <ModeSwitch />
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
            <ModeSwitch />
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
