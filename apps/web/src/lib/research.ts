// Research API client (Phases 4–6): strategy specs, runs, jobs, holdout.
// Every number shown in the UI comes from these endpoints — the engine's own results.

export type Side = "long" | "short";
export type Op = ">" | ">=" | "<" | "<=" | "==" | "!=" | "between" | "in" | "not_in";
export type Scalar = number | string | boolean;
export type Scenario = "optimistic" | "base" | "pessimistic";
export type Tier = "A" | "B" | "AB" | "C";

export interface Condition {
  feature: string;
  op: Op;
  value: Scalar | Scalar[];
}

export interface StrategySpec {
  spec_version?: "strategy-spec/1";
  meta: {
    name: string;
    family: string;
    hypothesis?: string;
    preregistration_id?: string | null;
    notes?: string;
    created_by?: "owner" | "engine" | "assistant";
  };
  entries: { side: Side; conditions: Condition[] }[];
  filters: {
    sessions?: string[] | null;
    vol_regimes?: string[] | null;
    hours_utc?: number[] | null;
    weekdays?: number[] | null;
    max_spread_rel?: number | null;
  };
  exit: {
    stop_atr: number;
    target_atr?: number | null;
    time_exit_bars?: number | null;
    trail_atr?: number | null;
    flat_before_weekend: boolean;
  };
  sizing: { mode?: "fixed_fractional"; risk_pct: number; initial_equity_usd: number };
}

export interface CatalogueFeature {
  name: string;
  group: string;
  unit: string;
  timing: string;
  description: string;
  numeric: boolean;
}

export interface Catalogue {
  spec_version: string;
  groups: Record<string, string>;
  features: CatalogueFeature[];
  ops: Op[];
  sessions: string[];
  vol_regimes: string[];
  always_on: string;
}

export interface Bucket {
  n: number;
  expectancy_r: number | null;
  total_r: number | null;
  win_rate: number | null;
  [key: string]: string | number | null;
}

export interface Metrics {
  n: number;
  wins?: number;
  win_rate?: number | null;
  expectancy_r: number | null;
  median_r?: number | null;
  std_r?: number | null;
  stderr_r?: number | null;
  total_r?: number | null;
  profit_factor: number | null;
  max_dd_r: number | null;
  max_dd_pct?: number | null;
  final_equity_usd?: number | null;
  ruined_at?: string | null;
  return_pct?: number | null;
  sharpe_per_trade?: number | null;
  avg_hold_minutes?: number | null;
  ambiguity_rate?: number | null;
  measured_spread_share?: number | null;
  expectancy_before_costs_r?: number | null;
  costs_r?: { spread: number; slippage: number; commission: number; swap: number };
  long_trades?: number;
  short_trades?: number;
  exit_reasons?: Record<string, number>;
  first_trade?: string;
  last_trade?: string;
  by_year?: Bucket[];
  by_month?: Bucket[];
  by_session?: Bucket[];
  by_weekday?: Bucket[];
  by_vol_regime?: Bucket[];
  by_side?: Bucket[];
  stability?: Record<"year" | "session", { score: number | null; buckets_scored: number; positive?: number }>;
  equity?: { time: number[]; cum_r: number[]; equity_usd: number[] };
  note?: string;
}

export interface Deflated {
  sharpe_per_trade: number;
  n_trials: number;
  sr0_expected_max: number;
  deflated_excess: number;
  probability: number | null;
  var_source: string;
}

export interface Robustness {
  bootstrap_expectancy_ci: { low: number | null; high: number | null; p_mean_le_0?: number; mean_block?: number; n_boot: number };
  monte_carlo_drawdown_r: { p50: number | null; p95: number | null; p99: number | null };
  cost_stress: {
    spread_points?: { extra: number; expectancy_r: number }[];
    breakeven_extra_spread_points?: number | null;
    breakeven_extra_commission_usd_per_lot?: number | null;
  };
}

export interface BacktestRun {
  run_id: string;
  kind: "backtest";
  created_utc: string;
  spec_hash: string;
  family: string;
  name: string;
  spec: StrategySpec;
  tier: Tier;
  tier_bounds_utc: [string, string | null];
  ambiguity_policy: string;
  lineage: { dataset_id: string; cost_model_id: string; feature_set_id: string; code_version: { git_commit: string | null; dirty: boolean } };
  signals: number;
  family_trials: number;
  deflated_sharpe: Deflated | null;
  results: Record<Scenario, Metrics>;
  robustness: Robustness;
}

export interface OptimizeRow {
  params: Record<string, number | string>;
  spec_hash: string | null;
  n?: number;
  expectancy_r?: number | null;
  profit_factor?: number | null;
  max_dd_r?: number | null;
  win_rate?: number | null;
  sharpe_per_trade?: number | null;
  total_r?: number | null;
  invalid?: string;
}

export interface OptimizeRun {
  run_id: string;
  kind: "optimize";
  spec_hash: string;
  family: string;
  name: string;
  spec: StrategySpec;
  optimize: {
    params: { path: string; values: (number | string)[] }[];
    variants: number;
    min_trades: number;
    table: OptimizeRow[];
    best: OptimizeRow | null;
    plateau: { ratio: number | null; neighbours: number; verdict: string } | null;
    best_deflated_sharpe?: Deflated | null;
    family_trials?: number;
  };
}

export interface ChecklistItem {
  key: string;
  label: string;
  value: unknown;
  threshold: string;
  passed: boolean | null;
  why: string;
}

export interface ValidateRun {
  run_id: string;
  kind: "validate";
  spec_hash: string;
  family: string;
  name: string;
  spec: StrategySpec;
  backtests: Record<"A" | "B" | "AB", string>;
  tiers: Record<"A" | "B" | "AB", Record<Scenario, Pick<Metrics, "n" | "expectancy_r" | "profit_factor" | "max_dd_r" | "win_rate">>>;
  walk_forward: {
    mode: string;
    train_months: number;
    test_months: number;
    folds: { train: [string, string]; test: [string, string]; chosen_params: Record<string, unknown> | null; train_expectancy_r: number | null; n: number; expectancy_r: number | null; total_r: number | null }[];
    positive_folds: number;
    scored_folds: number;
    oos: Pick<Metrics, "n" | "expectancy_r" | "profit_factor" | "max_dd_r" | "win_rate" | "total_r" | "equity">;
  };
  ambiguity_sensitivity: { pessimistic_policy_expectancy_r: number | null; optimistic_policy_expectancy_r: number | null; difference_r: number | null };
  robustness: Robustness;
  deflated_sharpe: Deflated | null;
  stability: Metrics["stability"];
  by_year: Bucket[];
  by_session: Bucket[];
  by_vol_regime: Bucket[];
  checklist: { verdict: "candidate" | "pending" | "rejected"; items: ChecklistItem[]; failed: number; pending: number; ready_to_unseal: boolean };
  holdout: { family: string; strategy_id: string; reason: string; accessed_at: string } | null;
  holdout_run: string | null;
  split: { a_start: string; b_start: string; c_start: string };
}

export type AnyRun = BacktestRun | OptimizeRun | ValidateRun;

export interface RunRow {
  run_id: string;
  kind: "backtest" | "optimize" | "validate";
  spec_hash: string;
  family: string;
  tier: string;
  created_at: string;
  summary: Record<string, unknown>;
}

export interface SpecRow {
  spec_hash: string;
  family: string;
  name: string;
  spec: StrategySpec;
  created_by: string;
  parent_hash: string | null;
  favourite: boolean;
  created_at: string;
  runs: number | null;
  last_run: string | null;
  family_trials: number | null;
}

export interface Job {
  job_id: string;
  kind: "backtest" | "optimize" | "validate" | "holdout";
  title: string;
  params: Record<string, unknown>;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  message: string;
  result?: { run_id: string } | null;
  error?: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Trade {
  scenario: Scenario;
  side: 1 | -1;
  decision_time: number;
  entry_time: number;
  exit_time: number;
  entry_price: number;
  exit_price: number;
  stop_initial: number;
  target: number | null;
  exit_reason: string;
  ambiguous: boolean;
  r_net: number;
  r_before_costs: number;
  mfe_r: number;
  mae_r: number;
  bars_held_m1: number;
  lots: number;
  pnl_usd: number;
  equity_usd: number;
  session: string | null;
  vol_regime: string | null;
}

export interface Overview {
  split: { a_start: string; b_start: string; c_start: string; frozen_utc: string };
  tiers: Record<"A" | "B" | "C", { start: string; end: string | null }>;
  lineage: { dataset_id: string; cost_model_id: string; feature_set_id: string };
  commission: { per_lot_round_turn_usd: number; confirmed: boolean; pessimistic_unconfirmed_usd: number };
  families: { family: string; trials: number; last_trial: string; holdout_used: boolean; holdout_strategy: string | null }[];
  thresholds: Record<string, number>;
}

export interface Preview {
  spec_hash: string;
  counts: Record<"A" | "B", number>;
  bars_per_tier: Record<"A" | "B", number>;
  event_time: number[];
  side: (1 | -1)[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details: { loc: string; msg: string }[] = [],
  ) {
    super(message);
  }
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    let details: { loc: string; msg: string }[] = [];
    try {
      const body = await res.json();
      const d = body.detail;
      if (typeof d === "string") msg = d;
      else if (d?.message) {
        msg = d.message;
        details = d.errors ?? [];
      } else if (Array.isArray(d)) {
        details = d.map((e: { loc: (string | number)[]; msg: string }) => ({ loc: e.loc.join("."), msg: e.msg }));
        msg = details.map((e) => `${e.loc}: ${e.msg}`).join("; ");
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg, details);
  }
  return res.json() as Promise<T>;
}

const post = <T>(url: string, body: unknown) =>
  call<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const research = {
  catalogue: () => call<Catalogue>("/api/strategy/catalogue"),
  validate: (spec: StrategySpec) => post<{ ok: true; spec_hash: string; features_used: string[] }>("/api/strategy/validate", spec),
  preview: (spec: StrategySpec) => post<Preview>("/api/strategy/preview", { spec }),
  save: (spec: StrategySpec, parent_hash?: string | null) => post<{ spec_hash: string }>("/api/strategies", { spec, parent_hash }),
  strategies: () => call<SpecRow[]>("/api/strategies"),
  strategy: (hash: string) =>
    call<SpecRow & { runs: RunRow[]; family_trials: number; holdout: Overview["families"][number] | null }>(
      `/api/strategies/${encodeURIComponent(hash)}`,
    ),
  favourite: (hash: string, on: boolean) => post<{ ok: true }>(`/api/strategies/${encodeURIComponent(hash)}/favourite?on=${on}`, {}),
  overview: () => call<Overview>("/api/research/overview"),
  runs: (spec_hash?: string) => call<RunRow[]>(`/api/runs${spec_hash ? `?spec_hash=${encodeURIComponent(spec_hash)}` : ""}`),
  run: <T extends AnyRun = AnyRun>(id: string) => call<T>(`/api/runs/${encodeURIComponent(id)}`),
  trades: (id: string, scenario: Scenario, offset = 0, limit = 200) =>
    call<{ total: number; offset: number; trades: Trade[] }>(
      `/api/runs/${encodeURIComponent(id)}/trades?scenario=${scenario}&offset=${offset}&limit=${limit}`,
    ),
  backtest: (spec: StrategySpec, tier: "A" | "B" | "AB") => post<{ job_id: string }>("/api/jobs/backtest", { spec, tier }),
  optimize: (spec: StrategySpec, params: { path: string; values: (number | string)[] }[]) =>
    post<{ job_id: string }>("/api/jobs/optimize", { spec, params }),
  validateJob: (spec: StrategySpec, params?: { path: string; values: (number | string)[] }[] | null) =>
    post<{ job_id: string }>("/api/jobs/validate", { spec, params: params?.length ? params : null }),
  unseal: (spec_hash: string, reason: string, confirm_family: string) =>
    post<{ job_id: string }>("/api/holdout/unseal", { spec_hash, reason, confirm_family }),
  jobs: () => call<Job[]>("/api/jobs?limit=20"),
  job: (id: string) => call<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  cancel: (id: string) => post<{ cancelled: boolean }>(`/api/jobs/${encodeURIComponent(id)}/cancel`, {}),
};

// ---------------------------------------------------------------- formatting helpers

export const fmtR = (x: number | null | undefined, d = 3) => (x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(d)} R`);
export const fmtPct = (x: number | null | undefined, d = 1) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
export const fmtNum = (x: number | null | undefined, d = 2) => (x == null ? "—" : x.toFixed(d));
export const fmtInt = (x: number | null | undefined) => (x == null ? "—" : x.toLocaleString());
export const fmtDate = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : "—");

/** Where a finished job's result lives in the UI. */
export function resultHref(kind: Job["kind"], runId: string) {
  if (kind === "optimize") return `/optimize?run=${runId}`;
  if (kind === "validate") return `/validate?run=${runId}`;
  return `/backtest?run=${runId}`;
}
