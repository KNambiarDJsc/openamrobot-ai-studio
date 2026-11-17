"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { API_URL, ApiError, getStatus, type StatusResponse } from "@/lib/api";
import { fmtTime } from "@/lib/format";

import { StatusBadge } from "./StatusBadge";

type Ctx = { status: StatusResponse | null; error: ApiError | null; refresh: () => Promise<void> };
const StatusContext = createContext<Ctx>({ status: null, error: null, refresh: async () => undefined });
export const useStudioStatus = () => useContext(StatusContext);

const NAV = [
  { href: "/", label: "Robot Overview", icon: "◧" },
  { href: "/copilot", label: "Diagnostics Copilot", icon: "❯" },
  { href: "/evidence", label: "Evidence Explorer", icon: "≣" },
  { href: "/simulation", label: "Simulation Monitor", icon: "◎" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getStatus());
      setError(null);
    } catch (e) {
      // Keep nothing from before: a failed fetch must not leave stale data looking current.
      setStatus(null);
      setError(e instanceof ApiError ? e : new ApiError("unknown", String(e)));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const conn = status?.connection;
  const overall = status?.readiness?.overall;
  return (
    <StatusContext.Provider value={{ status, error, refresh }}>
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">◆</span>
            <div>
              <div className="brand-name">AI Studio</div>
              <div className="brand-sub">OpenAMRobot · read-only</div>
            </div>
          </div>
          <nav>
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className={`nav-item ${path === n.href ? "active" : ""}`}>
                <span className="nav-icon" aria-hidden="true">{n.icon}</span>{n.label}
              </Link>
            ))}
          </nav>
          <div className="sidebar-foot">
            <div>Diagnostics only. No motion, publishing or controller changes.</div>
            <div className="mono small">studio {status?.snapshot.revisions.studio ?? "—"}</div>
          </div>
        </aside>
        <div className="main">
          <header className="topbar">
            <div className="topbar-left">
              {error ? (
                <span className="conn conn-down" data-testid="conn-state"><span aria-hidden="true">✕</span> API unreachable</span>
              ) : conn ? (
                <span className={`conn conn-${conn.state}`} data-testid="conn-state">
                  <span aria-hidden="true">{conn.state === "connected" || conn.state === "fixture" ? "●" : "◐"}</span>
                  {conn.mode === "fixture" ? "Demo mode" : "Live"} · {conn.state}
                </span>
              ) : <span className="conn">connecting…</span>}
              {status?.mode === "demo" && (
                <span className="demo-flag" data-testid="demo-flag">DEMO FIXTURE · {status.snapshot.fixture_id}</span>
              )}
              {conn?.mode === "live" && conn.adapter_url && <span className="mono small muted">{conn.adapter_url}</span>}
            </div>
            <div className="topbar-right">
              {overall && <span className="muted small">Robot</span>}
              {overall && <StatusBadge status={overall.status} size="sm" />}
              {status && <span className="mono small muted">evaluated {fmtTime(status.snapshot.evaluated_at)}</span>}
            </div>
          </header>
          {error && (
            <div className="banner banner-error" role="alert">
              <strong>{error.code}</strong>: {error.message}. Nothing below is current; no data is substituted.
              Start the API (<span className="mono">scripts/dev.ps1</span>) or check <span className="mono">{API_URL}</span>.
            </div>
          )}
          {conn?.mode === "live" && conn.state !== "connected" && (
            <div className="banner banner-warn" role="alert">
              ROS adapter {conn.state}{conn.last_error ? `: ${conn.last_error}` : ""}. Readiness reports ERROR until it
              answers; demo fixtures are not used in live mode.
            </div>
          )}
          <main className="content">{children}</main>
        </div>
      </div>
    </StatusContext.Provider>
  );
}
