"""Build the demo fixtures in fixtures/*.json.

    python scripts/make_fixtures.py [--base fixtures/recorded/<file>.json]

Every fixture is labelled. Each scenario is the healthy baseline plus one documented change, so the
difference in the readiness result is attributable to that change alone.

Baseline provenance:
  * upper body: if --base is given (a snapshot recorded by the ROS adapter from a real
    mock.launch.py run, see docs/ros-integration.md), its graph, controller and /joint_states
    observations are used verbatim, with their timestamps shifted to the fixture's clock;
    otherwise synthetic values in the shape of those interfaces.
  * navigation, lifecycle and /diagnostics: always synthetic, in the shape of
    openamr_nav_msgs/NavigationStatus (CONTRACT_VERSION 2) and navigation_status_node's /diagnostics
    mirror. No platform-sw navigation stack was run to produce them.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "contracts"), str(ROOT / "services" / "api")]

from studio_api import profile as P  # noqa: E402

T0 = datetime(2026, 11, 17, 20, 41, 12, 184000, tzinfo=timezone.utc)  # fixture evaluation time


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def obs(source, kind, value, age_s, stamp_age_s=None):
    t = T0 - timedelta(seconds=age_s)
    return {"source": source, "kind": kind, "value": value, "received_at": iso(t),
            "stamp": iso(T0 - timedelta(seconds=stamp_age_s if stamp_age_s is not None else age_s))}


PARK = {  # radians; a plausible stowed pose, synthetic
    1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0, 7: 0.0,
}


def joint_frame(t_s: float):
    names, pos, vel = [], [], []
    for side in ("left", "right"):
        for i in range(1, 8):
            names.append(f"openarm_{side}_joint{i}")
            a = 0.25 * math.sin(0.4 * t_s + i * 0.6) if i in (1, 2, 4) else 0.0
            pos.append(round(PARK[i] + (a if side == "left" else -a), 5))
            vel.append(round(0.1 * math.cos(0.4 * t_s + i * 0.6) if i in (1, 2, 4) else 0.0, 5))
        names.append(f"openarm_{side}_finger_joint1")
        pos.append(0.0)
        vel.append(0.0)
    names.append("lift_joint")
    pos.append(round(0.12 + 0.05 * math.sin(0.2 * t_s), 5))
    vel.append(round(0.01 * math.cos(0.2 * t_s), 5))
    return {"name": names, "position": pos, "velocity": vel}


def synthetic_upper_body():
    controllers = [{"name": n, "state": "active",
                    "type": "joint_state_broadcaster/JointStateBroadcaster" if n == "joint_state_broadcaster"
                    else "position_controllers/GripperActionController" if "gripper" in n
                    else "joint_trajectory_controller/JointTrajectoryController"}
                   for n in P.UPPER_BODY_CONTROLLERS]
    nodes = ["/robot_state_publisher", "/controller_manager"] + [f"/spawner_{n}" for n in []]
    return [
        obs("ros_graph", "graph", {"nodes": nodes}, 0.6),
        obs("/controller_manager/list_controllers", "controllers", {"available": True, "controllers": controllers}, 0.8),
        obs("/joint_states", "joint_state", joint_frame(0.0), 0.02),
    ]


def navigation(ready=True, health=1, reasons=(), sensors=(("scan_front", 0), ("imu", 0)), age=0.4):
    v = {"contract_version": 2, "profile_id": "sim_default", "thresholds_id": "UNSET",
         "health": health, "navigation_readiness": 1 if ready else 0,
         "not_ready_reasons": list(reasons), "active_reasons": [], "sensor_gaps": 0}
    out = [obs("/navigation/status", "navigation_status", v, age)]
    diag_level = {1: 0, 2: 1, 3: 2}.get(health, 3)
    out.append(obs("/diagnostics", "diagnostics", {
        "name": "navigation_status_node: health", "hardware_id": "sim_default", "level": diag_level,
        "message": P.NAV_HEALTH[health], "values": {"navigation_readiness": str(v["navigation_readiness"]),
                                                   "active_reasons": ""}}, age))
    for sid, lvl in sensors:
        out.append(obs("/diagnostics", "diagnostics", {
            "name": f"navigation_status_node: sensor {sid}", "hardware_id": sid, "level": lvl,
            "message": {0: "OK", 1: "DEGRADED", 2: "UNKNOWN", 3: "STALE"}[lvl],
            "values": {"reason": "0" if lvl == 0 else "2005", "rate_hz": "10.00" if lvl == 0 else "3.10",
                       "required": "True"}}, age))
    return out


def lifecycle(inactive=()):
    return [obs(f"/{n}/get_state", "lifecycle",
                {"node": n, "state_id": 2 if n in inactive else 3,
                 "state_label": "inactive" if n in inactive else "active"}, 1.1)
            for n in P.NAV2_MANAGED_NODES]


def tf():
    frames = [{"parent": "base_link", "child": "lift_base_link", "static": True},
              {"parent": "lift_base_link", "child": "lift_carriage_link", "static": False},
              {"parent": "map", "child": "odom", "static": False},
              {"parent": "odom", "child": "base_link", "static": False}]
    return [obs("/tf", "tf", {"frames": frames}, 0.05)]


def series():
    return [{"t": iso(T0 - timedelta(seconds=10 - k * 0.2)), **joint_frame(k * 0.2)} for k in range(51)]


def snapshot(fid, observations, graph_available=True, graph_error=None):
    return {"snapshot_id": f"fx-{fid}", "source_mode": "fixture", "fixture_id": fid, "captured_at": iso(T0),
            "graph_available": graph_available, "graph_error": graph_error,
            "revisions": {"studio": "fixture", "adapter": "fixture",
                          "robot_stack": "upperbody-sw a3a93c6 / platform-sw 69847ab (shape only)"},
            "observations": observations}


def build(base_upper):
    healthy_obs = base_upper + navigation() + lifecycle() + tf()

    def variant(fn):
        o = copy.deepcopy(healthy_obs)
        fn(o)
        return o

    def lift_inactive(o):
        for x in o:
            if x["kind"] == "controllers":
                for c in x["value"]["controllers"]:
                    if c["name"] == "lift_controller":
                        c["state"] = "inactive"

    def stale(o):
        for x in o:
            if x["kind"] in ("joint_state", "navigation_status"):
                t = T0 - timedelta(seconds=4.2 if x["kind"] == "joint_state" else 9.0)
                x["received_at"] = iso(t)
                x["stamp"] = iso(t)

    def conflict(o):
        for x in o:
            if x["kind"] == "lifecycle" and x["value"]["node"] == "controller_server":
                x["value"].update(state_id=2, state_label="inactive")

    def warning(o):
        o[:] = [x for x in o if x["kind"] not in ("navigation_status", "diagnostics")]
        o.extend(navigation(health=2, sensors=(("scan_front", 0), ("scan_rear", 1), ("imu", 0))))

    scenarios = [
        ("healthy", "Healthy robot", "All six upper-body controllers active, /joint_states fresh, navigation READY.",
         "baseline", healthy_obs, True, None),
        ("inactive_controller", "Inactive controller", "lift_controller reported inactive by controller_manager.",
         "baseline with lift_controller state set to inactive", variant(lift_inactive), True, None),
        ("stale_telemetry", "Stale telemetry", "/joint_states last received 4.2 s ago, /navigation/status 9 s ago.",
         "baseline with /joint_states and /navigation/status received_at moved back", variant(stale), True, None),
        ("missing_graph", "Missing ROS graph", "The adapter answers but discovers no ROS nodes.",
         "no observations; graph_available false", [], False,
         "adapter running, no ROS 2 nodes discovered on ROS_DOMAIN_ID 0 within 3.0 s"),
        ("conflicting_state", "Conflicting state",
         "/navigation/status says READY while controller_server's lifecycle state is inactive.",
         "baseline with controller_server get_state set to inactive", variant(conflict), True, None),
        ("diagnostic_warning", "Diagnostic warning",
         "Rear scan publishes below rate: sensor WARN and navigation health DEGRADED, still READY.",
         "baseline with health DEGRADED and a WARN sensor entry", variant(warning), True, None),
    ]
    out = []
    for fid, title, desc, change, o, ga, ge in scenarios:
        out.append({
            "fixture": {"id": fid, "title": title, "description": desc, "label": "DEMO FIXTURE",
                        "evaluate_at": iso(T0), "change_from_baseline": change,
                        "provenance": PROVENANCE},
            "snapshot": snapshot(fid, o, ga, ge),
            "series": series() if ga else [],
        })
    return out


PROVENANCE = ("Synthetic example data in the shape of the real interfaces (upperbody-sw a3a93c6 controllers and "
              "joints; openamr_nav_msgs/NavigationStatus v2). Not recorded from a robot.")


def main():
    global PROVENANCE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="adapter snapshot JSON recorded from a real mock.launch.py run")
    a = ap.parse_args()
    upper = synthetic_upper_body()
    if a.base:
        rec = json.loads(Path(a.base).read_text(encoding="utf-8"))
        cap = datetime.fromisoformat(rec["captured_at"].replace("Z", "+00:00"))
        upper = []
        for o in rec["observations"]:
            if o["kind"] not in ("graph", "controllers", "joint_state"):
                continue
            o = dict(o)
            for k in ("received_at", "stamp"):
                if o.get(k):
                    t = datetime.fromisoformat(o[k].replace("Z", "+00:00"))
                    o[k] = iso(T0 - (cap - t)) if k == "received_at" else o[k]
            upper.append(o)
        PROVENANCE = (f"Upper body: recorded by the ROS adapter from a real mock.launch.py run ({Path(a.base).name}, "
                      f"stack {rec['revisions'].get('robot_stack')}), received_at shifted to the fixture clock; header "
                      "stamps kept as recorded. Navigation, lifecycle and /diagnostics: synthetic, in the shape of "
                      "openamr_nav_msgs/NavigationStatus v2. Not a robot recording.")
    for fx in build(upper):
        p = ROOT / "fixtures" / f"{fx['fixture']['id']}.json"
        p.write_text(json.dumps(fx, indent=1) + "\n", encoding="utf-8")
        print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
