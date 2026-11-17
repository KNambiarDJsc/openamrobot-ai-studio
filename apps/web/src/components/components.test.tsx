import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReadinessEvaluation } from "@contracts";

import { LineChart } from "./LineChart";
import { StatusBadge } from "./StatusBadge";
import { sortChecks, TraceView } from "./TraceView";

const ev = {
  trace_id: "diag-2026-11-17-abcd0001", task: "upper_body", status: "BLOCKED",
  summary: "Upper body: BLOCKED by controllers. lift_controller is inactive, not active",
  evaluated_at: "2026-11-17T20:41:12.184Z", policy_version: "readiness-policy/1", source_mode: "fixture",
  fixture_id: "inactive_controller", snapshot_id: "fx", revisions: { studio: "abc123", adapter: "fixture" },
  blocking: ["controller.lift_controller"], unknown: [], warnings: [], disclaimer: "Not a safety function.",
  checks: [
    { id: "ros_graph", subsystem: "ros_graph", outcome: "pass", severity: "info", summary: "graph ok", evidence: [
      { source: "ros_graph", observed_at: "2026-11-17T20:41:11.584Z", freshness: { age_s: 0.6, max_age_s: 5, result: "fresh" },
        value: {}, severity: "info", software_revision: { studio: "abc123" }, trace_id: "diag-2026-11-17-abcd0001" }] },
    { id: "controller.lift_controller", subsystem: "controllers", outcome: "fail", severity: "error",
      summary: "lift_controller is inactive, not active", next_check: "ros2 control list_controllers", evidence: [
      { source: "/controller_manager/list_controllers", observed_at: "2026-11-17T20:41:11.384Z",
        freshness: { age_s: 0.8, max_age_s: 3, result: "fresh" }, value: { state: "inactive" }, severity: "error",
        software_revision: { studio: "abc123" }, trace_id: "diag-2026-11-17-abcd0001" }] },
  ],
} as unknown as ReadinessEvaluation;

describe("StatusBadge", () => {
  it("never relies on colour alone: icon and word are rendered", () => {
    render(<StatusBadge status="BLOCKED" />);
    const b = screen.getByText("BLOCKED");
    expect(b).toHaveAttribute("data-status", "BLOCKED");
    expect(b.querySelector(".badge-icon")?.textContent).toBe("■");
  });
});

describe("TraceView", () => {
  it("shows failures first with source, receive time, freshness and trace id", () => {
    render(<TraceView ev={ev} />);
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("controller.lift_controller");
    expect(rows[1]).toHaveTextContent("/controller_manager/list_controllers");
    expect(rows[1]).toHaveTextContent("2026-11-17 20:41:11.384Z");
    expect(rows[1]).toHaveTextContent("fresh");
    expect(screen.getByText(/trace diag-2026-11-17-abcd0001/)).toBeInTheDocument();
    expect(screen.getByText(/fixture inactive_controller \(demo data\)/)).toBeInTheDocument();
  });
  it("sorts error < fail < unknown < pass", () => {
    expect(sortChecks(ev.checks).map((c) => c.outcome)).toEqual(["fail", "pass"]);
  });
});

describe("LineChart", () => {
  it("shows the empty text instead of drawing without data", () => {
    render(<LineChart title="lift" unit="m" series={[{ key: "a", label: "a", color: "#3987e5", points: [] }]}
      emptyText="Telemetry socket not connected" />);
    expect(screen.getByText("Telemetry socket not connected")).toBeInTheDocument();
  });
  it("has a legend for two series and a tooltip on hover", () => {
    const { container } = render(<LineChart title="arms" unit="rad" emptyText="none" series={[
      { key: "l", label: "left j2", color: "#3987e5", points: [0, 0.1, 0.2] },
      { key: "r", label: "right j2", color: "#d95926", points: [0, -0.1, null] }]} />);
    expect(container.querySelectorAll(".legend li")).toHaveLength(2);
    expect(container.querySelectorAll("path")).toHaveLength(2);
    const hit = container.querySelector("rect[fill='transparent']")!;
    hit.getBoundingClientRect = () => ({ left: 0, width: 100, top: 0, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.mouseMove(hit, { clientX: 99 });
    expect(screen.getByRole("status")).toHaveTextContent("left j2");
    expect(screen.getByRole("status")).toHaveTextContent("0.2000 rad");
    expect(screen.getByRole("status")).toHaveTextContent("—");
  });
});
