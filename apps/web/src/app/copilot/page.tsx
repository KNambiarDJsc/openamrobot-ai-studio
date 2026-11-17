"use client";
import Link from "next/link";
import { useRef, useState } from "react";

import type { AgentAnswer } from "@contracts";

import { StatusBadge } from "@/components/StatusBadge";
import { TraceView } from "@/components/TraceView";
import { askCopilot } from "@/lib/api";
import { fmtTime } from "@/lib/format";

const SUGGESTIONS = [
  "Is the simulated robot ready for a navigation task? Which subsystem is blocking it?",
  "Are the arm and lift controllers active?",
  "Is any telemetry stale?",
  "Any diagnostic warnings?",
  "Raise the lift to the top stop",
];

type Turn = { q: string; a?: AgentAnswer; error?: string };

export default function CopilotPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setQ("");
    setTurns((t) => [...t, { q: question }]);
    try {
      const a = await askCopilot(question);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (e: any) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: `${e.code}: ${e.message}` } : x)));
    } finally {
      setBusy(false);
      setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  };

  return (
    <div className="page copilot">
      <div className="page-head">
        <h1>AI Diagnostics Copilot</h1>
        <p className="muted">Answers come from deterministic readiness tools and cite the observed state, its receive
          time and a trace id. Requests to move or command the robot are refused before any tool runs.</p>
      </div>
      <div className="suggestions">
        {SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
      </div>
      <div className="conversation" aria-live="polite">
        {turns.length === 0 && <p className="muted">Ask about readiness, controllers, navigation status, diagnostics or stale telemetry.</p>}
        {turns.map((t, i) => (
          <div key={i} className="turn" data-testid="turn">
            <div className="q"><span className="q-label">You</span>{t.q}</div>
            {!t.a && !t.error && <div className="a pending">Evaluating…</div>}
            {t.error && <div className="a banner banner-error">{t.error}</div>}
            {t.a && (
              <div className="a" data-testid="answer">
                <div className="a-head">
                  {t.a.refused ? <span className="badge st-refused"><span aria-hidden="true">⊘</span>REFUSED</span>
                    : <StatusBadge status={t.a.status ?? "UNKNOWN"} />}
                  <span className="mono small muted">intent {t.a.intent} · {t.a.provider}</span>
                  <Link className="mono small link" href={`/evidence?tool_trace=${encodeURIComponent(t.a.trace_id)}`}
                    data-testid="answer-trace">{t.a.trace_id}</Link>
                </div>
                {t.a.model_text && (
                  <p className="model-text"><span className="tag">model phrasing, checked against the evidence</span>{t.a.model_text}</p>
                )}
                <pre className="answer-text">{t.a.text}</pre>
                <details>
                  <summary className="small">Tool calls ({t.a.tool_calls.length})</summary>
                  <table className="table">
                    <thead><tr><th>#</th><th>Tool</th><th>Args</th><th>Outcome</th><th>Result</th><th>At</th></tr></thead>
                    <tbody>{t.a.tool_calls.map((c) => (
                      <tr key={c.seq}><td>{c.seq}</td><td className="mono small">{c.tool}</td>
                        <td className="mono small">{JSON.stringify(c.args)}</td><td>{c.outcome}</td>
                        <td className="small">{c.result_summary}</td><td className="mono small">{fmtTime(c.started_at)}</td></tr>
                    ))}</tbody>
                  </table>
                </details>
                {t.a.evaluations.map((ev) => (
                  <details key={ev.trace_id}>
                    <summary className="small">Evidence trace {ev.trace_id} ({ev.checks.length} checks)</summary>
                    <TraceView ev={ev} compact />
                  </details>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Why is the robot not ready?"
          aria-label="Question" maxLength={2000} />
        <button type="submit" className="btn-primary" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </div>
  );
}
