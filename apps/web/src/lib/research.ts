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
  kind: "backtest" | "optimize" | "validate" | "study" | "screen" | "ml";
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
  kind: "backtest" | "optimize" | "validate" | "holdout" | "study" | "screen" | "search" | "ml" | "costs";
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
  cost_profile?: { profile: string; status: string; promotion_profile: string };
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

/** One decision bar checked against a spec's rules (POST /api/strategy/explain). */
export interface Explain {
  spec_hash: string;
  decision_time: number;
  event_time: number;
  atr_pts: number | null;
  entries: { side: Side; passed: boolean; conditions: (Condition & { actual: Scalar | null; passed: boolean })[] }[];
  filters: { key: "hygiene" | "sessions" | "vol_regimes" | "hours_utc" | "weekdays" | "max_spread_rel"; value: unknown; actual: Scalar | null; passed: boolean }[];
  fires: boolean;
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

// ---------------------------------------------------------------- Phase 7: structure + explorer

export interface StructurePoint {
  time: number;
  price: number;
}

export interface StructureData {
  swings: { kind: "high" | "low"; time: number; price: number; known_at: number }[];
  levels: { price: number; touches: number; band: number; first_time: number | null; last_time: number | null; known_at: number }[];
  lines: {
    kind: "up" | "down";
    p1: StructurePoint;
    p2: StructurePoint;
    end: StructurePoint;
    known_at: number;
    touches: number;
    broken_at: number | null;
    channel_offset: number | null;
  }[];
  events: { kind: string; time: number; price: number }[];
  window_bars: number;
}

export interface Barriers {
  target_atr: number;
  stop_atr: number;
  horizon_bars: number;
}

export interface Pattern {
  pattern_id: string;
  slug: string;
  version: number;
  name: string;
  behaviour: string;
  description: string;
  definition: { side: Side; conditions: Condition[]; barriers: Barriers; hypothesis?: string };
  expected_direction: string;
  min_samples: Record<"A" | "B" | "C", number>;
  rule_version: string;
  created_by: string;
  registered_at: string;
  latest: Record<"A" | "B", (Record<string, unknown> & { run_id: string; created_at: string }) | null>;
}

export interface StudyStats {
  n: number;
  target_rate?: number | null;
  stop_rate?: number | null;
  time_rate?: number | null;
  mean_r_net?: number | null;
  median_r_net?: number | null;
  mean_r_gross?: number | null;
  win_rate_net?: number | null;
  mfe_r?: number | null;
  mae_r?: number | null;
  avg_minutes?: number | null;
  ambiguity_rate?: number | null;
}

export interface StudyBucket {
  n: number;
  scored: boolean;
  mean_r_net: number | null;
  mean_r_gross: number | null;
  target_rate: number | null;
  [key: string]: string | number | boolean | null;
}

export interface StudyRun {
  run_id: string;
  kind: "study";
  name: string;
  pattern_id: string | null;
  tier: "A" | "B";
  definition: { side: Side; conditions: Condition[]; barriers: Barriers };
  registered: boolean;
  exploratory: boolean;
  occurrences: number;
  bars_in_tier: number;
  scenarios: Record<Scenario, StudyStats>;
  gross: { bootstrap: Robustness["bootstrap_expectancy_ci"] };
  net: { bootstrap: Robustness["bootstrap_expectancy_ci"] };
  baseline: StudyStats & { sampled_every?: number };
  lift_vs_baseline: { target_rate: number | null; mean_r_gross: number | null; mean_r_net: number | null } | null;
  forward_returns_atr: Record<string, { n: number; mean_atr: number | null; hit_rate: number | null }>;
  by_year: StudyBucket[];
  by_session: StudyBucket[];
  by_vol_regime: StudyBucket[];
  sample: { min: number; n: number; sufficient: boolean; consequence: string | null };
  markers: { event_time: number[]; label: number[]; r_net: number[] };
}

export interface ScreenRow {
  pattern_id: string;
  name: string;
  behaviour: string;
  side: Side;
  n: number;
  sufficient: boolean;
  target_rate: number | null;
  baseline_target_rate: number | null;
  mean_r_gross: number | null;
  mean_r_net: number | null;
  mean_r_net_base: number | null;
  p_gross: number | null;
  p_net: number | null;
  q_gross?: number;
  q_net?: number;
  discovery_gross?: boolean;
  discovery_net?: boolean;
  stability_year: number | null;
  stability_session: number | null;
}

export interface ScreenRun {
  run_id: string;
  kind: "screen";
  name: string;
  tier: "A" | "B";
  fdr_q: number;
  rule_version: string;
  rows: ScreenRow[];
}

export interface Distribution {
  feature: string;
  by: string;
  rows: number;
  numeric: boolean;
  edges?: number[];
  categories?: string[];
  groups: {
    group: string;
    n: number;
    nulls?: number;
    mean?: number | null;
    p10?: number | null;
    p25?: number | null;
    p50?: number | null;
    p75?: number | null;
    p90?: number | null;
    hist?: number[];
    shares?: Record<string, number | null>;
  }[];
  spec: CatalogueFeature;
}

export interface DraftSuggestion {
  condition: Condition;
  why: string;
  group: string;
  selected: boolean;
}

export interface Draft {
  side: Side;
  suggestions: DraftSuggestion[];
  filters: { sessions?: string[] };
  note: string;
  event_time: number;
  available_at: number;
}

export const explore = {
  structure: (start: number, end: number) => call<StructureData>(`/api/structure?start=${start}&end=${end}`),
  distribution: (feature: string, by: string) =>
    call<Distribution>(`/api/explore/distribution?feature=${encodeURIComponent(feature)}&by=${by}`),
  behaviours: () =>
    call<{ groups: Record<string, string>; rule_version: string; min_samples: Record<string, number>; patterns: Pattern[]; screens: RunRow[] }>(
      "/api/behaviours",
    ),
  register: (body: { slug: string; name: string; behaviour?: string; side: Side; conditions: Condition[]; hypothesis: string; barriers: Barriers }) =>
    post<Pattern>("/api/behaviours", body),
  study: (body: { pattern_id?: string | null; name?: string; side?: Side; conditions?: Condition[]; barriers?: Barriers; tier: "A" | "B" }) =>
    post<{ job_id: string }>("/api/jobs/study", body),
  screen: (tier: "A" | "B") => post<{ job_id: string }>(`/api/jobs/screen?tier=${tier}`, {}),
  draft: (time: number, tf: string, side: Side) => post<Draft>("/api/strategy/draft-from-bar", { time, tf, side }),
};

// ---------------------------------------------------------------- Phase 8: research engine

export interface SearchBlock {
  label: string;
  side: Side;
  conditions: Condition[];
  pattern_id?: string | null;
  behaviour?: string;
}

export interface SearchSpaceDef {
  name: string;
  family: string;
  hypothesis?: string;
  blocks: SearchBlock[];
  sessions: (string[] | null)[];
  vol_regimes: (string[] | null)[];
  htf_align: boolean[];
  stop_atr: number[];
  target_atr: number[];
  time_exit_bars: number[];
  method: "grid" | "random" | "evolutionary";
  max_trials: number;
  max_minutes: number;
  min_trades_a: number;
  top_k: number;
  seed?: number;
}

export interface Hypothesis {
  search_id: string;
  spec_hash: string;
  seq: number;
  generation: number;
  label: string;
  spec: StrategySpec;
  status: "planned" | "passed_screen" | "rejected" | "not_selected" | "candidate";
  reasons: string[];
  metrics: {
    n?: number;
    expectancy_r?: number | null;
    profit_factor?: number | null;
    expectancy_before_costs_r?: number | null;
    B_expectancy_r?: number | null;
    B_n?: number | null;
    oos_expectancy_r?: number | null;
    deflated_excess?: number | null;
    verdict?: string;
    family_trials_after?: number;
  };
  validate_run: string | null;
  created_at: string;
  updated_at: string;
}

export interface SearchSummary {
  space_size?: number;
  registered: number;
  counts?: Record<string, number>;
  family_trials?: number;
  sr0_expected_max?: number | null;
  best?: { label: string; metrics: Hypothesis["metrics"]; status: string } | null;
  candidates?: number;
  note?: string;
}

export interface SearchRec {
  search_id: string;
  name: string;
  family: string;
  definition: SearchSpaceDef;
  mode: "auto" | "approve";
  status: "proposed" | "queued" | "running" | "paused" | "done" | "failed" | "cancelled";
  control: string;
  summary: SearchSummary;
  job_id: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  job: { job_id: string; status: string; progress: number; message: string } | null;
  resumable: boolean;
}

export interface CandidateRow {
  spec_hash: string;
  run_id: string;
  family: string;
  name: string | null;
  created_by: string | null;
  verdict: "candidate" | "pending" | "rejected" | null;
  failed: number | null;
  pending: number | null;
  expectancy_r: number | null;
  oos_expectancy_r: number | null;
  n: number | null;
  family_trials: number | null;
  validated_at: string;
}

export const pipeline = {
  space: () =>
    call<{ blocks: SearchBlock[]; sessions: string[]; vol_regimes: string[]; limits: Record<string, number> }>("/api/search/space"),
  list: () => call<SearchRec[]>("/api/searches"),
  get: (id: string) =>
    call<SearchRec & { hypotheses: Hypothesis[]; live: SearchSummary }>(`/api/searches/${encodeURIComponent(id)}`),
  create: (space: SearchSpaceDef, mode: "auto" | "approve") => post<SearchRec>("/api/searches", { space, mode }),
  approve: (id: string) => post<{ job_id: string }>(`/api/searches/${encodeURIComponent(id)}/approve`, {}),
  pause: (id: string) => post<{ ok: boolean }>(`/api/searches/${encodeURIComponent(id)}/pause`, {}),
  resume: (id: string) => post<{ job_id: string }>(`/api/searches/${encodeURIComponent(id)}/resume`, {}),
  candidates: () => call<CandidateRow[]>("/api/candidates"),
};

// ---------------------------------------------------------------- Phase 9: cost profiles

export interface CostProfileRow {
  profile: string;
  label: string;
  status: "validated" | "provisional" | "failed_validation" | "missing";
  cost_model_id: string | null;
  built_utc?: string;
  commission_round_turn_usd?: number;
  commission_confirmed?: boolean;
  spread_basis?: string;
  mean_spread_points_last_60_days?: { optimistic: number; base: number; pessimistic: number } | null;
  validation_passed?: boolean;
  tick_source_raw_version?: string | null;
}

export interface CostProfiles {
  dataset_id: string;
  active: string;
  promotion_profile: string;
  profiles: CostProfileRow[];
  raw_archives: { raw_version: string; server: string; account_label: string; tick_days: number }[];
}

export const costProfiles = {
  get: () => call<CostProfiles>("/api/costs/profiles"),
  setActive: (profile: string) => post<{ profile: string }>(`/api/costs/profiles/active?profile=${encodeURIComponent(profile)}`, {}),
  build: (body: { action: "provisional-raw" | "calibrate-raw"; commission_per_lot?: number; raw_ticks?: string }) =>
    post<{ job_id: string }>("/api/jobs/costs", body),
};

// ---------------------------------------------------------------- Phase 10: assistant + ML

export interface AssistantStatus {
  configured: boolean;
  provider: string | null;
  base_url_host: string | null;
  model: string;
  fast_model: string | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatReply {
  reply: string;
  proposal: { spec: StrategySpec; valid: boolean; spec_hash?: string; errors: { loc: string; msg: string }[] } | null;
  model: string;
  usage: { input_tokens: number | null; output_tokens: number | null } | null;
}

export interface MLSide {
  n: number;
  expectancy_r: number | null;
  profit_factor: number | null;
  max_dd_r: number | null;
  win_rate: number | null;
  total_r: number | null;
  bootstrap: { low?: number | null; high?: number | null };
}

export interface MLRun {
  run_id: string;
  kind: "ml";
  name: string;
  spec_hash: string;
  family: string;
  spec: StrategySpec;
  train: { tier: "A"; signals: number; positive_share: number; oof_auc: number | null; folds: number; embargo_days: number };
  threshold: { threshold: number; quantile?: number; table: { quantile: number; threshold: number; kept: number; expectancy_r: number }[] };
  importance: { feature: string; gain: number }[];
  test: { tier: "B"; signals: number; baseline: MLSide; filtered: MLSide; delta_r: number | null };
  verdict: "helps" | "not helping";
  reasons: string[];
  family_trials: number;
}

export const assistant = {
  status: () => call<AssistantStatus>("/api/assistant/status"),
  chat: (body: { question: string; history: ChatTurn[]; run_id?: string | null; spec?: StrategySpec | null; fast?: boolean }) =>
    post<ChatReply>("/api/assistant/chat", body),
};

export const ml = {
  run: (spec: StrategySpec) => post<{ job_id: string }>("/api/jobs/ml", { spec }),
  runs: () => call<RunRow[]>("/api/ml/runs"),
};

export const research = {
  catalogue: () => call<Catalogue>("/api/strategy/catalogue"),
  validate: (spec: StrategySpec) => post<{ ok: true; spec_hash: string; features_used: string[] }>("/api/strategy/validate", spec),
  preview: (spec: StrategySpec, limit = 2000) => post<Preview>("/api/strategy/preview", { spec, limit }),
  explain: (spec: StrategySpec, time: number) => post<Explain>("/api/strategy/explain", { spec, time }),
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
  if (kind === "study" || kind === "screen") return `/explorer?run=${runId}`;
  if (kind === "search") return `/pipeline?search=${runId}`;
  if (kind === "ml") return `/ml?run=${runId}`;
  if (kind === "costs") return `/costs`;
  if (kind === "optimize") return `/optimize?run=${runId}`;
  if (kind === "validate") return `/validate?run=${runId}`;
  return `/backtest?run=${runId}`;
}
