"""ROS-independent part of the adapter: message conversion and snapshot assembly.

Imports nothing from ROS, so it runs and is tested on any machine. Messages are read by attribute
(duck typing), which works for rclpy messages and for the stand-ins used in tests.
"""
from __future__ import annotations

import math
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Optional

LIFECYCLE_LABELS = {0: "unknown", 1: "unconfigured", 2: "inactive", 3: "active", 4: "finalized"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat().replace("+00:00", "Z") if t else None


def stamp_to_dt(stamp) -> Optional[datetime]:
    """builtin_interfaces/Time -> datetime. Zero stamps (unset) are None. Sim time stays sim time."""
    if stamp is None:
        return None
    sec, nsec = int(getattr(stamp, "sec", 0)), int(getattr(stamp, "nanosec", 0))
    if sec == 0 and nsec == 0:
        return None
    return datetime.fromtimestamp(sec + nsec / 1e9, tz=timezone.utc)


def _f(x) -> Optional[float]:
    x = float(x)
    return x if math.isfinite(x) else None  # JSON has no NaN; null marks a non-finite value


def joint_state(msg) -> dict[str, Any]:
    return {"name": list(msg.name), "position": [_f(p) for p in msg.position],
            "velocity": [_f(v) for v in msg.velocity]}


def diagnostic_status(st) -> dict[str, Any]:
    level = st.level
    level = int.from_bytes(level, "little") if isinstance(level, (bytes, bytearray)) else int(level)
    return {"name": st.name, "hardware_id": st.hardware_id, "level": level, "message": st.message,
            "values": {kv.key: kv.value for kv in st.values}}


def tf_frames(msg, static: bool) -> list[dict[str, Any]]:
    return [{"parent": t.header.frame_id.lstrip("/"), "child": t.child_frame_id.lstrip("/"), "static": static,
             "translation": [_f(t.transform.translation.x), _f(t.transform.translation.y),
                             _f(t.transform.translation.z)]}
            for t in msg.transforms]


def navigation_status(msg) -> dict[str, Any]:
    stack = getattr(msg, "stack", None)
    return {"contract_version": int(msg.contract_version), "profile_id": msg.profile_id,
            "thresholds_id": msg.thresholds_id, "health": int(msg.health),
            "navigation_readiness": int(msg.navigation_readiness),
            "not_ready_reasons": [int(r) for r in msg.not_ready_reasons],
            "active_reasons": [int(r) for r in msg.active_reasons], "sensor_gaps": int(msg.sensor_gaps),
            "stack_state": int(getattr(stack, "state", 0)) if stack is not None else None}


def controllers(response) -> dict[str, Any]:
    return {"available": True, "controllers": [
        {"name": c.name, "state": c.state, "type": c.type} for c in response.controller]}


def lifecycle(node: str, response) -> dict[str, Any]:
    sid = int(response.current_state.id)
    return {"node": node, "state_id": sid, "state_label": response.current_state.label or LIFECYCLE_LABELS.get(sid, "unknown")}


class SnapshotBuilder:
    """Latest observation per (source, key), thread-safe. Bounded: one entry per allowlisted fact."""

    MAX_DIAGNOSTIC_NAMES = 256

    def __init__(self, adapter_revision: str, robot_stack: Optional[str], domain_id: int, graph_timeout_s: float = 3.0):
        self.lock = threading.Lock()
        self.obs: dict[tuple[str, str], dict[str, Any]] = {}
        self.tf: dict[str, dict[str, Any]] = {}
        self.tf_received: Optional[datetime] = None
        self.nodes: list[str] = []
        self.nodes_at: Optional[datetime] = None
        self.started = utcnow()
        self.adapter_revision, self.robot_stack = adapter_revision, robot_stack
        self.domain_id, self.graph_timeout_s = domain_id, graph_timeout_s
        self.notes: list[str] = []

    def put(self, source: str, kind: str, value: dict[str, Any], stamp: Optional[datetime] = None,
            key: str = "", received_at: Optional[datetime] = None) -> None:
        o = {"source": source, "kind": kind, "stamp": iso(stamp), "received_at": iso(received_at or utcnow()),
             "value": value}
        with self.lock:
            if kind == "diagnostics" and (source, key) not in self.obs:
                if sum(1 for k in self.obs if k[0] == source) >= self.MAX_DIAGNOSTIC_NAMES:
                    return
            self.obs[(source, key)] = o

    def put_tf(self, frames: list[dict[str, Any]]) -> None:
        now = utcnow()
        with self.lock:
            for f in frames:
                self.tf[f["child"]] = f
            self.tf_received = now

    def set_nodes(self, nodes: list[str]) -> None:
        with self.lock:
            self.nodes, self.nodes_at = sorted(nodes), utcnow()

    def build(self) -> dict[str, Any]:
        now = utcnow()
        with self.lock:
            observations = list(self.obs.values())
            if self.tf:
                observations.append({"source": "/tf", "kind": "tf", "stamp": None, "received_at": iso(self.tf_received),
                                     "value": {"frames": list(self.tf.values())[:512]}})
            nodes, nodes_at = list(self.nodes), self.nodes_at
        graph_available, graph_error = True, None
        if not nodes:
            waited = (now - self.started).total_seconds()
            graph_available = False
            graph_error = (f"adapter running, no ROS 2 nodes discovered on ROS_DOMAIN_ID {self.domain_id}"
                           + (f" within {self.graph_timeout_s:.1f} s" if waited >= self.graph_timeout_s else
                              " yet (discovery in progress)"))
            observations = []
        else:
            observations.insert(0, {"source": "ros_graph", "kind": "graph", "stamp": None, "received_at": iso(nodes_at),
                                    "value": {"nodes": nodes, "domain_id": self.domain_id}})
        return {"snapshot_id": f"live-{secrets.token_hex(4)}", "source_mode": "live", "fixture_id": None,
                "captured_at": iso(now), "graph_available": graph_available, "graph_error": graph_error,
                "revisions": {"studio": self.adapter_revision, "adapter": self.adapter_revision,
                              "robot_stack": self.robot_stack},
                "observations": observations}
