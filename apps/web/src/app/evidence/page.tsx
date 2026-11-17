"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { TraceView } from "@/components/TraceView";
import { api, query, type EvaluationDetail, type EvaluationRow, type EventRow, type ToolCallRow } from "@/lib/api";
import { fmtTime, SUBSYSTEM_LABEL, toIso } from "@/lib/format";

type Tab = "evaluations" | "events" | "tool-calls";
type Filters = { task: string; status: string; subsystem: string; severity: string; since: string; until: string };
const EMPTY: Filters = { task: "", status: "", subsystem: "", severity: "", since: "", until: "" };

function Explorer() {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("tool_trace") ? "tool-calls" : "evaluations");
  const [f, setF] = useState<Filters>(EMPTY);
  const [rows, setRows] = useState<EvaluationRow[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [calls, setCalls] = useState<ToolCallRow[]>([]);
  const [toolTrace, setToolTrace] = useState(params.get("tool_trace") ?? "");
  const [detail, setDetail] = useState<EvaluationDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const open = useCallback(async (trace: string) => {
    try {
      setDetail(await api<EvaluationDetail>(`/evidence/evaluations/${encodeURIComponent(trace)}`));
      setErr(null);
    } catch (e: any) {
      setErr(`${e.code}: ${e.message}`);
    }
  }, []);

  const load = useCallback(async () => {
    const common = { since: toIso(f.since), until: toIso(f.until), severity: f.severity };
    try {
      if (tab === "evaluations") {
        const r = await api<{ items: EvaluationRow[] }>(`/evidence/evaluations${query({ ...common, task: f.task,
          status: f.status, subsystem: f.subsystem, limit: 200 })}`);
        setRows(r.items);
      } else if (tab === "events") {
        const r = await api<{ items: EventRow[] }>(`/evidence/events${query({ ...common, subsystem: f.subsystem, limit: 300 })}`);
        setEvents(r.items);
      } else {
        const r = await api<{ items: ToolCallRow[] }>(`/evidence/tool-calls${query({ trace_id: toolTrace, limit: 300 })}`);
        setCalls(r.items);
      }
      setErr(null);
    } catch (e: any) {
      setErr(`${e.code}: ${e.message}`);
    }
  }, [tab, f, toolTrace]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    const t = params.get("trace");
    if (t) open(t);
  }, [params, open]);

  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF((x) => ({ ...x, [k]: e.target.value }));

  return (
    <div className="page">
      <div className="page-head">
        <h1>Evidence Explorer</h1>
        <p className="muted">Recorded readiness evaluations with their snapshot, events and copilot tool-call traces.</p>
      </div>
      <div className="tabs" role="tablist">
        {(["evaluations", "events", "tool-calls"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}>{t.replace("-", " ")}</button>
        ))}
      </div>
      <form className="filters" onSubmit={(e) => { e.preventDefault(); load(); }} aria-label="Filters">
        {tab === "evaluations" && (<>
          <label>Task<select value={f.task} onChange={set("task")} name="task">
            <option value="">all</option><option value="overall">overall</option>
            <option value="upper_body">upper_body</option><option value="navigation">navigation</option></select></label>
          <label>Status<select value={f.status} onChange={set("status")} name="status">
            <option value="">all</option>{["READY", "BLOCKED", "UNKNOWN", "ERROR"].map((s) => <option key={s}>{s}</option>)}</select></label>
        </>)}
        {tab !== "tool-calls" && (<>
          <label>Subsystem<select value={f.subsystem} onChange={set("subsystem")} name="subsystem">
            <option value="">all</option>
            {(tab === "evaluations" ? ["ros_graph", "controllers", "joint_states", "navigation", "diagnostics"]
              : ["overall", "upper_body", "navigation", "controllers", "joint_states", "diagnostics", "ros_graph", "connection", "copilot", "demo"])
              .map((s) => <option key={s} value={s}>{SUBSYSTEM_LABEL[s] ?? s}</option>)}
          </select></label>
          <label>Min severity<select value={f.severity} onChange={set("severity")} name="severity">
            <option value="">all</option><option value="info">info</option><option value="warning">warning</option>
            <option value="error">error</option></select></label>
          <label>Since<input type="datetime-local" value={f.since} onChange={set("since")} /></label>
          <label>Until<input type="datetime-local" value={f.until} onChange={set("until")} /></label>
        </>)}
        {tab === "tool-calls" && (
          <label className="grow">Trace id<input value={toolTrace} onChange={(e) => setToolTrace(e.target.value)}
            placeholder="diag-2026-…" /></label>
        )}
        <button type="submit" className="btn">Apply</button>
        <button type="button" className="btn-ghost" onClick={() => { setF(EMPTY); setToolTrace(""); }}>Reset</button>
      </form>
      {err && <div className="banner banner-error" role="alert">{err}</div>}

      <div className={detail ? "split" : ""}>
        <section className="panel">
          {tab === "evaluations" && (
            <table className="table hover" data-testid="evaluations">
              <thead><tr><th>Status</th><th>Task</th><th className="col-wide">Summary</th><th>Recorded</th><th className="col-wide">Source</th><th>Trace</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.trace_id} onClick={() => open(r.trace_id)} className={detail?.trace_id === r.trace_id ? "selected" : ""}>
                    <td><StatusBadge status={r.status} size="sm" /></td><td className="small">{r.task}</td>
                    <td className="small col-wide">{r.summary}</td><td className="mono small">{fmtTime(r.recorded_at)}</td>
                    <td className="small col-wide">{r.source_mode === "fixture" ? `fixture ${r.fixture_id}` : "live"}</td>
                    <td className="mono small">{r.trace_id}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={6} className="muted">No evaluations match.</td></tr>}
              </tbody>
            </table>
          )}
          {tab === "events" && (
            <table className="table" data-testid="events">
              <thead><tr><th>At</th><th>Severity</th><th>Subsystem</th><th>Kind</th><th>Message</th><th>Trace</th></tr></thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}><td className="mono small">{fmtTime(e.at)}</td>
                    <td><span className={`sev sev-${e.severity}`}>{e.severity}</span></td><td className="small">{e.subsystem}</td>
                    <td className="small">{e.kind}</td><td className="small">{e.message}</td>
                    <td className="mono small">{e.trace_id && (e.kind === "status_change" || e.kind === "diagnostic")
                      ? <button className="link-btn" onClick={() => open(e.trace_id!)}>{e.trace_id}</button> : e.trace_id}</td></tr>
                ))}
                {!events.length && <tr><td colSpan={6} className="muted">No events match.</td></tr>}
              </tbody>
            </table>
          )}
          {tab === "tool-calls" && (
            <table className="table" data-testid="tool-calls">
              <thead><tr><th>Trace</th><th>#</th><th>Tool</th><th>Args</th><th>Outcome</th><th>Result</th><th>Started</th></tr></thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.id}><td className="mono small">{c.trace_id}</td><td>{c.seq}</td><td className="mono small">{c.tool}</td>
                    <td className="mono small">{JSON.stringify(c.args)}</td><td className={`small o-${c.outcome}`}>{c.outcome}</td>
                    <td className="small">{c.result_summary}</td><td className="mono small">{fmtTime(c.started_at)}</td></tr>
                ))}
                {!calls.length && <tr><td colSpan={7} className="muted">No tool calls match.</td></tr>}
              </tbody>
            </table>
          )}
        </section>
        {detail && (
          <section className="panel detail" data-testid="evaluation-detail">
            <div className="panel-head"><h2>Evaluation</h2><button className="btn-ghost" onClick={() => setDetail(null)}>Close</button></div>
            <TraceView ev={detail.body} compact />
            {detail.tool_calls.length > 0 && (
              <><h3>Tool calls</h3>
                <ul className="small">{detail.tool_calls.map((c) => <li key={c.id}><span className="mono">{c.tool}</span> {c.outcome}: {c.result_summary}</li>)}</ul></>
            )}
            <details><summary className="small">Recorded snapshot (JSON)</summary>
              <pre className="json">{JSON.stringify(detail.snapshot, null, 2)}</pre></details>
          </section>
        )}
      </div>
    </div>
  );
}

export default function EvidencePage() {
  return <Suspense fallback={<div className="page muted">Loading…</div>}><Explorer /></Suspense>;
}
