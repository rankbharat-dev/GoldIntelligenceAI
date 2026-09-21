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
