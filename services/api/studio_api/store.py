"""Evidence storage: readiness evaluations, events and tool-call traces.

SQLAlchemy Core with portable types (String, DateTime(timezone=True), JSON), so the same schema runs
on SQLite (default) and PostgreSQL (set DATABASE_URL=postgresql+psycopg://...). The schema is owned
by Alembic (services/api/migrations); `init_db` runs `alembic upgrade head` on start.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import sqlalchemy as sa

from oar_contracts import EventRecord, ReadinessEvaluation, ToolCall

metadata = sa.MetaData()

evaluations = sa.Table(
    "evaluations", metadata,
    sa.Column("trace_id", sa.String(64), primary_key=True),
    sa.Column("task", sa.String(32), nullable=False, index=True),
    sa.Column("status", sa.String(16), nullable=False, index=True),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source_mode", sa.String(16), nullable=False),
    sa.Column("fixture_id", sa.String(64)),
    sa.Column("studio_revision", sa.String(64), nullable=False),
    sa.Column("summary", sa.Text, nullable=False),
    sa.Column("subsystems", sa.JSON, nullable=False),
    sa.Column("severity", sa.String(16), nullable=False, index=True),
    sa.Column("body", sa.JSON, nullable=False),
    sa.Column("snapshot", sa.JSON, nullable=False),
)

events = sa.Table(
    "events", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("subsystem", sa.String(64), nullable=False, index=True),
    sa.Column("severity", sa.String(16), nullable=False, index=True),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("message", sa.Text, nullable=False),
    sa.Column("trace_id", sa.String(64), index=True),
    sa.Column("data", sa.JSON, nullable=False),
)

tool_calls = sa.Table(
    "tool_calls", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("trace_id", sa.String(64), nullable=False, index=True),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("tool", sa.String(64), nullable=False),
    sa.Column("args", sa.JSON, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("result_summary", sa.Text, nullable=False),
)

_SEV_RANK = {"info": 0, "warning": 1, "error": 2}


def _utc(t: Optional[datetime]) -> Optional[datetime]:
    if t is None:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _api_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def init_db(url: str) -> sa.Engine:
    from alembic import command
    from alembic.config import Config

    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(_api_dir() / "alembic.ini"))
    cfg.set_main_option("script_location", str(_api_dir() / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return sa.create_engine(url, future=True)


class EvidenceStore:
    def __init__(self, engine: sa.Engine):
        self.engine = engine

    # -------- writes
    def add_evaluation(self, ev: ReadinessEvaluation, snapshot: dict[str, Any], recorded_at: datetime) -> None:
        sev = max((c.severity.value for c in ev.checks), key=_SEV_RANK.get, default="info")
        with self.engine.begin() as cx:
            cx.execute(evaluations.insert().values(
                trace_id=ev.trace_id, task=ev.task.value, status=ev.status.value, evaluated_at=ev.evaluated_at,
                recorded_at=recorded_at, source_mode=ev.source_mode.value, fixture_id=ev.fixture_id,
                studio_revision=ev.revisions.studio, summary=ev.summary,
                subsystems=sorted({c.subsystem for c in ev.checks}), severity=sev,
                body=ev.model_dump(mode="json"), snapshot=snapshot))

    def add_event(self, e: EventRecord) -> int:
        with self.engine.begin() as cx:
            r = cx.execute(events.insert().values(
                at=e.at, subsystem=e.subsystem, severity=e.severity.value, kind=e.kind, message=e.message,
                trace_id=e.trace_id, data=e.data))
            return int(r.inserted_primary_key[0])

    def add_tool_calls(self, calls: list[ToolCall]) -> None:
        if not calls:
            return
        with self.engine.begin() as cx:
            cx.execute(tool_calls.insert(), [c.model_dump(mode="python") | {"outcome": c.outcome} for c in calls])

    # -------- reads
    def list_evaluations(self, *, task=None, status=None, subsystem=None, severity=None,
                         since=None, until=None, limit=100) -> list[dict]:
        q = sa.select(evaluations.c.trace_id, evaluations.c.task, evaluations.c.status, evaluations.c.evaluated_at,
                      evaluations.c.recorded_at, evaluations.c.source_mode, evaluations.c.fixture_id,
                      evaluations.c.studio_revision, evaluations.c.summary, evaluations.c.subsystems,
                      evaluations.c.severity)
        if task:
            q = q.where(evaluations.c.task == task)
        if status:
            q = q.where(evaluations.c.status == status)
        if severity:
            q = q.where(evaluations.c.severity.in_([s for s, r in _SEV_RANK.items() if r >= _SEV_RANK[severity]]))
        if since:
            q = q.where(evaluations.c.recorded_at >= _utc(since))
        if until:
            q = q.where(evaluations.c.recorded_at <= _utc(until))
        q = q.order_by(evaluations.c.recorded_at.desc()).limit(limit if not subsystem else max(limit * 5, 500))
        with self.engine.connect() as cx:
            rows = [dict(r._mapping) for r in cx.execute(q)]
        if subsystem:  # JSON containment differs between SQLite and Postgres; filter portably
            rows = [r for r in rows if subsystem in (r["subsystems"] or [])][:limit]
        return rows

    def get_evaluation(self, trace_id: str) -> Optional[dict]:
        with self.engine.connect() as cx:
            r = cx.execute(sa.select(evaluations).where(evaluations.c.trace_id == trace_id)).first()
            if r is None:
                return None
            calls = cx.execute(sa.select(tool_calls).where(tool_calls.c.trace_id == trace_id)
                               .order_by(tool_calls.c.seq)).all()
        d = dict(r._mapping)
        d["tool_calls"] = [dict(c._mapping) for c in calls]
        return d

    def list_events(self, *, subsystem=None, severity=None, kind=None, since=None, until=None,
                    limit=200) -> list[dict]:
        q = sa.select(events)
        if subsystem:
            q = q.where(events.c.subsystem == subsystem)
        if severity:
            q = q.where(events.c.severity.in_([s for s, r in _SEV_RANK.items() if r >= _SEV_RANK[severity]]))
        if kind:
            q = q.where(events.c.kind == kind)
        if since:
            q = q.where(events.c.at >= _utc(since))
        if until:
            q = q.where(events.c.at <= _utc(until))
        q = q.order_by(events.c.at.desc(), events.c.id.desc()).limit(limit)
        with self.engine.connect() as cx:
            return [dict(r._mapping) for r in cx.execute(q)]

    def list_tool_calls(self, *, trace_id=None, limit=200) -> list[dict]:
        q = sa.select(tool_calls)
        if trace_id:
            q = q.where(tool_calls.c.trace_id == trace_id)
        q = q.order_by(tool_calls.c.started_at.desc(), tool_calls.c.seq).limit(limit)
        with self.engine.connect() as cx:
            return [dict(r._mapping) for r in cx.execute(q)]
