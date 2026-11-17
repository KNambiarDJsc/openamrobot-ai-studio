"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LineChart } from "@/components/LineChart";
import { useStudioStatus } from "@/components/Shell";
import { FreshPill, StatusBadge } from "@/components/StatusBadge";
import { api, getFixtures, selectFixture, type Fixture } from "@/lib/api";
import { fmtAge, fmtTime, SUBSYSTEM_LABEL } from "@/lib/format";
import { series, useTelemetry } from "@/lib/telemetry";

type Obs = { source: string; kind: string; received_at: string; stamp: string | null; value: any;
  freshness: { age_s: number | null; max_age_s: number; result: string } | null };
type SnapshotView = { observations: Obs[]; graph_available: boolean; graph_error: string | null };

// Categorical slots 1-2 of the validated dark palette (blue, orange); the lift chart is a single series.
const SERIES_COLORS = { left: "#3987e5", right: "#d95926", lift: "#3987e5" };

function FixtureSwitcher({ onChange }: { onChange: () => void }) {
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => getFixtures().then((r) => setFixtures(r.fixtures)).catch((e) => setErr(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);
  if (!fixtures.length) return null;
  const active = fixtures.find((f) => f.active);
  return (
    <section className="panel fixture-panel" aria-label="Demo fixtures">
      <div className="panel-head">
        <h2>Demo fixture</h2>
        <span className="demo-flag">DEMO DATA · not a live robot</span>
      </div>
      <div className="fixture-tabs" role="tablist">
        {fixtures.map((f) => (
          <button key={f.id} role="tab" aria-selected={f.active} disabled={busy} data-fixture={f.id}
            className={`fixture-tab ${f.active ? "active" : ""}`}
            onClick={async () => {
              setBusy(true);
              try {
                await selectFixture(f.id);
                await load();
                onChange();
              } catch (e: any) {
                setErr(e.message);
              } finally {
                setBusy(false);
              }
            }}>
            {f.title}
          </button>
        ))}
      </div>
      {active && (
        <div className="fixture-desc">
          <p><strong>{active.title}.</strong> {active.description}</p>
          <p className="muted small">Change from baseline: {active.change_from_baseline}. Evaluated at the fixture clock
            {" "}{fmtTime(active.evaluate_at)}.</p>
          <details><summary className="small">Provenance</summary><p className="small muted">{active.provenance}</p></details>
        </div>
      )}
      {err && <div className="banner banner-error">{err}</div>}
    </section>
  );
}

function ReadinessCard({ task, r }: { task: string; r?: { status: string; summary: string; trace_id: string;
  blocking: string[]; unknown: string[]; warnings: string[] } }) {
  return (
    <article className={`card readiness-card`} data-testid={`readiness-${task}`}>
      <div className="card-head">
        <h3>{SUBSYSTEM_LABEL[task] ?? task}</h3>
        <StatusBadge status={r?.status} />
      </div>
      <p className="card-summary">{r?.summary ?? "No evaluation yet."}</p>
      {r && (
        <div className="card-foot">
          <span className="small muted">{r.blocking.length} blocking · {r.unknown.length} unknown · {r.warnings.length} warnings</span>
          <Link className="mono small link" href={`/evidence?trace=${encodeURIComponent(r.trace_id)}`}>{r.trace_id}</Link>
        </div>
      )}
    </article>
  );
}

export default function Overview() {
  const { status, refresh } = useStudioStatus();
  const [snap, setSnap] = useState<SnapshotView | null>(null);
  const tel = useTelemetry();

  const loadSnap = useCallback(() => api<SnapshotView>("/snapshot").then(setSnap).catch(() => setSnap(null)), []);
  useEffect(() => {
    loadSnap();
    const t = setInterval(loadSnap, 2000);
    return () => clearInterval(t);
  }, [loadSnap]);

  const obs = snap?.observations ?? [];
  const ctl = obs.find((o) => o.kind === "controllers");
  const js = obs.find((o) => o.kind === "joint_state");
  const nav = obs.find((o) => o.kind === "navigation_status");
  const diags = obs.filter((o) => o.kind === "diagnostics");
  const graph = obs.find((o) => o.kind === "graph");
  const lifecycle = obs.filter((o) => o.kind === "lifecycle");
  const tasks = ["overall", ...(status?.subsystems_expected ?? [])];
  const frames = tel.frames;
  const times = frames.map((f) => fmtTime(f.t) + (f.replay ? " (replay)" : ""));
  const replay = frames.some((f) => f.replay);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Robot Overview</h1>
        <p className="muted">Readiness from observed ROS state. Every value below comes from the Studio API.</p>
      </div>
      {status?.mode === "demo" && <FixtureSwitcher onChange={() => { refresh(); loadSnap(); tel.reset(); }} />}

      <section className="grid-3">
        {tasks.map((t) => <ReadinessCard key={t} task={t} r={status?.readiness?.[t]} />)}
      </section>

      <section className="grid-subsystems" aria-label="Subsystems">
        <article className="card">
          <div className="card-head"><h3>ROS graph</h3>
            <FreshPill result={snap ? (snap.graph_available ? graph?.freshness?.result : "missing") : null} /></div>
          {snap && !snap.graph_available ? <p className="err-text">{snap.graph_error}</p>
            : <p className="big-num">{graph?.value?.nodes?.length ?? "—"}<span className="unit"> nodes</span></p>}
        </article>
        <article className="card">
          <div className="card-head"><h3>Controllers</h3><FreshPill result={ctl?.freshness?.result} age={fmtAge(ctl?.freshness?.age_s)} /></div>
          {ctl?.value?.controllers ? (
            <ul className="kv-list">
              {ctl.value.controllers.map((c: any) => (
                <li key={c.name}><span className="mono small">{c.name}</span>
                  <span className={`ctl ctl-${c.state}`}>{c.state === "active" ? "●" : "■"} {c.state}</span></li>
              ))}
            </ul>
          ) : <p className="muted">{ctl?.value?.error ?? (ctl?.value?.available === false ? "controller_manager not running" : "not observed")}</p>}
        </article>
        <article className="card">
          <div className="card-head"><h3>Joint states</h3><FreshPill result={js?.freshness?.result} age={fmtAge(js?.freshness?.age_s)} /></div>
          {js ? (<>
            <p className="big-num">{js.value.name.length}<span className="unit"> joints</span></p>
            <p className="small muted">stamp {fmtTime(js.stamp)} · received {fmtTime(js.received_at)}</p>
          </>) : <p className="muted">/joint_states not observed</p>}
        </article>
        <article className="card">
          <div className="card-head"><h3>Navigation</h3><FreshPill result={nav?.freshness?.result} age={fmtAge(nav?.freshness?.age_s)} /></div>
          {nav ? (<>
            <p className="small">readiness <strong>{nav.value.navigation_readiness === 1 ? "READY" : "NOT_READY"}</strong> · health code {nav.value.health}</p>
            <p className="small muted">{lifecycle.filter((l) => l.value.state_id === 3).length}/{lifecycle.length} Nav2 lifecycle nodes active</p>
          </>) : <p className="muted">/navigation/status not observed</p>}
        </article>
        <article className="card">
          <div className="card-head"><h3>Diagnostics</h3></div>
          {diags.length ? (
            <ul className="kv-list">
              {diags.map((d) => (
                <li key={d.value.name}><span className="small">{d.value.name}</span>
                  <span className={`lvl lvl-${d.value.level}`}>{["OK", "WARN", "ERROR", "STALE"][d.value.level] ?? d.value.level}</span></li>
              ))}
            </ul>
          ) : <p className="muted">no /diagnostics entries</p>}
        </article>
      </section>

      <section className="grid-2">
        <div className="panel">
          <LineChart title="Arm joint 2 position" unit="rad" height={190}
            emptyText={tel.state === "open" ? "Waiting for /joint_states frames…" : "Telemetry socket not connected"}
            series={[
              { key: "l", label: "left j2", color: SERIES_COLORS.left, points: series(frames, "openarm_left_joint2").map((p) => p.v), times },
              { key: "r", label: "right j2", color: SERIES_COLORS.right, points: series(frames, "openarm_right_joint2").map((p) => p.v), times },
            ]}
            caption={replay ? "Fixture replay (synthetic series), not live data." : "Live /joint_states via the ROS adapter."} />
        </div>
        <div className="panel">
          <LineChart title="lift_joint position" unit="m" height={190}
            emptyText={tel.state === "open" ? "Waiting for /joint_states frames…" : "Telemetry socket not connected"}
            series={[{ key: "lift", label: "lift_joint", color: SERIES_COLORS.lift, points: series(frames, "lift_joint").map((p) => p.v), times }]}
            caption={`WebSocket ${tel.state} · ${frames.length} frames buffered (max 300)`} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Source freshness</h2>
          <span className="small muted">judged on adapter receive time; header stamps shown as published (sim time in Gazebo)</span></div>
        <table className="table">
          <thead><tr><th>Source</th><th>Kind</th><th>Received</th><th>Header stamp</th><th>Freshness</th></tr></thead>
          <tbody>
            {(status?.sources ?? []).map((s, i) => (
              <tr key={`${s.source}-${i}`}>
                <td className="mono small">{s.source}</td><td className="small">{s.kind}</td>
                <td className="mono small">{fmtTime(s.received_at)}</td><td className="mono small">{fmtTime(s.stamp)}</td>
                <td><FreshPill result={s.freshness?.result} age={s.freshness ? `${fmtAge(s.freshness.age_s)} / ${s.freshness.max_age_s}s` : undefined} /></td>
              </tr>
            ))}
            {status && !status.sources.length && <tr><td colSpan={5} className="muted">No sources observed.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Readiness timeline</h2><span className="small muted">overall, one mark per evaluation</span></div>
        <div className="timeline" aria-label="Readiness timeline">
          {tel.readiness.length ? tel.readiness.slice(-120).map((r, i) => (
            <span key={i} className={`tl tl-${r.status}`} title={`${fmtTime(r.at)} ${r.status}: ${r.summary}`} />
          )) : <span className="muted small">No evaluations streamed yet.</span>}
        </div>
      </section>
    </div>
  );
}
