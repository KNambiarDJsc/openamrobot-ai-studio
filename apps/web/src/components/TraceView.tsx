import type { Check, ReadinessEvaluation } from "@contracts";

import { fmtAge, fmtTime } from "@/lib/format";

import { FreshPill, StatusBadge } from "./StatusBadge";

const OUTCOME_ORDER: Record<string, number> = { error: 0, fail: 1, unknown: 2, pass: 3 };
const OUTCOME_ICON: Record<string, string> = { error: "✕", fail: "■", unknown: "?", pass: "✓" };

export function sortChecks(checks: Check[]): Check[] {
  return [...checks].sort((a, b) => OUTCOME_ORDER[a.outcome] - OUTCOME_ORDER[b.outcome]
    || Number(b.severity === "warning") - Number(a.severity === "warning") || a.id.localeCompare(b.id));
}

export function TraceView({ ev, compact = false }: { ev: ReadinessEvaluation; compact?: boolean }) {
  const checks = sortChecks(ev.checks);
  return (
    <div className="trace">
      <header className="trace-head">
        <StatusBadge status={ev.status} />
        <div>
          <div className="trace-summary">{ev.summary}</div>
          <div className="trace-meta mono">
            trace {ev.trace_id} · {ev.task} · evaluated {fmtTime(ev.evaluated_at)} · {ev.policy_version}
            {" · "}{ev.source_mode === "fixture" ? `fixture ${ev.fixture_id} (demo data)` : "live adapter"}
            {" · "}studio {ev.revisions.studio}
            {ev.revisions.adapter ? ` · adapter ${ev.revisions.adapter}` : ""}
          </div>
        </div>
      </header>
      <table className="checks">
        <thead>
          <tr><th>Outcome</th><th>Check</th><th>Observed</th>{!compact && <th>Source</th>}<th>Received</th><th>Freshness</th></tr>
        </thead>
        <tbody>
          {checks.map((c) => {
            const e = c.evidence[0];
            return (
              <tr key={c.id} className={`row-${c.outcome} sev-${c.severity}`}>
                <td><span className={`outcome o-${c.outcome}`}><span aria-hidden="true">{OUTCOME_ICON[c.outcome]}</span> {c.outcome}{c.severity === "warning" && c.outcome === "pass" ? " (warn)" : ""}</span></td>
                <td>
                  <div className="mono small">{c.id}</div>
                  {c.next_check && !compact && <div className="next-check">Next: {c.next_check}</div>}
                </td>
                <td>{c.summary}</td>
                {!compact && <td className="mono small">{e?.source}</td>}
                <td className="mono small">{fmtTime(e?.observed_at as string | null)}</td>
                <td><FreshPill result={e?.freshness.result} age={e ? `${fmtAge(e.freshness.age_s)} / ${e.freshness.max_age_s}s` : undefined} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="disclaimer">{ev.disclaimer}</p>
    </div>
  );
}
