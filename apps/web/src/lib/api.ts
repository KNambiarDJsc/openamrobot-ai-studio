import type { AgentAnswer, ConnectionState, ReadinessEvaluation } from "@contracts";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws") + "/api/v1/ws/telemetry";

/** Structured error from the API ({error:{code,message}}) or a transport failure. Never swallowed. */
export class ApiError extends Error {
  constructor(public code: string, message: string, public status?: number, public details?: unknown) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch (e) {
    throw new ApiError("api_unreachable", `Studio API at ${API_URL} is unreachable`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error;
    throw new ApiError(err?.code ?? `http_${res.status}`, err?.message ?? res.statusText, res.status, err?.details);
  }
  return body as T;
}

export type SourceRow = {
  source: string;
  kind: string;
  received_at: string | null;
  stamp: string | null;
  freshness: { age_s: number | null; max_age_s: number; result: "fresh" | "stale" | "missing" } | null;
};

export type StatusResponse = {
  connection: ConnectionState;
  mode: "demo" | "live";
  subsystems_expected: string[];
  readiness: Record<string, { status: string; summary: string; trace_id: string; evaluated_at: string;
    blocking: string[]; unknown: string[]; warnings: string[] }>;
  snapshot: { snapshot_id: string; source_mode: string; fixture_id: string | null; captured_at: string;
    graph_available: boolean; graph_error: string | null; evaluated_at: string;
    revisions: { studio: string; adapter?: string | null; robot_stack?: string | null } };
  sources: SourceRow[];
};

export type Fixture = { id: string; title: string; description: string; label: string; evaluate_at: string;
  change_from_baseline: string; provenance: string; active: boolean };

export type EvaluationRow = { trace_id: string; task: string; status: string; evaluated_at: string; recorded_at: string;
  source_mode: string; fixture_id: string | null; studio_revision: string; summary: string; subsystems: string[];
  severity: string };

export type EventRow = { id: number; at: string; subsystem: string; severity: string; kind: string; message: string;
  trace_id: string | null; data: Record<string, unknown> };

export type ToolCallRow = { id: number; trace_id: string; seq: number; tool: string; args: Record<string, unknown>;
  started_at: string; finished_at: string; outcome: string; result_summary: string };

export type EvaluationDetail = EvaluationRow & { body: ReadinessEvaluation; snapshot: Record<string, unknown>;
  tool_calls: ToolCallRow[] };

export const getStatus = () => api<StatusResponse>("/status");
export const getReadiness = (task: string) => api<ReadinessEvaluation>(`/readiness?task=${encodeURIComponent(task)}`);
export const getFixtures = () => api<{ mode: string; fixtures: Fixture[] }>("/fixtures");
export const selectFixture = (fixture_id: string) =>
  api<{ fixture: Fixture; readiness: Record<string, string> }>("/fixtures/select", {
    method: "POST", body: JSON.stringify({ fixture_id }) });
export const askCopilot = (question: string) =>
  api<AgentAnswer>("/agent/query", { method: "POST", body: JSON.stringify({ question }) });
export const getConnection = () => api<ConnectionState>("/connection");

export function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}
