"""Sources, telemetry buffer, evaluation recording and live fan-out.

Two sources, never mixed:
  FixtureSource  demo mode: a labelled fixture from fixtures/, evaluated at the fixture's own clock.
  LiveSource     live mode: polls the read-only ROS adapter's /snapshot. If the adapter cannot be
                 reached the snapshot says graph_available=false and readiness is ERROR. It never
                 falls back to fixture data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from oar_contracts import (
    ConnectionState, EventRecord, ReadinessEvaluation, Revisions, Severity, Snapshot, SourceMode, Task,
)

from .diagnostics import evaluate
from .settings import Settings
from .store import EvidenceStore

log = logging.getLogger("studio.core")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_trace_id(now: Optional[datetime] = None) -> str:
    now = now or utcnow()
    return f"diag-{now:%Y-%m-%d}-{secrets.token_hex(4)}"


def _parse_t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class FixtureError(KeyError):
    pass


class FixtureSource:
    mode = SourceMode.fixture

    def __init__(self, directory: Path, studio_rev: str, initial: str = "healthy"):
        self.dir = directory
        self.studio_rev = studio_rev
        self.fixtures: dict[str, dict] = {}
        for p in sorted(directory.glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            self.fixtures[d["fixture"]["id"]] = d
        if not self.fixtures:
            raise RuntimeError(f"no fixtures in {directory}")
        self.current = initial if initial in self.fixtures else next(iter(self.fixtures))
        self._frame = 0

    def catalog(self) -> list[dict]:
        return [d["fixture"] | {"active": fid == self.current} for fid, d in self.fixtures.items()]

    def select(self, fid: str) -> dict:
        if fid not in self.fixtures:
            raise FixtureError(fid)
        self.current, self._frame = fid, 0
        return self.fixtures[fid]["fixture"]

    def snapshot(self) -> Snapshot:
        d = self.fixtures[self.current]
        s = Snapshot.model_validate(d["snapshot"])
        s.revisions = Revisions(studio=self.studio_rev, adapter=s.revisions.adapter, robot_stack=s.revisions.robot_stack)
        return s

    def now(self) -> datetime:
        return _parse_t(self.fixtures[self.current]["fixture"]["evaluate_at"])

    def next_frame(self) -> Optional[dict]:
        series = self.fixtures[self.current].get("series") or []
        if not series:
            return None
        f = series[self._frame % len(series)]
        self._frame += 1
        return f | {"replay": True, "fixture_id": self.current}

    def connection(self) -> ConnectionState:
        return ConnectionState(mode=SourceMode.fixture, state="fixture", fixture_id=self.current)


class LiveSource:
    mode = SourceMode.live

    def __init__(self, url: str, studio_rev: str, timeout_s: float = 2.0, client: Optional[httpx.AsyncClient] = None):
        self.url = url.rstrip("/")
        self.studio_rev = studio_rev
        self.client = client or httpx.AsyncClient(timeout=timeout_s)
        self.latest: Optional[Snapshot] = None
        self.state = "reconnecting"
        self.last_ok_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.failures = 0

    async def poll(self) -> bool:
        try:
            r = await self.client.get(f"{self.url}/snapshot")
            r.raise_for_status()
            snap = Snapshot.model_validate(r.json())
        except Exception as e:  # noqa: BLE001 - any failure is reported, never hidden
            self.failures += 1
            self.last_error = f"{type(e).__name__}: {e}"[:300]
            self.state = "disconnected" if self.failures >= 3 else "reconnecting"
            return False
        snap.revisions = Revisions(studio=self.studio_rev, adapter=snap.revisions.adapter,
                                   robot_stack=snap.revisions.robot_stack)
        self.latest, self.failures, self.last_error = snap, 0, None
        self.state, self.last_ok_at = "connected", utcnow()
        return True

    def backoff_s(self, base: float) -> float:
        return min(base * (2 ** min(self.failures, 5)), 10.0) if self.failures else base

    def snapshot(self) -> Snapshot:
        if self.state == "connected" and self.latest is not None:
            return self.latest
        return Snapshot(
            snapshot_id=f"live-unavailable-{secrets.token_hex(3)}", source_mode=SourceMode.live, captured_at=utcnow(),
            graph_available=False,
            graph_error=f"ROS adapter at {self.url} unreachable ({self.last_error or 'no response yet'})",
            revisions=Revisions(studio=self.studio_rev), observations=[])

    def now(self) -> datetime:
        return utcnow()

    def connection(self) -> ConnectionState:
        return ConnectionState(mode=SourceMode.live, state=self.state, adapter_url=self.url,
                               last_ok_at=self.last_ok_at, last_error=self.last_error,
                               consecutive_failures=self.failures)


class Hub:
    """Bounded per-subscriber queues. A slow client loses old messages, never blocks the loop."""

    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self.subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self.subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subs.discard(q)

    def publish(self, msg: dict) -> None:
        for q in list(self.subs):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)


class Studio:
    def __init__(self, settings: Settings, store: EvidenceStore, source):
        self.settings, self.store, self.source = settings, store, source
        self.telemetry: deque[dict] = deque(maxlen=settings.telemetry_buffer)
        self.history: deque[dict] = deque(maxlen=settings.telemetry_buffer)
        self.last_status: dict[str, str] = {}
        self.last_recorded: dict[str, datetime] = {}
        self.last_eval: dict[str, ReadinessEvaluation] = {}
        self._last_js_received: Optional[datetime] = None
        self.hub = Hub()

    # ---------------- evaluation
    def evaluate(self, task: Task | str = Task.overall, *, record: bool = True,
                 trace_id: Optional[str] = None, reason: str = "request") -> ReadinessEvaluation:
        snap = self.source.snapshot()
        now = self.source.now()
        ev = evaluate(snap, task, now, trace_id or new_trace_id(), self.settings.subsystems)
        self.last_eval[ev.task.value] = ev
        if record:
            self._record(ev, snap, reason)
        return ev

    def _record(self, ev: ReadinessEvaluation, snap: Snapshot, reason: str) -> None:
        recorded_at = utcnow()
        self.store.add_evaluation(ev, snap.model_dump(mode="json"), recorded_at)
        self.last_recorded[ev.task.value] = recorded_at
        prev = self.last_status.get(ev.task.value)
        if prev != ev.status.value:
            sev = {"READY": Severity.info, "UNKNOWN": Severity.warning}.get(ev.status.value, Severity.error)
            self.store.add_event(EventRecord(
                at=recorded_at, subsystem=ev.task.value, severity=sev, kind="status_change",
                message=f"{ev.task.value}: {prev or 'none'} -> {ev.status.value}. {ev.summary}",
                trace_id=ev.trace_id, data={"from": prev, "to": ev.status.value, "reason": reason}))
            for c in ev.checks:
                if c.outcome.value != "pass" or c.severity == Severity.warning:
                    self.store.add_event(EventRecord(
                        at=recorded_at, subsystem=c.subsystem, severity=c.severity, kind="diagnostic",
                        message=c.summary, trace_id=ev.trace_id, data={"check": c.id, "outcome": c.outcome.value}))
        self.last_status[ev.task.value] = ev.status.value

    def tick_evaluate(self) -> list[ReadinessEvaluation]:
        """Evaluate overall and each subsystem; record when the status changed or the heartbeat is due."""
        out = []
        for task in [Task.overall, *[Task(s) for s in self.settings.subsystems]]:
            ev = self.evaluate(task, record=False)
            due = (self.last_status.get(task.value) != ev.status.value or task.value not in self.last_recorded
                   or utcnow() - self.last_recorded[task.value] > timedelta(seconds=self.settings.record_heartbeat_s))
            if due:
                self._record(ev, self.source.snapshot(), "tick")
            out.append(ev)
        return out

    # ---------------- telemetry
    def _ingest_live_joint_state(self) -> Optional[dict]:
        snap = self.source.snapshot()
        js = next((o for o in snap.observations if o.kind == "joint_state"), None)
        if js is None or js.received_at == self._last_js_received:
            return None
        self._last_js_received = js.received_at
        return {"t": js.received_at.isoformat(), "stamp": js.stamp.isoformat() if js.stamp else None,
                "replay": False, **{k: js.value.get(k, []) for k in ("name", "position", "velocity")}}

    def push_frame(self, frame: dict) -> None:
        self.telemetry.append(frame)
        self.hub.publish({"type": "telemetry", "frame": frame})

    def connection(self) -> ConnectionState:
        return self.source.connection()

    def event(self, subsystem: str, severity: Severity, kind: str, message: str, data: Optional[dict] = None,
              trace_id: Optional[str] = None) -> None:
        self.store.add_event(EventRecord(at=utcnow(), subsystem=subsystem, severity=severity, kind=kind,
                                         message=message, data=data or {}, trace_id=trace_id))
        self.hub.publish({"type": "event", "kind": kind, "message": message})

    # ---------------- loop
    async def run(self, stop: asyncio.Event) -> None:
        last_conn: Optional[str] = None
        next_eval = 0.0
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            period = self.settings.poll_interval_s
            if isinstance(self.source, LiveSource):
                await self.source.poll()
                period = self.source.backoff_s(self.settings.poll_interval_s)
                frame = self._ingest_live_joint_state()
                if frame:
                    self.push_frame(frame)
            else:
                frame = self.source.next_frame()
                if frame:
                    self.push_frame(frame)
            conn = self.connection()
            if conn.state != last_conn:
                sev = Severity.info if conn.state in ("connected", "fixture") else Severity.warning
                self.event("connection", sev, "connection", f"source {conn.mode.value}: {conn.state}"
                           + (f" ({conn.last_error})" if conn.last_error else ""), conn.model_dump(mode="json"))
                self.hub.publish({"type": "connection", "connection": conn.model_dump(mode="json")})
                last_conn = conn.state
            if loop.time() >= next_eval:
                try:
                    evs = self.tick_evaluate()
                except Exception:  # noqa: BLE001
                    log.exception("evaluation failed")
                    evs = []
                for ev in evs:
                    item = {"task": ev.task.value, "status": ev.status.value, "summary": ev.summary,
                            "trace_id": ev.trace_id, "evaluated_at": ev.evaluated_at.isoformat(), "at": utcnow().isoformat()}
                    if ev.task == Task.overall:
                        self.history.append(item)
                    self.hub.publish({"type": "readiness", **item})
                next_eval = loop.time() + self.settings.eval_interval_s
            try:
                await asyncio.wait_for(stop.wait(), timeout=period)
            except asyncio.TimeoutError:
                pass

    def snapshot_view(self) -> dict[str, Any]:
        """The current snapshot with each observation's freshness at the evaluation time."""
        from .diagnostics import freshness
        snap = self.source.snapshot()
        now = self.source.now()
        obs = []
        for o in snap.observations:
            f = freshness(o, o.kind, now) if o.kind in self._max_age_kinds() else None
            obs.append(o.model_dump(mode="json") | {"freshness": f.model_dump(mode="json") if f else None})
        return snap.model_dump(mode="json", exclude={"observations"}) | {"evaluated_at": now.isoformat(),
                                                                        "observations": obs}

    @staticmethod
    def _max_age_kinds():
        from .profile import MAX_AGE_S
        return MAX_AGE_S
