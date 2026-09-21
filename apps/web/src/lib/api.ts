export type Timeframe = "M1" | "M5" | "M15" | "H1";
export const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "H1"];

export interface CandlesResponse {
  dataset_id: string;
  timeframe: Timeframe;
  count: number;
  has_more: boolean;
  time: number[]; // UTC epoch seconds, bar open
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  incomplete: boolean[] | null;
}

export interface QualityReport {
  bars: number;
  passed: boolean;
  blocking: Record<string, number>;
  gaps: Record<string, { count: number; missing_minutes: number }>;
  daily_break_ny: { typical_start: string | null; typical_minutes: number | null; days_observed: number };
  largest_unexpected_gaps: { start_ny: string; minutes: number; category: string }[];
  short_intraday_missing_share: number;
  price_anomalies: { count: number; rule: string };
  flat_bars_share: number;
  spread_points: { p50: number; p90: number; p99: number; max: number; nonpositive: number; above_5x_p99: number };
  coverage: {
    first_ts_utc: string;
    last_ts_utc: string;
    research_window_utc: [string, string];
    thin_leading_weeks_excluded: string[];
    years: number;
  };
}

export interface DatasetSummary {
  dataset_id: string;
  symbol: string;
  broker: string;
  broker_server: string;
  price_side: string;
  built_utc: string;
  code_version: { git_commit: string | null; dirty: boolean };
  bars: Record<Timeframe, number>;
  clock_model: {
    days_measured: number;
    days_consistent_with_week: number;
    distinct_offsets_hours: number[];
    weeks_inferred_from_neighbours: number;
  };
  verification_vs_broker: Record<string, { ohlc_match_rate: number | null; compared: number }>;
  quality: QualityReport;
  symbol_spec: Record<string, unknown>;
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export function fetchSummary(dataset = "latest") {
  return getJson<DatasetSummary>(`/api/datasets/${encodeURIComponent(dataset)}/summary`);
}

export function fetchCandles(tf: Timeframe, before?: number, limit = 1500, dataset = "latest") {
  const q = new URLSearchParams({ tf, limit: String(limit), dataset });
  if (before !== undefined) q.set("before", String(before));
  return getJson<CandlesResponse>(`/api/candles?${q}`);
}

// ---------------------------------------------------------------- costs (Phase 2)

export type CostStat = "p25" | "p50" | "p90" | "p99" | "mean";
export type VolBucket = "all" | "low" | "mid" | "high";
export type CostWindow = "full" | "current";
export type CostBasis = "abs" | "ratio";
export type ScenarioName = "optimistic" | "base" | "pessimistic";

export interface ModelScore {
  n: number;
  mean_measured: number;
  mean_p50: number;
  mae_p50: number;
  median_ae_p50: number;
  coverage_p90: number;
  coverage_p99: number;
  relative_bias_p50: number;
}

type ScenarioMeans = Record<ScenarioName, number>;

export interface CostModelSummary {
  cost_model_id: string;
  model_version: string;
  dataset_id: string;
  broker: string;
  broker_server: string;
  built_utc: string;
  code_version: { git_commit: string | null; dirty: boolean };
  config_hash: string;
  point: number;
  contract_size: number;
  tick_window: { tick_days: number; first_day: string; last_day: string; ticks: number };
  vol_tercile_edges: { low_below: number; high_from: number };
  summary: {
    bars: number;
    measured_bars: number;
    measured_share: number;
    level_imputed_bars: number;
    abnormal_spread_bars: number;
    rollover_window_bars: number;
    mean_spread_points: {
      research_window: ScenarioMeans;
      last_60_days: ScenarioMeans;
      by_year: (ScenarioMeans & { year: number; bars: number })[];
    };
  };
  validation: {
    passed: boolean;
    chosen_model: string;
    calibration_days_before: string;
    holdout_minutes: number;
    acceptance: { max_abs_relative_bias_p50: number; min_coverage_p90: number };
    models: { level_x_ratio: ModelScore; abs_cells: ModelScore };
    abs_cells_on_pre_tick_history: { n: number; share_p50_below_quoted_minimum: number; median_p50_over_level: number };
  };
  execution: {
    scenarios: Record<
      ScenarioName,
      {
        market: { fixed_points: number; atr_frac: number };
        stop: { fixed_points: number; atr_frac: number };
        window_multiplier: number;
        use_unconfirmed_commission: boolean;
      }
    >;
    commission: { per_lot_round_turn_usd: number; confirmed: boolean; unconfirmed_pessimistic_usd: number };
    swap: {
      long_usd_per_lot_night: number;
      short_usd_per_lot_night: number;
      triple_day_mt5: number;
      rollover: string;
    };
    slippage_status: string;
  };
}

export interface CostHeatmap {
  stat: CostStat;
  vol: VolBucket;
  window: CostWindow;
  basis: CostBasis;
  unit: string;
  days: number[]; // ISO weekday, 1 = Monday
  hours: number[]; // UTC
  values: (number | null)[][]; // [day][hour]
  minutes: (number | null)[][];
}

export interface CostLevels {
  time: number[]; // UTC epoch seconds, day start
  level_median: number[];
  measured_mean: (number | null)[];
}

export function fetchCostModel(dataset = "latest") {
  return getJson<CostModelSummary>(`/api/costs/${encodeURIComponent(dataset)}`);
}

export function fetchCostHeatmap(
  p: { stat: CostStat; vol: VolBucket; window: CostWindow; basis: CostBasis },
  dataset = "latest",
) {
  const q = new URLSearchParams(p);
  return getJson<CostHeatmap>(`/api/costs/${encodeURIComponent(dataset)}/heatmap?${q}`);
}

export function fetchCostLevels(dataset = "latest") {
  return getJson<CostLevels>(`/api/costs/${encodeURIComponent(dataset)}/levels`);
}
