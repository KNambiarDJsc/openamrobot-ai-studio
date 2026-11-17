#!/usr/bin/env bash
# Live ROS 2 integration check against the real OpenAMRobot upper-body mock profile.
#
#   OVERLAY=~/oar_ws/install STUDIO=/mnt/d/openamrobot-ai-studio bash tests/ros/run_mock_integration.sh
#
# Needs: ROS 2 Jazzy, an overlay with openamr-upperbody-sw built (openamrobot_upperbody_bringup), python3.
# Starts mock.launch.py (ros2_control mock hardware, no Gazebo), starts the read-only adapter, waits for the
# controllers, then checks the adapter's /snapshot from Python (stdlib only) and saves it under
# fixtures/recorded/. Nothing is published to the robot graph; the adapter only subscribes and queries.
# Run it from the ROS machine. On the Windows side, `pytest -m ros` with ADAPTER_URL checks the same adapter.
set -euo pipefail
OVERLAY=${OVERLAY:?set OVERLAY to the install/ dir that contains openamrobot_upperbody_bringup}
STUDIO=${STUDIO:-$(cd "$(dirname "$0")/../.." && pwd)}
PORT=${ADAPTER_PORT:-8765}
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-73}   # isolated domain: never talk to another graph by accident
LOG=$(mktemp -d)
set +u; source /opt/ros/jazzy/setup.bash; source "$OVERLAY/setup.bash"; set -u

cleanup() { kill "${ADAPTER_PID:-}" "${LAUNCH_PID:-}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT

ros2 launch openamrobot_upperbody_bringup mock.launch.py >"$LOG/launch.log" 2>&1 &
LAUNCH_PID=$!
ROBOT_STACK_REVISION=${ROBOT_STACK_REVISION:-"upperbody-sw $(git -C "$OVERLAY/.." rev-parse --short HEAD 2>/dev/null || echo unknown) mock"} \
  PYTHONPATH="$STUDIO/services/ros-adapter" python3 -m studio_ros_adapter.server --port "$PORT" >"$LOG/adapter.log" 2>&1 &
ADAPTER_PID=$!

python3 - "$PORT" "$STUDIO" <<'EOF'
import json, sys, time, urllib.request
from pathlib import Path
port, studio = sys.argv[1], Path(sys.argv[2])
expected = {"joint_state_broadcaster", "left_arm_controller", "right_arm_controller",
            "left_gripper_controller", "right_gripper_controller", "lift_controller"}
deadline, snap = time.time() + 90, None
while time.time() < deadline:
    try:
        snap = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/snapshot", timeout=2))
        ctl = next((o for o in snap["observations"] if o["kind"] == "controllers"), None)
        states = {c["name"]: c["state"] for c in (ctl or {}).get("value", {}).get("controllers", [])}
        js = next((o for o in snap["observations"] if o["kind"] == "joint_state"), None)
        if expected <= {n for n, s in states.items() if s == "active"} and js:
            break
    except Exception as e:  # adapter or graph still starting
        pass
    time.sleep(1)
else:
    sys.exit(f"FAIL: controllers not all active within 90 s; last snapshot: {json.dumps(snap)[:800]}")
names = set(js["value"]["name"])
need = {f"openarm_{s}_joint{i}" for s in ("left", "right") for i in range(1, 8)} | {
        "openarm_left_finger_joint1", "openarm_right_finger_joint1", "lift_joint"}
assert need <= names, f"FAIL: /joint_states lacks {sorted(need - names)}"
assert snap["graph_available"], snap["graph_error"]
tf = next((o for o in snap["observations"] if o["kind"] == "tf"), None)
print("PASS: graph nodes", len(next(o for o in snap["observations"] if o["kind"] == "graph")["value"]["nodes"]),
      "| controllers", sorted(states.items()), "| joints", len(names), "| tf frames",
      len(tf["value"]["frames"]) if tf else 0)
out = studio / "fixtures" / "recorded"
out.mkdir(parents=True, exist_ok=True)
p = out / f"mock_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
p.write_text(json.dumps(snap, indent=1) + "\n")
print("recorded", p)
EOF
echo "logs: $LOG"
