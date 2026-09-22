"use client";

import { useMemo } from "react";

import { EquityChart } from "@/components/research/equity-chart";
import { MIN_TRADES_TO_JUDGE, PASS_EXPECTANCY, REGIME_PLAIN, SESSION_PLAIN, totalCostR, type Verdict } from "@/lib/plain";
import { fmtR, type Bucket, type Metrics } from "@/lib/research";
import { cn } from "@/lib/utils";

// Visual result blocks for Simple mode: the money curve, where the strategy works and
// where it doesn't, and the plain reasons behind the verdict. Numbers are the engine's
// pessimistic-scenario breakdowns; this file only draws and words them.

const SIDE_PLAIN: Record<string, string> = { long: "Buy trades", short: "Sell trades" };
const DAY_PLAIN: Record<string, string> = { "1": "Somvaar", "2": "Mangal", "3": "Budh", "4": "Guru", "5": "Shukra", "6": "Shani", "7": "Ravi" };

/** Cumulative R over time, with the plain one-line story under it. */
export function EquityStory({ m }: { m: Metrics }) {
  // The chart keeps a minimum spacing per point, so thousands of trades would only show the
  // latest part. Thin to ≤ 300 points for display (each kept point is a real cumulative value,
  // the last trade always included); the numbers above come from all trades.
  const curves = useMemo(() => {
    const eq = m.equity;
    if (!eq?.time.length) return [];
    const step = Math.max(1, Math.ceil(eq.time.length / 300));
    const idx = eq.time.map((_, i) => i).filter((i) => i % step === 0 || i === eq.time.length - 1);
    return [{ name: "Kul kamai (R)", color: "#e0b04a", time: idx.map((i) => eq.time[i]), value: idx.map((i) => eq.cum_r[i]) }];
  }, [m.equity]);
  if (!curves.length) return null;
  const total = m.total_r ?? m.equity!.cum_r[m.equity!.cum_r.length - 1];
  return (
    <section aria-label="Paise ka safar" className="space-y-2 rounded-2xl border bg-card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-bold">Paise ka safar — har trade ke baad kul kamai</h2>
        <span className={cn("font-mono text-lg font-bold", total >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtR(total, 1)}</span>
      </div>
      <p className="text-sm text-muted-foreground">
        Line upar = paisa badha, neeche = ghata. {m.n.toLocaleString()} trades ke baad kul {fmtR(total, 1)} (≈ {total >= 0 ? "+" : "−"}$
        {Math.abs(total * 100).toFixed(0)} agar har trade mein $100 risk). Sabse bada gira hua nuksaan {m.max_dd_r?.toFixed(1) ?? "—"} R.
      </p>
      <EquityChart curves={curves} height={220} />
    </section>
  );
}

function label(kind: string, b: Bucket): string {
  const k = String(b[kind] ?? "");
  if (kind === "session") return SESSION_PLAIN[k] ?? k;
  if (kind === "vol_regime") return REGIME_PLAIN[k] ?? k;
  if (kind === "side") return SIDE_PLAIN[k] ?? k;
  if (kind === "weekday") return DAY_PLAIN[k] ?? k;
  return k;
}

function Bars({ title, kind, rows }: { title: string; kind: string; rows?: Bucket[] }) {
  const list = (rows ?? []).filter((b) => b.n > 0);
  if (!list.length) return null;
  const max = Math.max(0.05, ...list.map((b) => Math.abs(b.expectancy_r ?? 0)));
  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold">{title}</p>
      <ul className="space-y-1.5">
        {list.map((b) => {
          const e = b.expectancy_r ?? 0;
          const w = (Math.abs(e) / max) * 50;
          const few = b.n < 30;
          return (
            <li key={label(kind, b)} className="grid grid-cols-[88px_minmax(0,1fr)_64px] items-center gap-2 text-xs">
              <span className="truncate text-muted-foreground" title={label(kind, b)}>
                {label(kind, b)}
              </span>
              <span className="relative h-4 rounded bg-muted/40">
                <span className="absolute top-0 bottom-0 left-1/2 w-px bg-border" />
                <span
                  className={cn("absolute top-0.5 bottom-0.5 rounded-sm", e >= 0 ? "bg-emerald-500/80" : "bg-red-500/80", few && "opacity-40")}
                  style={e >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
                />
              </span>
              <span className={cn("text-right font-mono tabular-nums", e >= 0 ? "text-emerald-400" : "text-red-400", few && "opacity-60")} title={`${b.n} trades`}>
                {e >= 0 ? "+" : ""}
                {e.toFixed(2)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Same trades, grouped: year, session, market mood, side. */
export function WhereItWorks({ m }: { m: Metrics }) {
  return (
    <section aria-label="Kab chali kab nahi" className="space-y-3 rounded-2xl border bg-card p-5">
      <div>
        <h2 className="text-lg font-bold">Kab chali, kab nahi?</h2>
        <p className="text-sm text-muted-foreground">
          Har trade ki average kamai (R), alag-alag hisson mein. Hara = faayda, laal = nuksaan. Halka rang = 30 se kam trades (bharosa kam).
        </p>
      </div>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <Bars title="Saal ke hisaab se" kind="year" rows={m.by_year} />
        <Bars title="Session ke hisaab se" kind="session" rows={m.by_session} />
        <Bars title="Market ka mood" kind="vol_regime" rows={m.by_vol_regime} />
        <Bars title="Buy vs Sell" kind="side" rows={m.by_side} />
      </div>
    </section>
  );
}

/** Plain reasons behind the verdict, derived from the engine's breakdowns. */
export function reasonsOf(m: Metrics, v: Verdict): { tone: "good" | "bad" | "warn"; text: string }[] {
  const out: { tone: "good" | "bad" | "warn"; text: string }[] = [];
  const before = m.expectancy_before_costs_r;
  const cost = totalCostR(m);
  if (m.n < MIN_TRADES_TO_JUDGE) out.push({ tone: "warn", text: `Sirf ${m.n} trades — itne kam trades pe koi bhi result luck ho sakta hai.` });
  if (before != null && cost != null) {
    if (before > 0 && (m.expectancy_r ?? 0) <= 0)
      out.push({ tone: "bad", text: `Pattern kharche se pehle ${fmtR(before, 2)} kamata hai, par har trade ka kharcha ${cost.toFixed(2)} R hai — kharcha kamai se bada.` });
    else if (before <= 0) out.push({ tone: "bad", text: `Kharche se pehle bhi kamai nahi (${fmtR(before, 2)}) — pattern ke baad price koi khaas disha nahi pakadta.` });
    else if (cost > 0 && before > 0) out.push({ tone: before > 2 * cost ? "good" : "warn", text: `Kharcha kamai ka ${Math.round((cost / before) * 100)}% kha jaata hai (${cost.toFixed(2)} R har trade).` });
  }
  const years = (m.by_year ?? []).filter((b) => b.n >= 30);
  if (years.length >= 2) {
    const pos = years.filter((b) => (b.expectancy_r ?? 0) > 0);
    if (pos.length === 0) out.push({ tone: "bad", text: `Kisi bhi saal mein faayda nahi — ${years.length} mein se 0 saal positive.` });
    else if (pos.length < years.length)
      out.push({
        tone: pos.length === 1 ? "bad" : "warn",
        text: `${years.length} mein se sirf ${pos.length} saal faayde mein (${pos.map((b) => b.year).join(", ")}). Ek-do saal ki kamai asli edge nahi hoti.`,
      });
    else out.push({ tone: "good", text: `Har saal faayde mein (${years.length}/${years.length}) — yeh achha sign hai.` });
  }
  const sessions = (m.by_session ?? []).filter((b) => b.n >= 30).sort((a, b) => (b.expectancy_r ?? 0) - (a.expectancy_r ?? 0));
  if (sessions.length >= 2) {
    const best = sessions[0];
    const worst = sessions[sessions.length - 1];
    if ((best.expectancy_r ?? 0) > 0 && (worst.expectancy_r ?? 0) < 0)
      out.push({
        tone: "warn",
        text: `${SESSION_PLAIN[String(best.session)] ?? best.session} session sabse achha (${fmtR(best.expectancy_r, 2)}), ${SESSION_PLAIN[String(worst.session)] ?? worst.session} sabse bura (${fmtR(worst.expectancy_r, 2)}). Session filter ek naya test ho sakta hai — par woh ek nayi koshish ginegi.`,
      });
  }
  if (v.kind === "pass")
    out.push({ tone: "warn", text: `Yeh sirf practice data ka result hai. Jab tak final check (naya data + luck test) pass na ho, isse profitable mat maano.` });
  else if ((m.expectancy_r ?? 0) > 0 && (m.expectancy_r ?? 0) < PASS_EXPECTANCY)
    out.push({ tone: "warn", text: `Faayda +${PASS_EXPECTANCY} R ki pass line se neeche — thoda sa zyada kharcha isse mita dega.` });
  return out;
}

export function WhyPanel({ m, v }: { m: Metrics; v: Verdict }) {
  const rs = reasonsOf(m, v);
  if (!rs.length) return null;
  return (
    <section aria-label="Kyun" className="space-y-2 rounded-2xl border bg-card p-5">
      <h2 className="text-lg font-bold">{v.kind === "pass" ? "Kyun pass hui — aur kya dhyaan rakhein" : "Kyun kaam nahi kiya?"}</h2>
      <ul className="space-y-2">
        {rs.map((r, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm leading-relaxed">
            <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", r.tone === "good" && "bg-emerald-400", r.tone === "bad" && "bg-red-400", r.tone === "warn" && "bg-amber-400")} />
            {r.text}
          </li>
        ))}
      </ul>
    </section>
  );
}
