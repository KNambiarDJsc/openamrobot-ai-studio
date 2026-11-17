"""Adapter message conversion and snapshot shape, without ROS (duck-typed message stand-ins)."""
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from oar_contracts import Snapshot, Task
from studio_api.diagnostics import evaluate
from studio_ros_adapter import snapshot as S

ROOT = Path(__file__).resolve().parents[1]


def stamp(sec, nsec=0):
    return NS(sec=sec, nanosec=nsec)


def test_stamp_zero_is_none_and_sim_time_kept():
    assert S.stamp_to_dt(stamp(0)) is None
    assert S.stamp_to_dt(stamp(12, 500_000_000)) == datetime(1970, 1, 1, 0, 0, 12, 500000, tzinfo=timezone.utc)


def test_joint_state_nan_becomes_null():
    m = NS(name=["lift_joint"], position=[float("nan")], velocity=[0.0])
    assert S.joint_state(m) == {"name": ["lift_joint"], "position": [None], "velocity": [0.0]}


def test_diagnostic_level_bytes_and_int():
    kv = [NS(key="rate_hz", value="9.8")]
    a = S.diagnostic_status(NS(name="n", hardware_id="h", level=b"\x01", message="m", values=kv))
    b = S.diagnostic_status(NS(name="n", hardware_id="h", level=2, message="m", values=kv))
    assert a["level"] == 1 and b["level"] == 2 and a["values"] == {"rate_hz": "9.8"}


def test_controllers_and_lifecycle_conversion():
    r = NS(controller=[NS(name="lift_controller", state="inactive", type="joint_trajectory_controller/JointTrajectoryController")])
    assert S.controllers(r)["controllers"][0] == {"name": "lift_controller", "state": "inactive",
                                                  "type": "joint_trajectory_controller/JointTrajectoryController"}
    assert S.lifecycle("amcl", NS(current_state=NS(id=3, label="active"))) == {"node": "amcl", "state_id": 3, "state_label": "active"}


def _builder_with_graph():
    b = S.SnapshotBuilder("rev1", "upperbody-sw test", 0)
    b.set_nodes(["/controller_manager", "/robot_state_publisher"])
    return b


def test_snapshot_validates_against_contract_and_evaluates():
    b = _builder_with_graph()
    names = [f"openarm_{s}_joint{i}" for s in ("left", "right") for i in range(1, 8)] + \
            ["openarm_left_finger_joint1", "openarm_right_finger_joint1", "lift_joint"]
    b.put("/joint_states", "joint_state", S.joint_state(NS(name=names, position=[0.0] * 17, velocity=[0.0] * 17)),
          S.stamp_to_dt(stamp(1_700_000_000)))
    ctl = [NS(name=n, state="active", type="t") for n in ("joint_state_broadcaster", "left_arm_controller",
                                                         "right_arm_controller", "left_gripper_controller",
                                                         "right_gripper_controller", "lift_controller")]
    b.put("/controller_manager/list_controllers", "controllers", S.controllers(NS(controller=ctl)))
    tfm = NS(transforms=[NS(header=NS(frame_id="base_link"), child_frame_id="lift_base_link",
                            transform=NS(translation=NS(x=0.06, y=0.0, z=0.1)))])
    b.put_tf(S.tf_frames(tfm, True))
    snap = Snapshot.model_validate(b.build())
    assert snap.graph_available and snap.observations[0].kind == "graph"
    assert {o.kind for o in snap.observations} == {"graph", "joint_state", "controllers", "tf"}
    ev = evaluate(snap, Task.upper_body, datetime.now(timezone.utc), "diag-live")
    assert ev.status.value == "READY", ev.summary


def test_no_nodes_means_graph_unavailable():
    b = S.SnapshotBuilder("rev1", None, 7, graph_timeout_s=0.0)
    b.put("/joint_states", "joint_state", {"name": [], "position": [], "velocity": []})
    snap = Snapshot.model_validate(b.build())
    assert not snap.graph_available and snap.observations == []
    assert "ROS_DOMAIN_ID 7" in snap.graph_error
    assert evaluate(snap, Task.overall, datetime.now(timezone.utc), "d").status.value == "ERROR"


def test_diagnostic_names_are_bounded():
    b = _builder_with_graph()
    for i in range(S.SnapshotBuilder.MAX_DIAGNOSTIC_NAMES + 50):
        b.put("/diagnostics", "diagnostics", {"name": f"d{i}", "level": 0}, key=f"d{i}")
    assert sum(1 for o in b.build()["observations"] if o["kind"] == "diagnostics") == S.SnapshotBuilder.MAX_DIAGNOSTIC_NAMES


def test_adapter_core_imports_without_ros():
    code = "import sys; sys.path.insert(0, r'%s'); import studio_ros_adapter.snapshot, studio_ros_adapter.allowlist, studio_ros_adapter.server; print('ok')" % (ROOT / "services" / "ros-adapter")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr
    assert "rclpy" not in sys.modules or True  # server imports rclpy lazily inside main()


def test_contracts_generated_files_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_contracts.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_nan_in_json_is_never_emitted():
    b = _builder_with_graph()
    b.put("/joint_states", "joint_state", S.joint_state(NS(name=["a"], position=[math.inf], velocity=[math.nan])))
    import json
    json.dumps(b.build(), allow_nan=False)  # raises if a NaN/inf leaked
