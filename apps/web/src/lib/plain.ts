// Plain-language layer for Simple mode (requirement 2026-09-22_simple-mode-ui.md):
// glossary, the answer-first verdict, and the wizard's choices → a real strategy spec.
// Every number still comes from the engine; this file only words and routes it.

import type { BacktestRun, Metrics, Side, StrategySpec } from "@/lib/research";

// ---------------------------------------------------------------- glossary

export const TERMS = {
  r: { name: "R", plain: "1 R = ek trade mein aap jitna risk karte ho. $100 risk kiya to 1 R = $100. +0.10 R matlab har trade pe average $10 kamai." },
  expectancy: { name: "Expectancy", plain: "Har trade ki average kamai (R mein), mehenge kharche ke saath. Sabse zaroori number." },
  trades: { name: "Trades", plain: "Kitni baar strategy ne trade liya. Kam se kam 1,000 (practice data) chahiye, tabhi result pe bharosa hota hai." },
  drawdown: { name: "Max drawdown", plain: "Account apne sabse ooncha point se kitna neeche gira. 15 R se zyada = sehna mushkil." },
  profit_factor: { name: "Profit factor", plain: "Total jeet ÷ total haar. 1.0 = barabar. Pass ke liye 1.15 ya zyada." },
  win_rate: { name: "Win rate", plain: "Kitne % trades faayde mein band hue. Akele yeh kaafi nahi — chhoti jeet aur badi haar ho to bhi nuksaan." },
  deflated: { name: "Deflated Sharpe", plain: "Luck test: itni koshishon (trials) ke baad bhi result luck se behtar hai ya nahi. 0 se upar chahiye." },
  trials: { name: "Family trials", plain: "Is idea ke kitne versions try hue. Jitni zyada koshish, pass hone ka bar utna ooncha." },
  tier: { name: "Tier A / B / C", plain: "Data ke 3 hisse: A = practice (2021–2024), B = check (2024–2025), C = final exam (band, sirf ek baar khulta)." },
  pessimistic: { name: "Pessimistic", plain: "Mehenga kharcha wala scenario (bura din). Pass/fail sirf isi se hota hai." },
  costs: { name: "Costs", plain: "Har trade ka kharcha: spread (buy-sell ka farak), slippage (kharab fill), commission (broker fee), swap (raat ka charge)." },
  atr: { name: "ATR", plain: "Gold ki ek aam 5-minute candle ka size. 1.5× = aam candle se dedh guna door." },
  sweep: { name: "Sweep", plain: "Price kisi level (jaise kal ka low) ke thoda paar gaya aur wapas aa gaya — jaise stop-loss pakad ke lauta ho." },
} as const;
export type TermKey = keyof typeof TERMS;

// ---------------------------------------------------------------- verdict

export type VerdictKind = "pass" | "weak" | "loss_costs" | "loss" | "few" | "empty";

export interface Verdict {
  kind: VerdictKind;
  tone: "good" | "warn" | "bad";
  title: string;
  why: string;
}

// Blueprint §15 lines, stated here only to word the answer; the engine's Validate
// checklist remains the judge.
export const PASS_EXPECTANCY = 0.1;
export const PASS_PF = 1.15;
export const MIN_TRADES_TO_JUDGE = 100;

export const TIER_PLAIN: Record<string, string> = {
  A: "Practice data (2021–2024)",
  B: "Check data (2024–2025)",
  AB: "Practice + check data (2021–2025)",
  C: "Final exam data",
};

const usd = (r: number) => `$${Math.abs(r * 100).toFixed(0)}`;

export function verdictOf(m: Metrics): Verdict {
  const e = m.expectancy_r;
  const before = m.expectancy_before_costs_r ?? null;
  if (!m.n || e == null) {
    return { kind: "empty", tone: "warn", title: "Is data mein ek bhi trade nahi bana", why: "Rules itne sakht hain ki koi candle unhe poora nahi karti. Filter dheela karo ya doosra session / disha chuno." };
  }
  if (m.n < MIN_TRADES_TO_JUDGE) {
    return {
      kind: "few",
      tone: "warn",
      title: "Trades bahut kam hain — abhi kuch keh nahi sakte",
      why: `Sirf ${m.n} trades bane. Itne kam trades ka result luck bhi ho sakta hai; bharose ke liye kam se kam ${MIN_TRADES_TO_JUDGE} chahiye (pass ke liye 1,000).`,
    };
  }
  if (e <= 0) {
    if (before != null && before > 0) {
      return {
        kind: "loss_costs",
        tone: "bad",
        title: "Abhi yeh strategy paisa nahi banati",
        why: `Har trade pe average ${usd(e)} ka nuksaan ($100 risk pe). Pattern kharche se pehle thoda kamata hai, par spread + commission ka kharcha usse zyada kha jaata hai.`,
      };
    }
    return {
      kind: "loss",
      tone: "bad",
      title: "Is pattern mein dum nahi dikha",
      why: `Har trade pe average ${usd(e)} ka nuksaan ($100 risk pe) — aur kharche se pehle bhi faayda nahi tha. Matlab pattern ke baad price koi khaas disha nahi pakadta.`,
    };
  }
  const pf = m.profit_factor ?? 0;
  if (e < PASS_EXPECTANCY || pf < PASS_PF) {
    return {
      kind: "weak",
      tone: "warn",
      title: "Thoda positive, par pass line se neeche",
      why: `Har trade pe average ${usd(e)} kamai ($100 risk pe). Pass ke liye kam se kam $${PASS_EXPECTANCY * 100} (+${PASS_EXPECTANCY} R) aur profit factor ${PASS_PF} chahiye — itna patla faayda thode se zyada kharche mein gayab ho sakta hai.`,
    };
  }
  return {
    kind: "pass",
    tone: "good",
    title: "Is data pe pass! Ab final check karo",
    why: `Har trade pe average ${usd(e)} kamai ($100 risk pe), mehenge kharche ke baad bhi. Ab dekhna hai ki naye data aur luck test mein bhi tikti hai ya nahi.`,
  };
}

export function totalCostR(m: Metrics): number | null {
  const c = m.costs_r;
  return c ? c.spread + c.slippage + c.commission + c.swap : null;
}

export const pessimistic = (run: BacktestRun) => run.results.pessimistic;

// ---------------------------------------------------------------- wizard choices

export interface Choice {
  id: string;
  title: string;
  desc: string;
  sentence: string;
}

export const PATTERNS: (Choice & { family: string; hypothesis: string; entries: StrategySpec["entries"]; fixedSessions?: string[] })[] = [
  {
    id: "sweep",
    title: "Kal ke high / low ka sweep",
    desc: "Price kal ke low ke neeche (ya high ke upar) jaaye aur usi candle mein wapas andar band ho",
    sentence: "price kal ke low ke neeche jaake wapas upar band ho (ya high ke upar jaake wapas neeche)",
    family: "prev-day-sweep",
    hypothesis: "Kal ke high/low ke paas stop-loss hote hain; sweep ke baad price wapas range mein lautta hai.",
    entries: [
      { side: "long", conditions: [{ feature: "pdl_sweep", op: "==", value: true }] },
      { side: "short", conditions: [{ feature: "pdh_sweep", op: "==", value: true }] },
    ],
  },
  {
    id: "reversal",
    title: "3-candle palatna (reversal)",
    desc: "Do girti candles ke baad ek strong upar wali candle, high ke paas band (ulta bhi)",
    sentence: "do girti candles ke baad ek strong upar wali candle bane (ya do chadhti ke baad strong girti)",
    family: "three-candle-reversal",
    hypothesis: "Do opposite candles ke baad ek strong close chhota palatna dikhata hai.",
    entries: [
      { side: "long", conditions: [{ feature: "dirs_3", op: "==", value: "DDU" }, { feature: "close_loc", op: ">", value: 0.7 }] },
      { side: "short", conditions: [{ feature: "dirs_3", op: "==", value: "UUD" }, { feature: "close_loc", op: "<", value: 0.3 }] },
    ],
  },
  {
    id: "momentum",
    title: "London khulte hi tezi",
    desc: "London ke pehle ghante mein, bade (1-ghante) trend ki disha mein tez push",
    sentence: "London ke pehle ghante mein bade trend ki disha mein tez push aaye",
    family: "london-momentum",
    hypothesis: "London ke shuru mein trend ki disha wale push aage chalte hain.",
    entries: [
      { side: "long", conditions: [{ feature: "min_since_london_open", op: "between", value: [0, 60] }, { feature: "ret5_atr", op: ">", value: 1.0 }, { feature: "h1_trend_atr", op: ">", value: 0 }] },
      { side: "short", conditions: [{ feature: "min_since_london_open", op: "between", value: [0, 60] }, { feature: "ret5_atr", op: "<", value: -1.0 }, { feature: "h1_trend_atr", op: "<", value: 0 }] },
    ],
    fixedSessions: ["london", "london_ny_overlap"],
  },
];

export const SESSIONS: (Choice & { value: string[] | null })[] = [
  { id: "asian", title: "Asian session", desc: "India mein subah se dopahar tak — aam taur pe shaant", sentence: "Asian session", value: ["asian"] },
  { id: "london", title: "London session", desc: "Dopahar se shaam tak — din ki pehli badi halchal", sentence: "London session", value: ["london", "london_ny_overlap"] },
  { id: "ny", title: "New York session", desc: "Shaam se raat tak — sabse zyada volume", sentence: "New York session", value: ["new_york", "london_ny_overlap"] },
  { id: "all", title: "Poora din", desc: "Koi time filter nahi — pata na ho to yahi chuno", sentence: "kisi bhi time", value: null },
];

export const SIDES: (Choice & { keep: Side[] })[] = [
  { id: "buy", title: "Sirf Buy (upar)", desc: "Sirf tab jab price upar jaane ki ummeed ho", sentence: "buy karo", keep: ["long"] },
  { id: "sell", title: "Sirf Sell (neeche)", desc: "Sirf tab jab price neeche jaane ki ummeed ho", sentence: "sell karo", keep: ["short"] },
  { id: "both", title: "Dono", desc: "Pattern jis taraf ishara kare, us taraf", sentence: "pattern ki disha mein trade lo", keep: ["long", "short"] },
];

export const RISKS: (Choice & { stop: number; target: number; bars: number })[] = [
  { id: "small", title: "Chhota: 1× stop, 1.5× target", desc: "Jaldi andar-bahar (2 ghante tak). Kharcha sabse zyada chubhega.", sentence: "nuksaan aam candle ke 1 guna pe kaato, faayda 1.5 guna pe lo", stop: 1, target: 1.5, bars: 24 },
  { id: "balanced", title: "Balanced: 1.5× stop, 3× target", desc: "1 ka risk, 2 ki ummeed (1:2). 4 ghante tak.", sentence: "nuksaan aam candle ke 1.5 guna pe kaato, faayda 3 guna pe lo", stop: 1.5, target: 3, bars: 48 },
  { id: "big", title: "Bada: 2× stop, 6× target", desc: "1 ka risk, 3 ki ummeed (1:3). Kam trades jeetenge par bade; kharcha kam chubhta hai.", sentence: "nuksaan aam candle ke 2 guna pe kaato, faayda 6 guna pe lo", stop: 2, target: 6, bars: 96 },
];

export interface WizardAnswers {
  pattern: string | null;
  session: string | null;
  side: string | null;
  risk: string | null;
  why: string;
}

export const byId = <T extends { id: string }>(xs: T[], id: string | null) => xs.find((x) => x.id === id) ?? null;

export function sentenceOf(a: WizardAnswers): string {
  const p = byId(PATTERNS, a.pattern);
  const s = byId(SESSIONS, a.session);
  const d = byId(SIDES, a.side);
  const r = byId(RISKS, a.risk);
  // The momentum idea already names its time (London's first hour).
  const when = p?.fixedSessions ? "" : s ? (s.id === "all" ? "bhi " : `${s.sentence} mein `) : "… ";
  const risk = r ? r.sentence.charAt(0).toUpperCase() + r.sentence.slice(1) : "…";
  return `Jab ${when}${p ? p.sentence : "…"}, tab ${d ? d.sentence : "…"}. ${risk}.`;
}

/** The wizard's answers as a real strategy-spec/1 (validated by the engine before it runs). */
export function specOf(a: WizardAnswers): StrategySpec | null {
  const p = byId(PATTERNS, a.pattern);
  const s = byId(SESSIONS, a.session);
  const d = byId(SIDES, a.side);
  const r = byId(RISKS, a.risk);
  if (!p || !d || !r || (!s && !p.fixedSessions)) return null;
  const sessions = p.fixedSessions ?? s?.value ?? null;
  const sideWord = d.id === "both" ? "" : d.id === "buy" ? " · buy" : " · sell";
  const sessionWord = p.fixedSessions ? "" : s && s.id !== "all" ? ` · ${s.title.replace(" session", "")}` : "";
  return {
    meta: {
      name: `${p.title}${sessionWord}${sideWord} · ${r.title.split(":")[0]}`,
      family: p.family,
      hypothesis: a.why.trim() || p.hypothesis,
      created_by: "owner",
    },
    entries: p.entries.filter((e) => d.keep.includes(e.side)).map((e) => ({ side: e.side, conditions: e.conditions.map((c) => ({ ...c })) })),
    filters: sessions ? { sessions } : {},
    exit: { stop_atr: r.stop, target_atr: r.target, time_exit_bars: r.bars, trail_atr: null, flat_before_weekend: true },
    sizing: { risk_pct: 1, initial_equity_usd: 10000 },
  };
}

/** Same idea, wider exits (1:3) — the usual first fix when costs eat the edge. */
export function widerExits(spec: StrategySpec): StrategySpec {
  const big = RISKS[2];
  return {
    ...spec,
    meta: { ...spec.meta, name: `${spec.meta.name.replace(/ · (Chhota|Balanced|Bada)$/, "")} · Bada`, created_by: "owner" },
    exit: { ...spec.exit, stop_atr: big.stop, target_atr: big.target, time_exit_bars: big.bars },
  };
}

export const CREATED_BY: Record<string, string> = {
  owner: "Aapne banaya",
  engine: "Engine ne dhoondha",
  assistant: "AI ne banaya",
};

// ---------------------------------------------------------------- trade replay words

/** Plain names of the features the Simple-mode ideas (and common chart ideas) use.
 *  Anything else falls back to the engine's catalogue name. */
export const FEATURE_PLAIN: Record<string, string> = {
  pdl_sweep: "Kal ke low ka sweep (neeche jaake wapas andar band)",
  pdh_sweep: "Kal ke high ka sweep (upar jaake wapas andar band)",
  dirs_3: "Pichhli 3 candles ki disha (U = upar, D = neeche)",
  close_loc: "Candle kahan band hui (0 = low pe, 1 = high pe)",
  min_since_london_open: "London khule kitne minute hue",
  ret5_atr: "Pichhli 5 candles ka push (× aam candle)",
  h1_trend_atr: "1-ghante ka trend (+ upar, − neeche)",
  rsi14: "RSI 14",
  bb_pctb: "Bollinger band mein jagah (0 = neeche wali band, 1 = upar wali)",
  bb_close_below_lower: "Close Bollinger ki neeche wali band ke neeche",
  bb_close_above_upper: "Close Bollinger ki upar wali band ke upar",
  ema_stack: "EMA 9/21/50/200 ki line-up (+1 upar, −1 neeche)",
  ema9_21_cross: "EMA 9 ne EMA 21 ko cross kiya (+1 upar, −1 neeche)",
  session: "Session",
  vol_regime: "Volatility (low / mid / high)",
  body_atr: "Candle body ka size (× aam candle)",
  range_atr: "Candle ka poora size (× aam candle)",
};

const OP_WORD: Record<string, string> = {
  ">": "se zyada",
  ">=": "ya zyada",
  "<": "se kam",
  "<=": "ya kam",
  "==": "=",
  "!=": "nahi =",
  between: "ke beech",
  in: "inmein se",
  not_in: "inmein se nahi",
};

export function valueWord(v: unknown): string {
  if (v === true) return "haan";
  if (v === false) return "nahi";
  if (v == null) return "—";
  if (Array.isArray(v)) return v.map(valueWord).join(" – ");
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) >= 10 ? 1 : 2);
  return String(v);
}

/** "Candle kahan band hui … 0.7 se zyada" */
export function ruleWord(feature: string, op: string, value: unknown): string {
  const name = FEATURE_PLAIN[feature] ?? feature;
  if (op === "==" && typeof value === "boolean") return value ? name : `${name} — nahi`;
  if (op === "==" || op === "!=") return `${name} ${OP_WORD[op]} ${valueWord(value)}`;
  return `${name}: ${valueWord(value)} ${OP_WORD[op] ?? op}`;
}

export const FILTER_PLAIN: Record<string, string> = {
  hygiene: "Safe time (rollover, weekend ya kharab spread nahi)",
  sessions: "Session",
  vol_regimes: "Volatility",
  hours_utc: "Ghanta (UTC)",
  weekdays: "Din",
  max_spread_rel: "Spread normal se zyada nahi",
};

export const EXIT_PLAIN: Record<string, { word: string; tone: "good" | "bad" | "muted" }> = {
  target: { word: "Target (TP) hit hua", tone: "good" },
  stop: { word: "Stop-loss (SL) hit hua", tone: "bad" },
  stop_gap: { word: "Price gap ke saath stop ke paar khula", tone: "bad" },
  time: { word: "Time khatam — trade band kiya", tone: "muted" },
  weekend: { word: "Weekend se pehle band kiya", tone: "muted" },
  trail: { word: "Trailing stop hit hua", tone: "muted" },
  end: { word: "Data khatam", tone: "muted" },
};

export const SESSION_PLAIN: Record<string, string> = {
  asian: "Asian",
  london: "London",
  new_york: "New York",
  london_ny_overlap: "London + NY",
  off: "Band / beech ka time",
};

export const REGIME_PLAIN: Record<string, string> = { low: "Shaant market", mid: "Normal market", high: "Tez market" };

/** A one-word status from a run row's stored summary (lists; the result page has the full verdict). */
export function quickVerdict(summary: Record<string, unknown>): { text: string; tone: "good" | "warn" | "bad" | "muted" } {
  const n = typeof summary.n === "number" ? summary.n : 0;
  const e = typeof summary.expectancy_r === "number" ? summary.expectancy_r : null;
  const pf = typeof summary.profit_factor === "number" ? summary.profit_factor : null;
  if (!n || e == null) return { text: "Koi trade nahi", tone: "muted" };
  if (n < MIN_TRADES_TO_JUDGE) return { text: "Trades bahut kam", tone: "warn" };
  if (e <= 0) return { text: "Paisa nahi banata", tone: "bad" };
  if (e < PASS_EXPECTANCY || (pf ?? 0) < PASS_PF) return { text: "Thoda +, pass nahi", tone: "warn" };
  return { text: "Pehla test pass — final check baaki", tone: "good" };
}

export const VALIDATE_PLAIN: Record<string, { text: string; tone: "good" | "warn" | "bad" }> = {
  candidate: { text: "Final check pass — final exam (sealed data) baaki", tone: "good" },
  pending: { text: "Final check adhoora", tone: "warn" },
  rejected: { text: "Final check mein fail", tone: "bad" },
};

/** A spec for the live preview while the wizard is half-filled: missing answers take the
 *  widest choice (both sides, all day, balanced exits). Preview only shows where the entry
 *  rules fire — it is not a backtest and adds no trial. */
export function previewSpecOf(a: WizardAnswers): StrategySpec | null {
  if (!a.pattern) return null;
  return specOf({ ...a, session: a.session ?? "all", side: a.side ?? "both", risk: a.risk ?? "balanced" });
}

/** The final-check (§15) items in plain words; the engine's checklist stays the judge. */
export function checkPlain(key: string): string {
  const tier = key.endsWith("_A") ? "practice data" : key.endsWith("_B") ? "check data" : "";
  if (key.startsWith("expectancy_")) return `Har trade ki average kamai +0.10 R ya zyada (${tier})`;
  if (key === "n_dev") return "Practice data mein kam se kam 1,000 trades";
  if (key === "n_val") return "Check data mein kam se kam 250 trades";
  if (key.startsWith("pf_")) return `Total jeet ÷ total haar 1.15 ya zyada (${tier})`;
  if (key.startsWith("dd_")) return `Sabse bada gira nuksaan 15 R / 20% se kam (${tier})`;
  if (key === "stability_year") return "Zyadatar saalon (70%+) mein faayda";
  if (key === "stability_session") return "Zyadatar sessions (70%+) mein faayda";
  if (key === "ambiguity") return "Ek hi minute mein SL + TP dono wale trades 5% se kam";
  if (key === "deflated_sharpe") return "Luck test: itni koshishon ke baad bhi luck se behtar";
  if (key === "holdout") return "Final exam data (band) pe bhi tike";
  if (key === "holdout_accesses") return "Final exam sirf ek baar khula";
  if (key === "cost_profile") return "Asli Raw account ke kharchon pe judge (Raw data aane tak pending)";
  return key;
}
