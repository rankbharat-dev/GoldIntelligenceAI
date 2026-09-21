"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const PAGES = [
  { href: "/", label: "Chart" },
  { href: "/costs", label: "Costs" },
];

export function AppNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Pages" className="flex items-center gap-1">
      {PAGES.map((p) => {
        const active = p.href === "/" ? pathname === "/" : pathname.startsWith(p.href);
        return (
          <Link
            key={p.href}
            href={p.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              active ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {p.label}
          </Link>
        );
      })}
    </nav>
  );
}
