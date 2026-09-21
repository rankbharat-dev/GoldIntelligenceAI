// CEO Work Lab API client. Every state shown on the page comes from the mission store
// (/api/ceo/*); every number inside an output carries the run / job id that produced it.

import { ApiError } from "@/lib/research";

export type AgentKey = "director" | "data_scientist" | "pattern_analyst" | "strategy_architect" | "validator";
export type MissionStatus = "draft" | "awaiting_approval" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type TaskState =
  | "pending"
  | "waiting_deps"
  | "waiting_ceo"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Source {
  run_id?: string | null;
  job_id?: string | null;
  dataset_id?: string | null;
  query?: string | null;
}

export interface Finding {
  text: string;
  metrics: Record<string, number | string | null>;
  source: Source | null;
}

export interface Artifact {
  kind: "run" | "job" | "spec" | "search" | "pattern" | "note";
  ref: string;
  title: string;
}

export interface TaskOutput {
  summary: string;
  findings: Finding[];
  artifacts: Artifact[];
  limitations: string[];
  next_steps: string[];
}

export interface Task {
  task_id: string;
  mission_id: string;
  seq: number;
  agent: Exclude<AgentKey, "director">;
  title: string;
  instructions: string;
  depends_on: string[];
  needs_approval: boolean;
  approved: boolean;
  revision_of: string | null;
  state: TaskState;
  attempt: number;
  max_attempts: number;
  output: TaskOutput | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CeoEvent {
  event_id: number;
  mission_id: string;
  task_id: string | null;
  actor: string;
  kind: string;
  message: string;
  created_at: string;
}

export interface Progress {
  total: number;
  done: number;
  completed: number;
  running: number;
  failed: number;
  waiting_ceo: number;
}

export interface Report {
  headline: string;
  summary: string;
  verdict: "promising" | "inconclusive" | "rejected" | "blocked";
  findings: Finding[];
  strategies: string[];
  recommendations: string[];
  limitations: string[];
}

export interface MissionRow {
  mission_id: string;
  objective: string;
  status: MissionStatus;
  require_plan_approval: boolean;
  plan_note: string;
  created_at: string;
  finished_at: string | null;
  progress: Progress;
  agents: string[];
  has_report: boolean;
}

export interface CeoRun {
  run_id: string;
  mission_id: string;
  status: "requested" | "running" | "done" | "failed" | "cancelled";
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  usage: Record<string, number | boolean> | null;
}

export interface Usage {
  tasks: number;
  attempts: number;
  engine_runs_cited: number;
  jobs_cited: number;
  strategies: number;
  minutes: number | null;
  bridge_runs: number;
  bridge_runs_measured: number;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  turns?: number;
}

export interface BridgeStatus {
  alive: boolean;
  seen: string | null;
  info: { cli?: string | null; cli_version?: string | null; busy?: string | null };
  runs: CeoRun[];
}

export interface Mission extends Omit<MissionRow, "agents" | "has_report"> {
  constraints: Record<string, unknown>;
  runs: CeoRun[];
  usage: Usage;
  limits: { max_tasks: number; max_attempts: number; max_revisions: number; deadline_hours: number };
  report: Report | null;
  started_at: string | null;
  tasks: Task[];
  events: CeoEvent[];
}

export interface AgentCard {
  agent: AgentKey;
  name: string;
  role: string;
  status: "working" | "waiting" | "idle";
  current_task: { task_id: string; mission_id: string; title: string; started_at: string } | null;
  completed: number;
  failed: number;
  last_error: string | null;
  last_activity: CeoEvent | null;
}

export interface CeoOverview {
  missions: Record<MissionStatus, number>;
  tasks: Record<TaskState, number>;
  agents: AgentCard[];
  recent_events: CeoEvent[];
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const d = (await res.json()).detail;
      if (typeof d === "string") msg = d;
      else if (d?.message) msg = `${d.message}: ${(d.errors ?? []).map((e: { msg: string }) => e.msg).join("; ")}`;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

const post = <T>(url: string, body: unknown = {}) =>
  call<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const m = (id: string) => `/api/ceo/missions/${encodeURIComponent(id)}`;

export const ceo = {
  overview: () => call<CeoOverview>("/api/ceo/overview"),
  missions: () => call<MissionRow[]>("/api/ceo/missions"),
  mission: (id: string) => call<Mission>(m(id)),
  create: (body: { objective: string; require_plan_approval: boolean; limits?: Record<string, number> }) =>
    post<Mission>("/api/ceo/missions", body),
  approve: (id: string) => post<Mission>(`${m(id)}/approve`),
  pause: (id: string) => post<Mission>(`${m(id)}/pause`),
  resume: (id: string) => post<Mission>(`${m(id)}/resume`),
  cancel: (id: string) => post<Mission>(`${m(id)}/cancel`),
  approveTask: (taskId: string) => post<Task>(`/api/ceo/tasks/${encodeURIComponent(taskId)}/approve`),
  sendBack: (id: string, feedback: string) => post<Mission>(`${m(id)}/send-back`, { feedback }),
  editTask: (taskId: string, body: { title?: string; instructions?: string }) =>
    post<Task>(`/api/ceo/tasks/${encodeURIComponent(taskId)}/edit`, body),
  dropTask: (taskId: string) => post<Task>(`/api/ceo/tasks/${encodeURIComponent(taskId)}/drop`),
  messages: (id: string) => call<CeoEvent[]>(`${m(id)}/messages`),
  say: (id: string, text: string) => post<{ ok: true }>(`${m(id)}/messages`, { text, actor: "ceo" }),
  run: (id: string) => post<{ run: CeoRun; bridge: BridgeStatus }>(`${m(id)}/run`),
  bridge: () => call<BridgeStatus>("/api/ceo/bridge"),
  streamUrl: (id: string) => `${m(id)}/stream`,
};

export const EDITABLE: TaskState[] = ["pending", "waiting_deps", "waiting_ceo", "queued"];

export const ACTIVE_MISSION: MissionStatus[] = ["draft", "awaiting_approval", "running", "paused"];

/** Where a cited run opens in the app (run ids start with their kind). */
export function runHref(runId: string) {
  const k = runId.slice(0, 2);
  if (k === "st" || k === "sc") return `/explorer?run=${runId}`;
  if (k === "va") return `/validate?run=${runId}`;
  if (k === "op") return `/optimize?run=${runId}`;
  if (k === "ml") return `/ml?run=${runId}`;
  return `/backtest?run=${runId}`;
}
