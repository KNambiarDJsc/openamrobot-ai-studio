"""API contracts, structured errors, evidence filters, WebSocket and live-mode failure handling."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from oar_contracts import AgentAnswer, ConnectionState, ReadinessEvaluation, Snapshot
from studio_api.app import create_app
from studio_api.core import LiveSource
from studio_api.settings import Settings


def make_client(tmp_path, **kw) -> TestClient:
    s = Settings()
    s.database_url = f"sqlite:///{(tmp_path / 'studio.db').as_posix()}"
    s.studio_revision = "test-rev"
    s.run_loop = kw.pop("run_loop", False)
    for k, v in kw.items():
        setattr(s, k, v)
    return TestClient(create_app(s))


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def test_health_and_openapi(client):
    h = client.get("/api/v1/health").json()
    assert h["ok"] and h["mode"] == "demo" and h["studio_revision"] == "test-rev"
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/status", "/api/v1/readiness", "/api/v1/evidence/evaluations", "/api/v1/agent/query",
              "/api/v1/simulation", "/api/v1/fixtures/select"):
        assert p in paths


def test_readiness_matches_contract_and_is_recorded(client):
    r = client.get("/api/v1/readiness", params={"task": "upper_body"})
    ev = ReadinessEvaluation.model_validate(r.json())
    assert ev.status.value == "READY" and ev.revisions.studio == "test-rev" and ev.source_mode.value == "fixture"
    row = client.get(f"/api/v1/evidence/evaluations/{ev.trace_id}").json()
    assert row["status"] == "READY" and row["snapshot"]["fixture_id"] == "healthy"
    assert row["body"]["trace_id"] == ev.trace_id


def test_record_false_does_not_store(client):
    tid = client.get("/api/v1/readiness", params={"record": False}).json()["trace_id"]
    assert client.get(f"/api/v1/evidence/evaluations/{tid}").status_code == 404


def test_status_lists_sources_with_freshness(client):
    s = client.get("/api/v1/status").json()
    assert s["connection"]["state"] == "fixture"
    assert s["readiness"]["overall"]["status"] == "READY"
    kinds = {x["kind"] for x in s["sources"]}
    assert {"joint_state", "controllers", "navigation_status", "graph"} <= kinds
    assert all(x["freshness"]["result"] == "fresh" for x in s["sources"] if x["freshness"])


def test_fixture_switch_changes_readiness_and_logs_events(client):
    r = client.post("/api/v1/fixtures/select", json={"fixture_id": "missing_graph"}).json()
    assert r["readiness"]["overall"] == "ERROR"
    ev = client.get("/api/v1/events" if False else "/api/v1/evidence/events", params={"kind": "fixture"}).json()
    assert ev["items"][0]["message"].startswith("fixture selected: missing_graph")
    changes = client.get("/api/v1/evidence/events", params={"kind": "status_change"}).json()["items"]
    assert any("-> ERROR" in e["message"] for e in changes)


def test_evidence_filters(client):
    for fid in ("healthy", "inactive_controller", "stale_telemetry", "healthy"):
        client.post("/api/v1/fixtures/select", json={"fixture_id": fid})
    get = lambda **p: client.get("/api/v1/evidence/evaluations", params=p).json()["items"]  # noqa: E731
    assert get(status="BLOCKED") and all(r["status"] == "BLOCKED" for r in get(status="BLOCKED"))
    assert all(r["task"] == "navigation" for r in get(task="navigation"))
    assert all("navigation" in r["subsystems"] for r in get(subsystem="navigation"))
    assert all(r["severity"] == "error" for r in get(severity="error"))
    assert {r["severity"] for r in get(severity="warning")} <= {"warning", "error"}
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert get(since=future) == []
    assert len(get(limit=2)) == 2
    errs = client.get("/api/v1/evidence/events", params={"severity": "error"}).json()["items"]
    assert errs and all(e["severity"] == "error" for e in errs)


@pytest.mark.parametrize("req,code,err", [
    (("post", "/api/v1/fixtures/select", {"fixture_id": "nope"}), 404, "unknown_fixture"),
    (("post", "/api/v1/agent/query", {"question": ""}), 422, "validation_error"),
    (("post", "/api/v1/agent/query", {"question": "x", "extra": 1}), 422, "validation_error"),
    (("get", "/api/v1/readiness?task=arms", None), 422, "validation_error"),
    (("get", "/api/v1/evidence/evaluations?limit=0", None), 422, "validation_error"),
    (("get", "/api/v1/evidence/evaluations/diag-none", None), 404, "unknown_trace"),
])
def test_structured_errors(client, req, code, err):
    method, url, body = req
    r = client.request(method, url, json=body)
    assert r.status_code == code
    j = r.json()
    assert set(j) == {"error"} and j["error"]["code"] == err and j["error"]["message"]


def test_agent_answer_cites_trace_and_records_tool_calls(client):
    client.post("/api/v1/fixtures/select", json={"fixture_id": "inactive_controller"})
    a = AgentAnswer.model_validate(client.post("/api/v1/agent/query", json={"question": "Why is the lift blocked?"}).json())
    assert a.status.value == "BLOCKED" and a.trace_id in a.text and "lift_controller" in a.text
    assert "received 2026-11-17T20:41:11" in a.text  # cites the observed receive time
    calls = client.get("/api/v1/evidence/tool-calls", params={"trace_id": a.trace_id}).json()["items"]
    assert [c["tool"] for c in calls] == ["evaluate_readiness"]
    sub = a.evaluations[0].trace_id
    assert sub.startswith(a.trace_id + ".")
    detail = client.get(f"/api/v1/evidence/evaluations/{sub}").json()
    assert detail["tool_calls"][0]["trace_id"] == a.trace_id


def test_simulation_view_is_labelled_telemetry(client):
    s = client.get("/api/v1/simulation").json()
    assert s["representation"].startswith("telemetry-based")
    assert "lift_joint" in s["joint_state"]["value"]["name"]


def test_websocket_streams_replay_telemetry(tmp_path):
    with make_client(tmp_path, run_loop=True, poll_interval_s=0.05, eval_interval_s=0.05) as c:
        with c.websocket_connect("/api/v1/ws/telemetry") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["connection"]["state"] == "fixture"
            seen = set()
            for _ in range(40):
                m = ws.receive_json()
                seen.add(m["type"])
                if m["type"] == "telemetry":
                    assert m["frame"]["replay"] is True and m["frame"]["fixture_id"] == "healthy"
                if {"telemetry", "readiness"} <= seen:
                    break
            assert {"telemetry", "readiness"} <= seen


def test_hub_is_bounded():
    from studio_api.core import Hub
    h = Hub(maxsize=3)
    q = h.subscribe()
    for i in range(10):
        h.publish({"i": i})
    assert q.qsize() == 3 and q.get_nowait()["i"] == 7


# ---------------------------------------------------------------- live mode

def test_live_mode_adapter_down_is_error_never_fixture(tmp_path):
    with make_client(tmp_path, mode="live", adapter_url="http://127.0.0.1:9") as c:
        ev = c.get("/api/v1/readiness").json()
        assert ev["status"] == "ERROR" and ev["source_mode"] == "live" and ev["fixture_id"] is None
        assert "unreachable" in ev["summary"]
        assert c.get("/api/v1/fixtures").json()["fixtures"] == []
        r = c.post("/api/v1/fixtures/select", json={"fixture_id": "healthy"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_demo_mode"


def _adapter_transport(snapshot: dict, fail: list):
    def handler(request: httpx.Request):
        if fail and fail[0]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=snapshot)
    return httpx.MockTransport(handler)


def test_live_source_reconnects_with_backoff(fixture_loader):
    snap, _, d = fixture_loader("healthy")
    body = d["snapshot"] | {"source_mode": "live", "fixture_id": None}
    fail = [True]
    src = LiveSource("http://adapter", "rev", client=httpx.AsyncClient(transport=_adapter_transport(body, fail)))

    async def go():
        for _ in range(3):
            assert await src.poll() is False
        assert src.connection().state == "disconnected" and src.backoff_s(0.5) > 0.5
        assert src.snapshot().graph_available is False
        fail[0] = False
        assert await src.poll() is True
        c = ConnectionState.model_validate(src.connection().model_dump())
        assert c.state == "connected" and c.consecutive_failures == 0 and src.backoff_s(0.5) == 0.5
        assert Snapshot.model_validate(src.snapshot().model_dump()).graph_available
    asyncio.run(go())


def test_live_source_rejects_malformed_snapshot():
    bad = {"snapshot_id": "x", "source_mode": "live"}  # missing required fields
    src = LiveSource("http://adapter", "rev", client=httpx.AsyncClient(transport=_adapter_transport(bad, [False])))
    assert asyncio.run(src.poll()) is False
    assert "ValidationError" in src.last_error
    assert src.snapshot().graph_available is False
