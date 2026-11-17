"""Read-only HTTP endpoint for the adapter (stdlib only, so nothing is pip-installed into the ROS env).

    source /opt/ros/jazzy/setup.bash && source <overlay>/install/setup.bash
    python3 -m studio_ros_adapter.server --host 127.0.0.1 --port 8765

GET /snapshot   latest allowlisted observations (contract: oar_contracts.Snapshot)
GET /health     liveness, revision, notes
GET /allowlist  the complete ROS surface the adapter may touch
Every other method or path is 404/405: the HTTP side accepts no commands either.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import allowlist
from .snapshot import SnapshotBuilder, iso, utcnow


def _revision() -> str:
    if os.environ.get("ADAPTER_REVISION"):
        return os.environ["ADAPTER_REVISION"]
    try:
        root = Path(__file__).resolve().parents[3]
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=3).stdout.strip() or "unversioned"
    except Exception:  # noqa: BLE001
        return "unversioned"


def make_handler(builder: SnapshotBuilder):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/snapshot":
                self._send(200, builder.build())
            elif self.path == "/health":
                self._send(200, {"ok": True, "revision": builder.adapter_revision, "robot_stack": builder.robot_stack,
                                 "started": iso(builder.started), "now": iso(utcnow()), "notes": builder.notes,
                                 "domain_id": builder.domain_id})
            elif self.path == "/allowlist":
                self._send(200, {"topics": {k: v[0] for k, v in allowlist.TOPICS.items()},
                                 "services": [rx.pattern for rx, _ in allowlist.SERVICES],
                                 "read_only_service_types": sorted(allowlist.READ_ONLY_SERVICE_TYPES)})
            else:
                self._send(404, {"error": {"code": "not_found", "message": self.path}})

        def _refuse(self):
            self._send(405, {"error": {"code": "read_only", "message": "the adapter accepts GET only"}})

        do_POST = do_PUT = do_PATCH = do_DELETE = _refuse  # noqa: N815

        def log_message(self, *a):  # quiet
            pass

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("ADAPTER_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("ADAPTER_PORT", "8765")))
    a = ap.parse_args()
    builder = SnapshotBuilder(_revision(), os.environ.get("ROBOT_STACK_REVISION"),
                              int(os.environ.get("ROS_DOMAIN_ID", "0")))
    stop = threading.Event()
    from .node import spin_forever  # rclpy only here
    t = threading.Thread(target=spin_forever, args=(builder, stop), daemon=True)
    t.start()
    httpd = ThreadingHTTPServer((a.host, a.port), make_handler(builder))
    print(f"studio_ros_adapter serving http://{a.host}:{a.port}/snapshot", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
        t.join(timeout=3)


if __name__ == "__main__":
    main()
