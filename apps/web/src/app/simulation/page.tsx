"use client";
import { useCallback, useEffect, useState } from "react";

import { FreshPill } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { fmtAge, fmtNum, fmtTime, liftFraction } from "@/lib/format";

type Obs = { source: string; received_at: string; stamp: string | null; value: any;
  freshness: { age_s: number | null; max_age_s: number; result: string } | null };
type Sim = { source_mode: string; fixture_id: string | null; graph_available: boolean; evaluated_at: string;
  joint_state: Obs | null; tf: Obs | null; controllers: Obs | null; representation: string };


function LiftSchematic({ lift }: { lift: number | null }) {
  const f = liftFraction(lift);
  const colTop = 40, colBottom = 260, carH = 26;
  const y = f === null ? null : colBottom - carH - f * (colBottom - colTop - carH);
  return (
    <svg viewBox="0 0 220 300" className="schematic" role="img"
      aria-label={f === null ? "lift position not observed" : `lift_joint at ${lift?.toFixed(3)} m`}>
      <rect x="30" y="262" width="160" height="22" rx="4" className="sch-base" />
      <text x="110" y="277" textAnchor="middle" className="sch-label">base</text>
      <rect x="98" y={colTop} width="24" height={colBottom - colTop} rx="3" className="sch-col" />
      {[0, 0.5, 1].map((s) => {
        const yy = colBottom - carH / 2 - s * (colBottom - colTop - carH);
        return <g key={s}><line x1="124" x2="134" y1={yy} y2={yy} className="sch-tick" />
          <text x="138" y={yy} dominantBaseline="middle" className="sch-label">{`L${1000 + s * 350}`}</text></g>;
      })}
      {y !== null ? (
        <g>
          <rect x="60" y={y} width="100" height={carH} rx="4" className="sch-carriage" />
          <line x1="60" x2="22" y1={y + carH / 2} y2={y + carH / 2 + 28} className="sch-arm" />
          <line x1="160" x2="198" y1={y + carH / 2} y2={y + carH / 2 + 28} className="sch-arm" />
          <text x="110" y={y + carH / 2} textAnchor="middle" dominantBaseline="middle" className="sch-value">
            {lift!.toFixed(3)} m</text>
        </g>
      ) : <text x="110" y="150" textAnchor="middle" className="sch-label">lift_joint not observed</text>}
    </svg>
  );
}

export default function SimulationPage() {
  const [sim, setSim] = useState<Sim | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Sim>("/simulation").then((s) => { setSim(s); setErr(null); })
    .catch((e) => { setSim(null); setErr(`${e.code}: ${e.message}`); }), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [load]);

  const js = sim?.joint_state;
  const names: string[] = js?.value?.name ?? [];
  const pos: (number | null)[] = js?.value?.position ?? [];
  const vel: (number | null)[] = js?.value?.velocity ?? [];
  const lift = names.indexOf("lift_joint") >= 0 ? pos[names.indexOf("lift_joint")] : null;
  const frames: any[] = sim?.tf?.value?.frames ?? [];
  const groups: [string, (n: string) => boolean][] = [
    ["Left arm", (n) => n.startsWith("openarm_left")], ["Right arm", (n) => n.startsWith("openarm_right")],
    ["Lift and other", (n) => !n.startsWith("openarm_")]];

  return (
    <div className="page">
      <div className="page-head">
        <h1>Simulation Monitor</h1>
        <p className="muted">Joint states, transforms and controller state as reported by the ROS graph.</p>
      </div>
      <div className="banner banner-info" data-testid="representation-note">
        Telemetry-based representation drawn from <span className="mono">/joint_states</span>. This is not a Gazebo
        render or a live 3D view.{sim?.source_mode === "fixture" ? ` Source: demo fixture ${sim.fixture_id}.` : ""}
      </div>
      {err && <div className="banner banner-error" role="alert">{err}</div>}
      <div className="sim-grid">
        <section className="panel">
          <div className="panel-head"><h2>Lift</h2><FreshPill result={js?.freshness?.result} age={fmtAge(js?.freshness?.age_s)} /></div>
          <LiftSchematic lift={lift} />
          <p className="small muted">Carriage height from <span className="mono">lift_joint</span> over the 0.35 m travel.
            Arms drawn as fixed stubs; their angles are in the table.</p>
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Joint states</h2>
            <span className="small muted">stamp {fmtTime(js?.stamp)} · received {fmtTime(js?.received_at)}</span></div>
          {names.length ? groups.map(([g, pred]) => (
            <div key={g}>
              <h3 className="group-title">{g}</h3>
              <table className="table compact">
                <thead><tr><th>Joint</th><th className="num">Position</th><th className="num">Velocity</th></tr></thead>
                <tbody>
                  {names.map((n, i) => pred(n) ? (
                    <tr key={n}><td className="mono small">{n}</td>
                      <td className="num mono">{fmtNum(pos[i])}</td><td className="num mono">{fmtNum(vel[i])}</td></tr>
                  ) : null)}
                </tbody>
              </table>
            </div>
          )) : <p className="muted">/joint_states not observed{sim && !sim.graph_available ? " (ROS graph unavailable)" : ""}.</p>}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Transforms</h2><FreshPill result={sim?.tf?.freshness?.result} age={fmtAge(sim?.tf?.freshness?.age_s)} /></div>
          {frames.length ? (
            <table className="table compact">
              <thead><tr><th>Parent</th><th>Child</th><th>Type</th></tr></thead>
              <tbody>{frames.map((f) => (
                <tr key={f.child}><td className="mono small">{f.parent}</td><td className="mono small">{f.child}</td>
                  <td className="small">{f.static ? "static" : "dynamic"}</td></tr>
              ))}</tbody>
            </table>
          ) : <p className="muted">No TF frames observed.</p>}
          <h3 className="group-title">Controllers</h3>
          {sim?.controllers?.value?.controllers ? (
            <ul className="kv-list">{sim.controllers.value.controllers.map((c: any) => (
              <li key={c.name}><span className="mono small">{c.name}</span>
                <span className={`ctl ctl-${c.state}`}>{c.state === "active" ? "●" : "■"} {c.state}</span></li>
            ))}</ul>
          ) : <p className="muted">Controller list not observed.</p>}
        </section>
      </div>
    </div>
  );
}
