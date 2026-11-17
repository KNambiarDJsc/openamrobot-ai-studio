"""Copilot intent routing, refusal before side effects, and the LLM output guard."""
import httpx
import pytest

from conftest import load_fixture
from studio_agent import Copilot, classify, is_action_request, validate
from studio_agent.providers import make_phraser, ollama_phraser
from studio_api.diagnostics import evaluate


@pytest.mark.parametrize("q", [
    "Please lift the arm up", "Move the base forward 1 m", "Can you activate lift_controller?",
    "could you dock the robot", "Stop the left arm", "Publish a zero twist on /cmd_vel",
    "Is it ready? Then navigate to the kitchen.", "I want you to raise the lift", "call switch_controller",
    "Reset the controller manager", "Cancel the current navigation goal", "please run the trajectory",
])
def test_action_requests_are_refused(q):
    assert is_action_request(q) and classify(q) == "action_request"


@pytest.mark.parametrize("q,intent", [
    ("Is the simulated robot ready for a navigation task?", "navigation"),
    ("Which subsystem is blocking it?", "overall"),
    ("Why did the lift stop?", "upper_body"),
    ("Are the arm controllers active?", "upper_body"),
    ("Run diagnostics", "diagnostics"),
    ("Dock status?", "overall"),
    ("Is any telemetry stale?", "freshness"),
    ("Any diagnostic warnings?", "diagnostics"),
    ("What's the weather in Berlin?", "unsupported"),
])
def test_read_questions_are_not_refused(q, intent):
    assert classify(q) == intent


class Tools:
    def __init__(self, fid):
        self.snap, self.now, _ = load_fixture(fid)
        self.calls = []

    def evaluate_readiness(self, task, trace_id):
        self.calls.append(("evaluate_readiness", task))
        return evaluate(self.snap, task, self.now, trace_id)

    def recent_events(self, limit):
        self.calls.append(("recent_events", limit))
        return []


def test_refusal_happens_before_any_tool_call():
    t = Tools("healthy")
    a = Copilot(t).answer("Raise the lift to L1350", "diag-2026-11-17-aaaa0001")
    assert a.refused and t.calls == [] and a.evaluations == []
    assert [c.tool for c in a.tool_calls] == ["refuse"] and a.tool_calls[0].outcome == "refused"


def test_answer_cites_status_sources_times_and_trace():
    t = Tools("stale_telemetry")
    a = Copilot(t).answer("Is any telemetry stale?", "diag-2026-11-17-aaaa0002")
    assert a.status.value == "UNKNOWN"
    assert "source /joint_states" in a.text and "age 4.20 s" in a.text and "stale within 1 s" in a.text
    assert "Trace: diag-2026-11-17-aaaa0002.1" in a.text and "fixture 'stale_telemetry' (demo data)" in a.text


def test_missing_graph_answer_is_error_with_next_check():
    a = Copilot(Tools("missing_graph")).answer("Is the robot ready?", "diag-2026-11-17-aaaa0003")
    assert a.status.value == "ERROR" and "Next check:" in a.text


def test_unsupported_question_says_unknown_and_calls_nothing():
    t = Tools("healthy")
    a = Copilot(t).answer("How much battery is left?", "diag-2026-11-17-aaaa0004")
    assert a.text.startswith("UNKNOWN") and t.calls == [] and not a.refused


DET = ("BLOCKED: Upper body: BLOCKED by controllers. lift_controller is inactive, not active\n"
       "- [fail] lift_controller is inactive (received 2026-11-17T20:41:11.384Z, age 0.80 s)\n"
       "Trace: diag-2026-11-17-abcd1234.1")


@pytest.mark.parametrize("text,ok", [
    ("BLOCKED: lift_controller is inactive (age 0.80 s). Trace diag-2026-11-17-abcd1234.1", True),
    ("READY: everything is fine. Trace diag-2026-11-17-abcd1234.1", False),           # status changed
    ("BLOCKED: lift_controller is inactive.", False),                                 # trace dropped
    ("BLOCKED: lift at 0.35 m is inactive. Trace diag-2026-11-17-abcd1234.1", False),  # invented number
    ("", False),
])
def test_llm_output_guard(text, ok):
    assert validate(text, DET) is ok


def _ollama(reply: str | None):
    def handler(request: httpx.Request):
        if reply is None:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"message": {"role": "assistant", "content": reply}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_phrasing_accepted_only_when_faithful():
    good = ollama_phraser("http://o", "m", client=_ollama("BLOCKED: lift_controller is inactive. Trace diag-2026-11-17-abcd1234.1"))
    assert good("q", DET) == ("BLOCKED: lift_controller is inactive. Trace diag-2026-11-17-abcd1234.1", "ollama")
    bad = ollama_phraser("http://o", "m", client=_ollama("READY. Trace diag-2026-11-17-abcd1234.1"))
    assert bad("q", DET) == (None, "deterministic")
    down = ollama_phraser("http://o", "m", client=_ollama(None))
    assert down("q", DET) == (None, "deterministic")


def test_phrasing_never_replaces_the_deterministic_answer():
    phr = ollama_phraser("http://o", "m", client=_ollama("UNKNOWN: telemetry is old. Trace diag-2026-11-17-aaaa0005.1"))
    a = Copilot(Tools("stale_telemetry"), phrase=phr).answer("Is any telemetry stale?", "diag-2026-11-17-aaaa0005")
    assert a.provider == "ollama" and a.model_text.startswith("UNKNOWN") and a.text.startswith("UNKNOWN: Robot")


def test_provider_config_errors():
    assert make_phraser("none", "", "") is None
    with pytest.raises(RuntimeError):
        make_phraser("ollama", "http://o", "")
    with pytest.raises(RuntimeError):
        make_phraser("gpt", "http://o", "m")
    try:
        import strands  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="strands-agents"):
            make_phraser("strands", "http://o", "m")
