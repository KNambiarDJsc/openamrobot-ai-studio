export type Status = "READY" | "BLOCKED" | "UNKNOWN" | "ERROR";

/** Status colours are reserved and always ship with an icon and a word (never colour alone). */
export const STATUS_META: Record<Status, { icon: string; label: string; cls: string; meaning: string }> = {
  READY: { icon: "●", label: "READY", cls: "st-ready", meaning: "All required checks present, fresh and passing" },
  BLOCKED: { icon: "■", label: "BLOCKED", cls: "st-blocked", meaning: "A required check is present, fresh and failing" },
  UNKNOWN: { icon: "?", label: "UNKNOWN", cls: "st-unknown", meaning: "A required fact is missing, stale or contradictory" },
  ERROR: { icon: "✕", label: "ERROR", cls: "st-error", meaning: "The diagnostic query itself could not complete" },
};

export function statusMeta(s: string | null | undefined) {
  return STATUS_META[(s as Status)] ?? STATUS_META.UNKNOWN;
}

export function fmtAge(age: number | null | undefined): string {
  if (age === null || age === undefined) return "never";
  if (age < 1) return `${Math.round(age * 1000)} ms`;
  if (age < 120) return `${age.toFixed(age < 10 ? 2 : 1)} s`;
  return `${Math.round(age / 60)} min`;
}

/** UTC wall time with milliseconds: the same form the copilot cites, so text and UI match. */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").replace(/\.(\d{3})Z$/, ".$1Z");
}

export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined) return "non-finite";
  return v.toFixed(digits);
}

/** datetime-local (local time, no zone) -> ISO UTC for the API. */
export function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

// Lift travel: 350 mm column; calibration stops L1000 / L1175 / L1350 are lift_joint 0 / 0.175 / 0.35 m
// (upperbody-sw mock.launch.py docstring and the roadmap).
export const LIFT_TRAVEL_M = 0.35;

export function liftFraction(v: number | null | undefined): number | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  return Math.max(0, Math.min(1, v / LIFT_TRAVEL_M));
}

export const SUBSYSTEM_LABEL: Record<string, string> = {
  overall: "Robot",
  upper_body: "Upper body",
  navigation: "Navigation",
  controllers: "Controllers",
  joint_states: "Joint states",
  diagnostics: "Diagnostics",
  ros_graph: "ROS graph",
  connection: "Connection",
  copilot: "Copilot",
  demo: "Demo",
};
