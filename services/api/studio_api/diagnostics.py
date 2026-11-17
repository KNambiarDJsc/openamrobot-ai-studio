"""Deterministic readiness evaluation (RFC section 2 and Appendix A).

Pure functions: a Snapshot and an evaluation time in, a ReadinessEvaluation out. No I/O, no clock,
no model. The same snapshot and time always give the same result, which is what makes fixtures,
tests and evidence replay meaningful.

Status rules, per task:
  ERROR    the ROS graph is unavailable, or a diagnostic query failed (timeout, call error)
  BLOCKED  a required fact is present, fresh and fails (e.g. a controller is not active)
  UNKNOWN  a required fact is missing, stale or contradicts another fact
  READY    every required fact is present, fresh and passes
Precedence: ERROR > BLOCKED > UNKNOWN > READY. Missing data is never turned into READY or BLOCKED.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, Optional

from oar_contracts import (
    Check, CheckOutcome, EvidenceRecord, Freshness, FreshnessResult, Observation, Readiness,
    ReadinessEvaluation, Revisions, Severity, Snapshot, Task,
)

from . import profile as P

OK, FAIL, UNK, ERR = CheckOutcome.passed, CheckOutcome.failed, CheckOutcome.unknown, CheckOutcome.error


# ---------------------------------------------------------------- freshness

def freshness(obs: Optional[Observation], kind: str, now: datetime) -> Freshness:
    max_age = P.MAX_AGE_S[kind]
    if obs is None:
        return Freshness(age_s=None, max_age_s=max_age, result=FreshnessResult.missing)
    age = (now - obs.received_at).total_seconds()
    if age < -P.FUTURE_TOLERANCE_S or age > max_age:
        return Freshness(age_s=round(age, 3), max_age_s=max_age, result=FreshnessResult.stale)
    return Freshness(age_s=round(max(age, 0.0), 3), max_age_s=max_age, result=FreshnessResult.fresh)


class _Ctx:
    def __init__(self, snap: Snapshot, now: datetime, trace_id: str):
        self.snap, self.now, self.trace_id = snap, now, trace_id
        self.rev: Revisions = snap.revisions

    def find(self, kind: str, source: Optional[str] = None) -> list[Observation]:
        return [o for o in self.snap.observations if o.kind == kind and (source is None or o.source == source)]

    def one(self, kind: str, source: Optional[str] = None) -> Optional[Observation]:
        found = self.find(kind, source)
        return max(found, key=lambda o: o.received_at) if found else None

    def evidence(self, obs: Optional[Observation], kind: str, source: str, severity: Severity,
                 value: Optional[dict] = None) -> EvidenceRecord:
        return EvidenceRecord(
            source=obs.source if obs else source,
            observed_at=obs.received_at if obs else None,
            stamp=obs.stamp if obs else None,
            freshness=freshness(obs, kind, self.now),
            value=value if value is not None else (obs.value if obs else {"observed": False}),
            severity=severity,
            software_revision=self.rev,
            trace_id=self.trace_id,
        )


def _sev(outcome: CheckOutcome) -> Severity:
    return {OK: Severity.info, FAIL: Severity.error, UNK: Severity.warning, ERR: Severity.error}[outcome]


def _check(ctx, cid, subsystem, outcome, summary, evidence, next_check=None, severity=None) -> Check:
    sev = severity or _sev(outcome)
    for e in evidence:
        e.severity = sev
    return Check(id=cid, subsystem=subsystem, outcome=outcome, severity=sev, summary=summary,
                 next_check=None if outcome == OK and severity != Severity.warning else next_check,
                 evidence=evidence)


# ---------------------------------------------------------------- graph

def _graph_check(ctx: _Ctx) -> Check:
    if not ctx.snap.graph_available:
        ev = ctx.evidence(None, "graph", "ros_graph", Severity.error,
                          value={"graph_available": False, "error": ctx.snap.graph_error})
        return _check(ctx, "ros_graph", "ros_graph", ERR,
                      f"ROS graph unavailable: {ctx.snap.graph_error or 'no response from the adapter'}",
                      [ev], "Is the ROS adapter running, and does `ros2 node list` show the robot nodes?")
    obs = ctx.one("graph")
    ev = ctx.evidence(obs, "graph", "ros_graph", Severity.info)
    f = ev.freshness.result
    if f != FreshnessResult.fresh:
        return _check(ctx, "ros_graph", "ros_graph", UNK, f"ROS graph listing is {f}", [ev],
                      "Check the adapter's /health and `ros2 node list`.")
    n = len(obs.value.get("nodes", []))
    return _check(ctx, "ros_graph", "ros_graph", OK, f"ROS graph reachable, {n} nodes listed", [ev])


# ---------------------------------------------------------------- upper body

def _upper_body_checks(ctx: _Ctx) -> list[Check]:
    checks: list[Check] = []
    src = "/controller_manager/list_controllers"
    obs = ctx.one("controllers", src)
    ev = ctx.evidence(obs, "controllers", src, Severity.info)
    fr = ev.freshness.result
    active_joints: set[str] = set()
    if obs is None or fr != FreshnessResult.fresh:
        checks.append(_check(ctx, "controller_manager", "controllers", UNK,
                             f"Controller list is {fr}", [ev],
                             "Run `ros2 control list_controllers` and check the adapter log."))
    elif obs.value.get("error"):
        checks.append(_check(ctx, "controller_manager", "controllers", ERR,
                             f"list_controllers query failed: {obs.value['error']}", [ev],
                             "Is /controller_manager responsive? `ros2 control list_controllers`."))
    elif obs.value.get("available") is False:
        checks.append(_check(ctx, "controller_manager", "controllers", FAIL,
                             "controller_manager is not running (list_controllers is not advertised)", [ev],
                             "Start the upper-body bringup (mock.launch.py or sim.launch.py)."))
    else:
        checks.append(_check(ctx, "controller_manager", "controllers", OK,
                             f"controller_manager answered with {len(obs.value.get('controllers', []))} controllers", [ev]))
        listed = {c["name"]: c for c in obs.value.get("controllers", [])}
        for name, joints in P.UPPER_BODY_CONTROLLERS.items():
            c = listed.get(name)
            cev = ctx.evidence(obs, "controllers", src, Severity.info,
                               value={"controller": name, "state": c["state"] if c else "not_loaded",
                                      "type": c.get("type") if c else None})
            if c is None:
                checks.append(_check(ctx, f"controller.{name}", "controllers", FAIL,
                                     f"{name} is not loaded", [cev],
                                     f"`ros2 control list_controllers`: is {name} spawned by the launch file?"))
            elif c["state"] != "active":
                checks.append(_check(ctx, f"controller.{name}", "controllers", FAIL,
                                     f"{name} is {c['state']}, not active", [cev],
                                     f"`ros2 control list_controllers`: why is {name} {c['state']}?"))
            else:
                active_joints.update(joints)
                checks.append(_check(ctx, f"controller.{name}", "controllers", OK, f"{name} is active", [cev]))

    js = ctx.one("joint_state", "/joint_states")
    jev = ctx.evidence(js, "joint_state", "/joint_states", Severity.info)
    fr = jev.freshness.result
    if js is None or fr != FreshnessResult.fresh:
        checks.append(_check(ctx, "joint_states", "joint_states", UNK,
                             f"/joint_states is {fr}" + (f" (age {jev.freshness.age_s} s)" if jev.freshness.age_s is not None else ""),
                             [jev], "`ros2 topic hz /joint_states`: is joint_state_broadcaster publishing?"))
        return checks
    names = js.value.get("name", [])
    pos = js.value.get("position", [])
    present = {n: (pos[i] if i < len(pos) else None) for i, n in enumerate(names)}
    missing = [j for j in P.UPPER_BODY_JOINTS if j not in present]
    nonfinite = [j for j, v in present.items() if j in P.UPPER_BODY_JOINTS and (v is None or not math.isfinite(v))]
    contradicted = sorted(j for j in missing if j in active_joints)
    summary_value = {"joints_reported": len(names), "missing": missing, "non_finite": nonfinite}
    jev2 = ctx.evidence(js, "joint_state", "/joint_states", Severity.info, value=summary_value)
    if contradicted:
        checks.append(_check(ctx, "joint_states", "joint_states", UNK,
                             f"Contradictory: controllers report active but /joint_states lacks {', '.join(contradicted)}",
                             [jev2], "Compare `ros2 control list_hardware_interfaces` with `ros2 topic echo /joint_states --once`."))
    elif nonfinite:
        checks.append(_check(ctx, "joint_states", "joint_states", FAIL,
                             f"Non-finite position for {', '.join(nonfinite)}", [jev2],
                             "Inspect the hardware interface for these joints."))
    elif missing:
        checks.append(_check(ctx, "joint_states", "joint_states", FAIL,
                             f"/joint_states lacks {', '.join(missing)}", [jev2],
                             "Is the hardware profile the expected one (mock or gazebo)?"))
    else:
        checks.append(_check(ctx, "joint_states", "joint_states", OK,
                             f"/joint_states fresh, all {len(P.UPPER_BODY_JOINTS)} expected joints finite", [jev2]))
    return checks


# ---------------------------------------------------------------- navigation

def _reason_names(codes: Iterable[int]) -> list[str]:
    return [P.NAV_REASONS.get(int(c), f"UNKNOWN_REASON_{c}") for c in codes]


def _navigation_checks(ctx: _Ctx) -> list[Check]:
    checks: list[Check] = []
    src = "/navigation/status"
    obs = ctx.one("navigation_status", src)
    ev = ctx.evidence(obs, "navigation_status", src, Severity.info)
    fr = ev.freshness.result
    nav_ready: Optional[bool] = None
    if obs is None or fr != FreshnessResult.fresh:
        checks.append(_check(ctx, "navigation_status", "navigation", UNK, f"{src} is {fr}", [ev],
                             "Is platform-sw bringup running navigation_status_node? `ros2 topic echo /navigation/status --once`."))
    else:
        v = obs.value
        readiness = P.NAV_READINESS.get(v.get("navigation_readiness"), "NOT_READY")
        health = P.NAV_HEALTH.get(v.get("health"), "UNKNOWN")
        reasons = _reason_names(v.get("not_ready_reasons", []))
        decoded = {**v, "navigation_readiness_label": readiness, "health_label": health,
                   "not_ready_reason_names": reasons,
                   "active_reason_names": _reason_names(v.get("active_reasons", []))}
        dev = ctx.evidence(obs, "navigation_status", src, Severity.info, value=decoded)
        nav_ready = readiness == "READY"
        if nav_ready:
            checks.append(_check(ctx, "navigation_status.readiness", "navigation", OK,
                                 "navigation_status_node reports READY", [dev]))
        else:
            checks.append(_check(ctx, "navigation_status.readiness", "navigation", FAIL,
                                 "navigation_status_node reports NOT_READY: " + (", ".join(reasons) or "no reason given"),
                                 [dev], "Address the first reason code; see openamr_nav_msgs/NavigationStatus.msg."))
        hev = ctx.evidence(obs, "navigation_status", src, Severity.info, value={"health": v.get("health"), "health_label": health})
        if health == "FAULT":
            checks.append(_check(ctx, "navigation_status.health", "navigation", FAIL, "Navigation health FAULT", [hev],
                                 "Read active_reasons on /navigation/status."))
        elif health == "UNKNOWN":
            checks.append(_check(ctx, "navigation_status.health", "navigation", UNK, "Navigation health UNKNOWN", [hev],
                                 "navigation_status_node has not decided health yet."))
        elif health == "DEGRADED":
            checks.append(_check(ctx, "navigation_status.health", "navigation", OK, "Navigation health DEGRADED",
                                 [hev], "Read active_reasons on /navigation/status.", severity=Severity.warning))
        else:
            checks.append(_check(ctx, "navigation_status.health", "navigation", OK, "Navigation health OK", [hev]))

    fresh_lc = {}
    for node in P.NAV2_MANAGED_NODES:
        lsrc = f"/{node}/get_state"
        lobs = ctx.one("lifecycle", lsrc)
        if lobs is not None:  # lifecycle polling is optional; navigation_status already rolls the stack up
            fresh_lc[node] = (lsrc, lobs, ctx.evidence(lobs, "lifecycle", lsrc, Severity.info))
    inactive = [n for n, (_, lobs, lev) in fresh_lc.items()
                if lev.freshness.result == FreshnessResult.fresh and not lobs.value.get("error")
                and lobs.value.get("state_id") != P.LIFECYCLE_ACTIVE]
    # Two fresh sources disagree: neither is believed, both are reported UNKNOWN (RFC A.1).
    contradiction = bool(nav_ready and inactive)
    if contradiction:
        for i, c in enumerate(checks):
            if c.id == "navigation_status.readiness":
                checks[i] = _check(ctx, c.id, c.subsystem, UNK,
                                   f"Contradictory: /navigation/status says READY while {', '.join(inactive)} "
                                   "is not active", c.evidence,
                                   "Compare `ros2 lifecycle get` for each node with /navigation/status.")
    for node, (lsrc, lobs, lev) in fresh_lc.items():
        lfr = lev.freshness.result
        if lfr != FreshnessResult.fresh:
            checks.append(_check(ctx, f"lifecycle.{node}", "navigation", UNK, f"{node} lifecycle state is {lfr}", [lev],
                                 f"`ros2 lifecycle get /{node}`"))
        elif lobs.value.get("error"):
            checks.append(_check(ctx, f"lifecycle.{node}", "navigation", ERR,
                                 f"get_state on {node} failed: {lobs.value['error']}", [lev], f"`ros2 lifecycle get /{node}`"))
        elif node in inactive:
            label = P.LIFECYCLE_LABELS.get(lobs.value.get("state_id"), "unknown")
            if contradiction:
                checks.append(_check(ctx, f"lifecycle.{node}", "navigation", UNK,
                                     f"Contradictory: {node} is {label} while /navigation/status says READY", [lev],
                                     f"`ros2 lifecycle get /{node}`"))
            else:
                checks.append(_check(ctx, f"lifecycle.{node}", "navigation", FAIL, f"{node} is {label}, not active", [lev],
                                     f"`ros2 lifecycle get /{node}`; check lifecycle_manager_navigation logs."))
        else:
            checks.append(_check(ctx, f"lifecycle.{node}", "navigation", OK, f"{node} is active", [lev]))
    return checks


# ---------------------------------------------------------------- diagnostics

def _diagnostic_checks(ctx: _Ctx) -> list[Check]:
    checks: list[Check] = []
    for obs in sorted(ctx.find("diagnostics"), key=lambda o: o.value.get("name", "")):
        name = obs.value.get("name", "?")
        level = obs.value.get("level")
        label = P.DIAG_LEVELS.get(level, f"LEVEL_{level}")
        ev = ctx.evidence(obs, "diagnostics", "/diagnostics", Severity.info,
                          value={**obs.value, "level_label": label})
        cid = f"diagnostic.{name}"
        msg = obs.value.get("message", "")
        if ev.freshness.result != FreshnessResult.fresh:
            checks.append(_check(ctx, cid, "diagnostics", UNK, f"{name}: last report is {ev.freshness.result}", [ev],
                                 "Is the publisher of this diagnostic still running?"))
        elif label == "ERROR":
            checks.append(_check(ctx, cid, "diagnostics", FAIL, f"{name}: ERROR {msg}".strip(), [ev],
                                 "`ros2 topic echo /diagnostics` and read this entry's values."))
        elif label == "STALE":
            checks.append(_check(ctx, cid, "diagnostics", UNK, f"{name}: publisher reports STALE {msg}".strip(), [ev],
                                 "The publisher itself reports stale inputs."))
        elif label == "WARN":
            checks.append(_check(ctx, cid, "diagnostics", OK, f"{name}: WARN {msg}".strip(), [ev],
                                 "`ros2 topic echo /diagnostics` and read this entry's values.", severity=Severity.warning))
        else:
            checks.append(_check(ctx, cid, "diagnostics", OK, f"{name}: OK {msg}".strip(), [ev]))
    return checks


# ---------------------------------------------------------------- roll-up

def roll_up(checks: list[Check]) -> Readiness:
    outcomes = {c.outcome for c in checks}
    if ERR in outcomes:
        return Readiness.ERROR
    if FAIL in outcomes:
        return Readiness.BLOCKED
    if UNK in outcomes or not checks:
        return Readiness.UNKNOWN
    return Readiness.READY


_TASK_LABEL = {Task.overall: "Robot", Task.upper_body: "Upper body (arms, grippers, lift controllers)",
               Task.navigation: "Navigation"}


def evaluate(snap: Snapshot, task: Task | str, now: datetime, trace_id: str,
             subsystems: Iterable[str] = ("upper_body", "navigation")) -> ReadinessEvaluation:
    task = Task(task)
    ctx = _Ctx(snap, now, trace_id)
    graph = _graph_check(ctx)
    if graph.outcome == ERR:
        checks = [graph]
    else:
        checks = [graph]
        wanted = set(subsystems) if task == Task.overall else {task.value}
        if "upper_body" in wanted:
            checks += _upper_body_checks(ctx)
        if "navigation" in wanted:
            checks += _navigation_checks(ctx)
        if task == Task.overall:
            checks += _diagnostic_checks(ctx)
    status = roll_up(checks)
    blocking = [c.id for c in checks if c.outcome == FAIL]
    unknown = [c.id for c in checks if c.outcome in (UNK, ERR)]
    warnings = [c.id for c in checks if c.outcome == OK and c.severity == Severity.warning]
    label = _TASK_LABEL[task]
    if status == Readiness.READY:
        summary = f"{label}: READY. {len(checks)} checks passed" + (f", {len(warnings)} with warnings." if warnings else ".")
    elif status == Readiness.ERROR:
        first = next(c for c in checks if c.outcome == ERR)
        summary = f"{label}: ERROR. {first.summary}"
    elif status == Readiness.BLOCKED:
        first = next(c for c in checks if c.outcome == FAIL)
        more = f" (+{len(blocking) - 1} more)" if len(blocking) > 1 else ""
        summary = f"{label}: BLOCKED by {first.subsystem}. {first.summary}{more}"
    else:
        first = next((c for c in checks if c.outcome == UNK), None)
        summary = f"{label}: UNKNOWN. " + (first.summary if first else "no checks applied")
    return ReadinessEvaluation(
        trace_id=trace_id, task=task, status=status, summary=summary, evaluated_at=now,
        policy_version=P.POLICY_VERSION, source_mode=snap.source_mode, fixture_id=snap.fixture_id,
        snapshot_id=snap.snapshot_id, revisions=snap.revisions, blocking=blocking, unknown=unknown,
        warnings=warnings, checks=checks,
    )
