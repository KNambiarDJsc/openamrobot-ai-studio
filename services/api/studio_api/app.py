"""OpenAMRobot AI Studio API.

    uvicorn studio_api.app:create_app --factory --port 8000      # docs at /docs

Read-only with respect to the robot: no endpoint publishes, calls a mutating ROS service or changes a
controller. The only state an endpoint changes is the Studio's own (which demo fixture is shown, the
evidence it records).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from oar_contracts import (
    CONTRACT_VERSION, AgentAnswer, AgentQuery, ConnectionState, ErrorResponse, ReadinessEvaluation, Severity, Task,
)
from studio_agent import Copilot, make_phraser

from .core import FixtureError, FixtureSource, LiveSource, Studio, new_trace_id, utcnow
from .settings import Settings
from .store import EvidenceStore, init_db

log = logging.getLogger("studio.api")

ERRORS = {400: "bad_request", 404: "not_found", 409: "conflict", 422: "validation_error", 503: "unavailable"}


def _err(status: int, code: str, message: str, details: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details,
                                                               "trace_id": None}})


class FixtureSelect(BaseModel):
    fixture_id: str = Field(min_length=1, max_length=64)


class _Tools:
    def __init__(self, studio: Studio):
        self.studio = studio

    def evaluate_readiness(self, task: str, trace_id: str) -> ReadinessEvaluation:
        return self.studio.evaluate(task, record=True, trace_id=trace_id, reason="copilot")

    def recent_events(self, limit: int) -> list[dict[str, Any]]:
        return self.studio.store.list_events(limit=limit)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings()
    engine = init_db(settings.database_url)
    store = EvidenceStore(engine)
    if settings.mode == "live":
        source = LiveSource(settings.adapter_url, settings.studio_revision)
    elif settings.mode == "demo":
        source = FixtureSource(settings.fixtures_dir, settings.studio_revision, settings.initial_fixture)
    else:
        raise RuntimeError(f"STUDIO_MODE must be demo or live, not {settings.mode!r}")
    studio = Studio(settings, store, source)
    copilot = Copilot(_Tools(studio), make_phraser(settings.llm_provider, settings.ollama_url, settings.ollama_model))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        task = asyncio.create_task(studio.run(stop)) if settings.run_loop else None
        yield
        stop.set()
        if task:
            await task

    app = FastAPI(
        title="OpenAMRobot AI Studio API", version=CONTRACT_VERSION, lifespan=lifespan,
        description="Read-only diagnostics over the OpenAMRobot ROS 2 graph. Status vocabulary READY, BLOCKED, "
                    "UNKNOWN, ERROR (RFC Appendix A). Not a safety function.",
        responses={k: {"model": ErrorResponse} for k in (400, 404, 409, 422)})
    app.state.studio, app.state.settings, app.state.copilot = studio, settings, copilot
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                       allow_headers=["*"])

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return _err(exc.status_code, exc.detail.get("code", ERRORS.get(exc.status_code, "error")),
                        exc.detail.get("message", ""), exc.detail.get("details"))
        return _err(exc.status_code, ERRORS.get(exc.status_code, "error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError):
        return _err(422, "validation_error", "request failed schema validation",
                    {"errors": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled")
        return _err(500, "internal_error", f"{type(exc).__name__}: {exc}")

    api = "/api/v1"

    @app.get(f"{api}/health", tags=["meta"])
    def health() -> dict:
        return {"ok": True, "mode": settings.mode, "contract_version": CONTRACT_VERSION,
                "studio_revision": settings.studio_revision, "llm_provider": settings.llm_provider}

    @app.get(f"{api}/status", tags=["robot"])
    def status() -> dict:
        """Connection, mode, per-subsystem status from the latest evaluation and source freshness."""
        conn = studio.connection()
        latest = {t: e for t, e in studio.last_eval.items()}
        if "overall" not in latest:
            latest["overall"] = studio.evaluate(Task.overall, record=False)
        snap = studio.snapshot_view()
        return {
            "connection": conn.model_dump(mode="json"),
            "mode": settings.mode,
            "subsystems_expected": list(settings.subsystems),
            "readiness": {t: {"status": e.status.value, "summary": e.summary, "trace_id": e.trace_id,
                              "evaluated_at": e.evaluated_at.isoformat(), "blocking": e.blocking,
                              "unknown": e.unknown, "warnings": e.warnings} for t, e in latest.items()},
            "snapshot": {k: snap[k] for k in ("snapshot_id", "source_mode", "fixture_id", "captured_at",
                                              "graph_available", "graph_error", "revisions", "evaluated_at")},
            "sources": [{"source": o["source"], "kind": o["kind"], "received_at": o["received_at"],
                         "stamp": o["stamp"], "freshness": o["freshness"]} for o in snap["observations"]],
        }

    @app.get(f"{api}/snapshot", tags=["robot"])
    def snapshot() -> dict:
        """Latest observations with their freshness at the evaluation time."""
        return studio.snapshot_view()

    @app.get(f"{api}/readiness", response_model=ReadinessEvaluation, tags=["readiness"])
    def readiness(task: Task = Task.overall, record: bool = True) -> ReadinessEvaluation:
        """Evaluate now. Recorded in the evidence store unless record=false."""
        return studio.evaluate(task, record=record, reason="api")

    @app.get(f"{api}/connection", response_model=ConnectionState, tags=["meta"])
    def connection() -> ConnectionState:
        return studio.connection()

    @app.get(f"{api}/fixtures", tags=["demo"])
    def fixtures() -> dict:
        if not isinstance(studio.source, FixtureSource):
            return {"mode": settings.mode, "fixtures": []}
        return {"mode": settings.mode, "fixtures": studio.source.catalog()}

    @app.post(f"{api}/fixtures/select", tags=["demo"])
    def select_fixture(body: FixtureSelect) -> dict:
        """Demo mode only: switch which labelled fixture the Studio shows. Touches no robot."""
        if not isinstance(studio.source, FixtureSource):
            raise HTTPException(409, {"code": "not_demo_mode", "message": "fixtures can only be selected in demo mode"})
        try:
            fx = studio.source.select(body.fixture_id)
        except FixtureError:
            raise HTTPException(404, {"code": "unknown_fixture", "message": f"no fixture {body.fixture_id!r}",
                                      "details": {"available": list(studio.source.fixtures)}})
        studio.telemetry.clear()
        studio.event("demo", Severity.info, "fixture", f"fixture selected: {fx['id']} ({fx['title']})", {"fixture": fx})
        evs = studio.tick_evaluate()
        return {"fixture": fx, "readiness": {e.task.value: e.status.value for e in evs}}

    @app.get(f"{api}/evidence/evaluations", tags=["evidence"])
    def list_evaluations(task: Optional[Task] = None,
                         status: Optional[Literal["READY", "BLOCKED", "UNKNOWN", "ERROR"]] = None,
                         subsystem: Optional[str] = Query(None, max_length=64),
                         severity: Optional[Severity] = None, since: Optional[datetime] = None,
                         until: Optional[datetime] = None, limit: int = Query(100, ge=1, le=1000)) -> dict:
        rows = studio.store.list_evaluations(task=task.value if task else None, status=status, subsystem=subsystem,
                                             severity=severity.value if severity else None, since=since, until=until,
                                             limit=limit)
        return {"items": rows, "count": len(rows)}

    @app.get(f"{api}/evidence/evaluations/{{trace_id}}", tags=["evidence"])
    def get_evaluation(trace_id: str) -> dict:
        row = studio.store.get_evaluation(trace_id)
        if row is None:
            raise HTTPException(404, {"code": "unknown_trace", "message": f"no evaluation {trace_id!r}"})
        if not row["tool_calls"] and "." in trace_id:
            row["tool_calls"] = studio.store.list_tool_calls(trace_id=trace_id.split(".")[0])
        return row

    @app.get(f"{api}/evidence/events", tags=["evidence"])
    def list_events(subsystem: Optional[str] = Query(None, max_length=64), severity: Optional[Severity] = None,
                    kind: Optional[str] = Query(None, max_length=32), since: Optional[datetime] = None,
                    until: Optional[datetime] = None, limit: int = Query(200, ge=1, le=1000)) -> dict:
        rows = studio.store.list_events(subsystem=subsystem, severity=severity.value if severity else None,
                                        kind=kind, since=since, until=until, limit=limit)
        return {"items": rows, "count": len(rows)}

    @app.get(f"{api}/evidence/tool-calls", tags=["evidence"])
    def list_tool_calls(trace_id: Optional[str] = Query(None, max_length=80),
                        limit: int = Query(200, ge=1, le=1000)) -> dict:
        rows = studio.store.list_tool_calls(trace_id=trace_id, limit=limit)
        return {"items": rows, "count": len(rows)}

    @app.post(f"{api}/agent/query", response_model=AgentAnswer, tags=["copilot"])
    def agent_query(body: AgentQuery) -> AgentAnswer:
        """Answer a readiness question from deterministic tools. Action requests are refused before any tool runs."""
        trace = new_trace_id()
        ans = copilot.answer(body.question, trace, tuple(settings.subsystems))
        studio.store.add_tool_calls(ans.tool_calls)
        studio.event("copilot", Severity.warning if ans.refused else Severity.info,
                     "refusal" if ans.refused else "copilot",
                     f"{'refused' if ans.refused else ans.intent}: {body.question[:200]}",
                     {"intent": ans.intent, "status": ans.status.value if ans.status else None,
                      "provider": ans.provider}, trace_id=trace)
        return ans

    @app.get(f"{api}/simulation", tags=["robot"])
    def simulation() -> dict:
        """Joint states, TF frames and robot state as observed. Telemetry only; there is no Gazebo view."""
        snap = studio.snapshot_view()
        by_kind: dict[str, list] = {}
        for o in snap["observations"]:
            by_kind.setdefault(o["kind"], []).append(o)
        js = by_kind.get("joint_state", [None])[0]
        tf = by_kind.get("tf", [None])[0]
        ctl = by_kind.get("controllers", [None])[0]
        return {"source_mode": snap["source_mode"], "fixture_id": snap["fixture_id"],
                "graph_available": snap["graph_available"], "evaluated_at": snap["evaluated_at"],
                "joint_state": js, "tf": tf, "controllers": ctl,
                "telemetry": list(studio.telemetry)[-120:],
                "representation": "telemetry-based; not a simulator render"}

    @app.get(f"{api}/telemetry/history", tags=["robot"])
    def telemetry_history(limit: int = Query(300, ge=1, le=5000)) -> dict:
        return {"frames": list(studio.telemetry)[-limit:], "readiness": list(studio.history)[-limit:],
                "buffer_max": studio.telemetry.maxlen}

    @app.websocket(f"{api}/ws/telemetry")
    async def ws_telemetry(ws: WebSocket):
        await ws.accept()
        q = studio.hub.subscribe()
        try:
            await ws.send_json({"type": "hello", "at": utcnow().isoformat(),
                                "connection": studio.connection().model_dump(mode="json"),
                                "buffer_max": studio.hub.maxsize})
            while True:
                msg = await q.get()
                await ws.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            studio.hub.unsubscribe(q)

    return app
