"""Read-only enforcement: the adapter, the agent and the API can observe but never act on the robot."""
import ast
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from studio_agent import READ_ONLY_TOOLS
from studio_ros_adapter import allowlist
from studio_ros_adapter.server import make_handler
from studio_ros_adapter.snapshot import SnapshotBuilder

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = [ROOT / "services" / d for d in ("ros-adapter", "agent", "api")]

FORBIDDEN_CALLS = {"create_publisher", "create_action_client", "publish", "send_goal", "send_goal_async",
                   "set_parameters", "set_parameters_atomically", "create_service"}
FORBIDDEN_NAMES = {"SwitchController", "LoadController", "UnloadController", "ConfigureController", "ChangeState",
                   "SetParameters", "Twist", "JointTrajectory", "FollowJointTrajectory", "NavigateToPose",
                   "ActionClient"}


def _py_files():
    for d in CODE_DIRS:
        yield from (p for p in d.rglob("*.py") if "migrations" not in p.parts)


def test_no_mutating_ros_calls_in_any_service():
    found = []
    for p in _py_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
                # Hub.publish fans out to WebSocket clients, not ROS: allowed only in studio_api/core.py.
                if not (node.attr == "publish" and p.name == "core.py" and "studio_api" in p.parts):
                    found.append(f"{p.relative_to(ROOT)}:{node.lineno} .{node.attr}")
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name in FORBIDDEN_NAMES:
                        found.append(f"{p.relative_to(ROOT)}:{node.lineno} import {a.name}")
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                found.append(f"{p.relative_to(ROOT)}:{node.lineno} {node.id}")
    assert found == []


def test_service_calls_only_through_the_poll_wrapper():
    uses = []
    for p in _py_files():
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in ("call_async", "call", "create_client"):
                uses.append((p.name, node.attr))
    assert sorted(set(uses)) == [("node.py", "call_async"), ("node.py", "create_client")]


def test_allowlist_contains_only_queries():
    assert allowlist.READ_ONLY_SERVICE_TYPES == {"controller_manager_msgs/srv/ListControllers",
                                                 "lifecycle_msgs/srv/GetState"}
    assert all(t in allowlist.READ_ONLY_SERVICE_TYPES for _, t in allowlist.SERVICES)
    assert not (set(t for t, _ in allowlist.TOPICS.values()) & allowlist.DENIED_TYPES)


@pytest.mark.parametrize("svc,typ", [
    ("/controller_manager/switch_controller", "controller_manager_msgs/srv/SwitchController"),
    ("/controller_manager/list_controllers", "controller_manager_msgs/srv/SwitchController"),
    ("/amcl/change_state", "lifecycle_msgs/srv/ChangeState"),
    ("/lift_guard/set_parameters", "rcl_interfaces/srv/SetParameters"),
    ("/some_random_node/get_state", "lifecycle_msgs/srv/GetState"),
])
def test_denied_services(svc, typ):
    with pytest.raises(allowlist.NotAllowed):
        allowlist.check_service(svc, typ)


@pytest.mark.parametrize("topic,typ", [
    ("/cmd_vel", "geometry_msgs/msg/Twist"),
    ("/lift_controller/joint_trajectory", "trajectory_msgs/msg/JointTrajectory"),
    ("/joint_states", "std_msgs/msg/String"),
    ("/rosout", "rcl_interfaces/msg/Log"),
])
def test_denied_topics(topic, typ):
    with pytest.raises(allowlist.NotAllowed):
        allowlist.check_topic(topic, typ)


def test_allowed_surface():
    allowlist.check_service("/controller_manager/list_controllers", "controller_manager_msgs/srv/ListControllers")
    allowlist.check_service("/bt_navigator/get_state", "lifecycle_msgs/srv/GetState")
    assert allowlist.check_topic("/joint_states", "sensor_msgs/msg/JointState") == "joint_state"


def test_read_only_node_wrapper_refuses_before_touching_ros():
    """Exercise ReadOnlyNode with a fake rclpy node (rclpy itself is not importable here)."""
    import importlib
    import sys
    import types

    fake_rclpy = types.ModuleType("rclpy")
    fake_rclpy.node = types.ModuleType("rclpy.node")
    fake_rclpy.node.Node = object
    fake_rclpy.qos = types.ModuleType("rclpy.qos")
    for n in ("DurabilityPolicy", "QoSProfile", "ReliabilityPolicy"):
        setattr(fake_rclpy.qos, n, object)
    saved = {k: sys.modules.get(k) for k in ("rclpy", "rclpy.node", "rclpy.qos")}
    sys.modules.update({"rclpy": fake_rclpy, "rclpy.node": fake_rclpy.node, "rclpy.qos": fake_rclpy.qos})
    try:
        node_mod = importlib.import_module("studio_ros_adapter.node")
        touched = []
        raw = SimpleNamespace(create_subscription=lambda *a: touched.append(("sub", a[1])),
                              create_client=lambda *a: touched.append(("client", a[1])))
        ro = node_mod.ReadOnlyNode(raw)
        Twist = type("Twist", (), {"__module__": "geometry_msgs.msg._twist"})
        SwitchController = type("SwitchController", (), {"__module__": "controller_manager_msgs.srv._switch_controller"})
        JointState = type("JointState", (), {"__module__": "sensor_msgs.msg._joint_state"})
        with pytest.raises(allowlist.NotAllowed):
            ro.subscribe("/cmd_vel", Twist, lambda m: None, None)
        with pytest.raises(allowlist.NotAllowed):
            ro.query_client("/controller_manager/switch_controller", SwitchController)
        assert touched == []
        ro.subscribe("/joint_states", JointState, lambda m: None, None)
        assert touched == [("sub", "/joint_states")]
        assert not any(hasattr(ro, m) for m in ("publish", "create_publisher", "call", "send_goal"))
    finally:
        sys.modules.pop("studio_ros_adapter.node", None)
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_adapter_http_accepts_get_only():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(SnapshotBuilder("t", None, 0)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert json.load(urllib.request.urlopen(f"{base}/allowlist"))["read_only_service_types"]
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            req = urllib.request.Request(f"{base}/snapshot", data=b"{}", method=method)
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req)
            assert e.value.code == 405
    finally:
        srv.shutdown()


def test_agent_registry_is_read_only():
    assert set(READ_ONLY_TOOLS) == {"evaluate_readiness", "recent_events"}


def test_api_mutating_routes_touch_only_studio_state(tmp_path):
    from studio_api.app import create_app
    from studio_api.settings import Settings
    s = Settings()
    s.database_url = f"sqlite:///{(tmp_path / 'x.db').as_posix()}"
    s.run_loop = False
    app = create_app(s)
    writes = sorted(r.path for r in app.routes if getattr(r, "methods", None) and r.methods - {"GET", "HEAD"})
    assert writes == ["/api/v1/agent/query", "/api/v1/fixtures/select"]
