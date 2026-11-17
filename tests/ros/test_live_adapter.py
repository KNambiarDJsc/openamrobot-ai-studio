"""Opt-in live check of a running adapter (real ROS graph). Skipped unless ADAPTER_URL is set.

    # on the ROS machine: mock.launch.py + `python3 -m studio_ros_adapter.server`
    ADAPTER_URL=http://127.0.0.1:8765 pytest -m ros tests/ros
"""
import os
from datetime import datetime, timezone

import httpx
import pytest

from oar_contracts import Snapshot, Task
from studio_api.diagnostics import evaluate

URL = os.environ.get("ADAPTER_URL")
pytestmark = [pytest.mark.ros, pytest.mark.skipif(not URL, reason="ADAPTER_URL not set: no live ROS graph")]


def test_live_snapshot_matches_contract_and_upper_body_is_ready():
    snap = Snapshot.model_validate(httpx.get(f"{URL}/snapshot", timeout=5).json())
    assert snap.graph_available, snap.graph_error
    ev = evaluate(snap, Task.upper_body, datetime.now(timezone.utc), "diag-live-test")
    assert ev.status.value == "READY", ev.summary


def test_live_adapter_refuses_writes():
    for method in ("POST", "PUT", "DELETE"):
        assert httpx.request(method, f"{URL}/snapshot", timeout=5).status_code == 405
