"use client";

import { cn } from "@/lib/utils";

// Small form + display primitives shared by the research pages.

export const inputCls =
  "h-8 w-full min-w-0 rounded-md border border-input bg-input/30 px-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-50 aria-invalid:border-destructive";

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-snug text-muted-foreground/80">{hint}</span>}
    </label>
  );
}

export function NumberInput({
  value,
  onChange,
  step = 0.1,
  min,
  max,
  placeholder,
  disabled,
  ...rest
}: {
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  step?: number;
  min?: number;
  max?: number;
  placeholder?: string;
  disabled?: boolean;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <input
      type="number"
      inputMode="decimal"
      className={cn(inputCls, "font-mono tabular-nums")}
      value={value ?? ""}
      step={step}
      min={min}
      max={max}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      {...rest}
    />
  );
}

export function Chips<T extends string | number>({
  options,
  value,
  onChange,
  label = (o: T) => String(o),
}: {
  options: readonly T[];
  value: T[] | null | undefined;
  onChange: (v: T[] | null) => void;
  label?: (o: T) => string;
}) {
  const set = new Set(value ?? []);
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((o) => {
        const on = set.has(o);
        return (
          <button
            key={String(o)}
            type="button"
            aria-pressed={on}
            onClick={() => {
              const next = new Set(set);
              if (on) next.delete(o);
              else next.add(o);
              const arr = options.filter((x) => next.has(x));
              onChange(arr.length ? arr : null);
            }}
            className={cn(
              "rounded-md border px-2 py-0.5 text-xs transition-colors",
              on ? "border-primary/60 bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {label(o)}
          </button>
        );
      })}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "good" | "bad" | "muted";
}) {
  return (
    <div className="min-w-0 rounded-lg border bg-background/40 px-3 py-2">
      <p className="truncate text-[11px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "font-mono text-base font-semibold tabular-nums",
          tone === "good" && "text-emerald-400",
          tone === "bad" && "text-red-400",
          tone === "muted" && "text-muted-foreground",
        )}
      >
        {value}
      </p>
      {hint && <p className="truncate text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export const toneOf = (x: number | null | undefined) => (x == null ? "muted" : x > 0 ? "good" : x < 0 ? "bad" : undefined);

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl bg-card p-3 ring-1 ring-foreground/10", className)}>
      <div className="mb-2 flex flex-wrap items-start gap-2">
        <div className="mr-auto min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="text-xs leading-relaxed text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-3 px-1">
      <div className="mr-auto min-w-0">
        <h1 className="text-base font-semibold">{title}</h1>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 text-xs leading-relaxed",
        tone === "info" && "border-dashed text-muted-foreground",
        tone === "warn" && "border-amber-500/40 bg-amber-500/5 text-amber-200",
        tone === "error" && "border-red-500/40 bg-red-500/5 text-red-300",
      )}
    >
      {children}
    </div>
  );
}

/** A compact table for breakdown buckets (by year / session / …). */
export function BucketTable({ rows, keyName, label }: { rows: { [k: string]: unknown }[]; keyName: string; label: string }) {
  if (!rows?.length) return <p className="text-xs text-muted-foreground">No trades.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-1 pr-2 text-left font-normal">{label}</th>
            <th className="py-1 pr-2 text-right font-normal">Trades</th>
            <th className="py-1 pr-2 text-right font-normal">Expectancy</th>
            <th className="py-1 pr-2 text-right font-normal">Total</th>
            <th className="py-1 text-right font-normal">Win rate</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {rows.map((r) => {
            const e = r.expectancy_r as number | null;
            return (
              <tr key={String(r[keyName])} className="border-t border-border/60">
                <td className="py-1 pr-2 font-sans">{String(r[keyName])}</td>
                <td className="py-1 pr-2 text-right">{(r.n as number).toLocaleString()}</td>
                <td className={cn("py-1 pr-2 text-right", e != null && (e > 0 ? "text-emerald-400" : "text-red-400"))}>
                  {e == null ? "—" : `${e >= 0 ? "+" : ""}${e.toFixed(3)}`}
                </td>
                <td className="py-1 pr-2 text-right">{r.total_r == null ? "—" : (r.total_r as number).toFixed(1)}</td>
                <td className="py-1 text-right">{r.win_rate == null ? "—" : `${((r.win_rate as number) * 100).toFixed(0)}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
