"""rclpy side of the adapter. Imported only where ROS 2 Jazzy is installed.

ReadOnlyNode wraps an rclpy Node and exposes exactly two ROS operations, `subscribe` and
`query_client`, each checked against allowlist.py. The adapter never holds a reference to the raw
node outside this class, and this class has no publisher, action or parameter method.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from . import allowlist, snapshot as S

SERVICE_PERIOD_S = 1.0
SERVICE_TIMEOUT_S = 1.0


class ReadOnlyNode:
    def __init__(self, node: Node):
        self._node = node

    def subscribe(self, topic: str, msg_cls, callback: Callable, qos) -> None:
        type_name = f"{msg_cls.__module__.split('.')[0]}/msg/{msg_cls.__name__}"
        allowlist.check_topic(topic, type_name)
        self._node.create_subscription(msg_cls, topic, callback, qos)

    def query_client(self, service: str, srv_cls):
        type_name = f"{srv_cls.__module__.split('.')[0]}/srv/{srv_cls.__name__}"
        allowlist.check_service(service, type_name)
        return self._node.create_client(srv_cls, service)

    def service_names(self) -> set[str]:
        return {n for n, _ in self._node.get_service_names_and_types()}

    def node_names(self) -> list[str]:
        me = self._node.get_name()
        return [f"{ns.rstrip('/')}/{n}" for n, ns in self._node.get_node_names_and_namespaces() if n != me]

    def timer(self, period: float, cb: Callable) -> None:
        self._node.create_timer(period, cb)

    def log(self, msg: str) -> None:
        self._node.get_logger().info(msg)


class _Poll:
    """One outstanding read-only service call at a time, with a deadline."""

    def __init__(self, source: str, client, request, on_result: Callable[[Any], None], on_error: Callable[[str], None]):
        self.source, self.client, self.request = source, client, request
        self.on_result, self.on_error = on_result, on_error
        self.future = None
        self.deadline = 0.0

    def step(self, advertised: bool) -> None:
        now = time.monotonic()
        if self.future is not None:
            if self.future.done():
                try:
                    self.on_result(self.future.result())
                except Exception as e:  # noqa: BLE001
                    self.on_error(f"{type(e).__name__}: {e}")
                self.future = None
            elif now > self.deadline:
                self.future.cancel()
                self.future = None
                self.on_error(f"timeout after {SERVICE_TIMEOUT_S:.1f} s")
            return
        if advertised:
            self.future = self.client.call_async(self.request)
            self.deadline = now + SERVICE_TIMEOUT_S


class StudioAdapter:
    def __init__(self, builder: S.SnapshotBuilder):
        self.b = builder
        self.node = Node("studio_ros_adapter")
        self.ro = ReadOnlyNode(self.node)
        self.polls: list[_Poll] = []
        self._setup()

    def _setup(self) -> None:
        from diagnostic_msgs.msg import DiagnosticArray
        from sensor_msgs.msg import JointState
        from tf2_msgs.msg import TFMessage

        qos = QoSProfile(depth=10)
        static_qos = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                reliability=ReliabilityPolicy.RELIABLE)
        self.ro.subscribe("/joint_states", JointState,
                          lambda m: self.b.put("/joint_states", "joint_state", S.joint_state(m), S.stamp_to_dt(m.header.stamp)), qos)
        self.ro.subscribe("/diagnostics", DiagnosticArray, self._on_diag, qos)
        self.ro.subscribe("/tf", TFMessage, lambda m: self.b.put_tf(S.tf_frames(m, False)), qos)
        self.ro.subscribe("/tf_static", TFMessage, lambda m: self.b.put_tf(S.tf_frames(m, True)), static_qos)
        try:
            from openamr_nav_msgs.msg import NavigationStatus  # platform-sw / openamrobot-interfaces overlay
            self.ro.subscribe("/navigation/status", NavigationStatus,
                              lambda m: self.b.put("/navigation/status", "navigation_status", S.navigation_status(m),
                                                   S.stamp_to_dt(m.header.stamp)), qos)
        except ImportError:
            self.b.notes.append("openamr_nav_msgs not installed: /navigation/status is not observed")

        from controller_manager_msgs.srv import ListControllers
        src = "/controller_manager/list_controllers"
        self.polls.append(_Poll(src, self.ro.query_client(src, ListControllers), ListControllers.Request(),
                                lambda r: self.b.put(src, "controllers", S.controllers(r)),
                                lambda e: self.b.put(src, "controllers", {"available": True, "error": e})))
        from lifecycle_msgs.srv import GetState
        for n in allowlist.NAV2_MANAGED_NODES:
            s = f"/{n}/get_state"
            self.polls.append(_Poll(s, self.ro.query_client(s, GetState), GetState.Request(),
                                    lambda r, n=n, s=s: self.b.put(s, "lifecycle", S.lifecycle(n, r)),
                                    lambda e, n=n, s=s: self.b.put(s, "lifecycle", {"node": n, "error": e})))
        self.ro.timer(SERVICE_PERIOD_S, self._tick)

    def _on_diag(self, msg) -> None:
        stamp = S.stamp_to_dt(msg.header.stamp)
        for st in msg.status:
            self.b.put("/diagnostics", "diagnostics", S.diagnostic_status(st), stamp, key=st.name)

    def _tick(self) -> None:
        nodes = self.ro.node_names()
        self.b.set_nodes(nodes)
        advertised = self.ro.service_names()
        cm = "/controller_manager/list_controllers"
        if nodes and cm not in advertised:
            self.b.put(cm, "controllers", {"available": False, "controllers": []})
        for p in self.polls:
            p.step(p.source in advertised)


def spin_forever(builder: S.SnapshotBuilder, stop) -> None:
    rclpy.init()
    adapter = StudioAdapter(builder)
    adapter.ro.log(f"studio_ros_adapter up, ROS_DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '0')}")
    try:
        while rclpy.ok() and not stop.is_set():
            rclpy.spin_once(adapter.node, timeout_sec=0.1)
    finally:
        adapter.node.destroy_node()
        rclpy.try_shutdown()
