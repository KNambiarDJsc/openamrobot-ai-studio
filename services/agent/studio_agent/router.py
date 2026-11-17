"""Deterministic diagnostics copilot.

question -> refusal check -> intent -> read-only tool calls -> answer built from the evaluations.

The refusal check runs before any tool is called, so an action request has no ROS side effect and
leaves exactly one tool-call record: the refusal. The tool registry contains read operations only
(tests/test_read_only.py checks the names and that no tool can reach a publisher).

The text of every answer is assembled from ReadinessEvaluation fields: status, check summaries,
sources, receive times, ages and the trace id. Nothing in it is generated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from oar_contracts import AgentAnswer, ReadinessEvaluation, Task, ToolCall

# Verbs that are unambiguous as the first word of a sentence ("Stop the arm", "Activate lift_controller").
IMPERATIVE_VERBS = (
    "move|drive|go|navigate|raise|lower|activate|deactivate|switch|start|stop|halt|publish|send|command|set|"
    "enable|disable|spawn|kill|restart|reset|reboot|open|close|grip|grasp|release|cancel|execute|trigger|rotate|"
    "configure|shutdown|teleop|undock|lift\\s+(?:the|it|up|down|to)"
)
# Any of these after "can you", "please", "I want you to" ... ("Can you dock?", "please run the trajectory").
REQUEST_VERBS = IMPERATIVE_VERBS + "|lift|dock|park|home|turn|load|unload|run|cleanup|drive"
_SENTENCE_RE = re.compile(
    rf"^\s*(?:(?:please|now|then|and|also|next|ok|okay|after\s+that|so)\b,?\s+)*(?:{IMPERATIVE_VERBS})\b", re.I)
_ACTION_RE = [
    re.compile(rf"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:{REQUEST_VERBS})\b", re.I),
    re.compile(rf"\bplease\s+(?:{REQUEST_VERBS})\b", re.I),
    re.compile(rf"\b(?:i\s+want\s+you\s+to|go\s+ahead\s+and|make\s+(?:it|the\s+robot))\s+(?:{REQUEST_VERBS})\b", re.I),
    re.compile(r"cmd_vel|/cmd\b|switch_controller|set_parameters|follow_joint_trajectory|/_action/send_goal", re.I),
]

INTENTS: list[tuple[str, re.Pattern]] = [
    ("navigation", re.compile(r"navigat|nav2|\bnav\b|amcl|planner|bt_navigator|lifecycle|locali[sz]|map_server|collision", re.I)),
    ("upper_body", re.compile(r"\barms?\b|gripper|\blift\b|controller|joint|manipulat|upper.?body|openarm|ros2_control", re.I)),
    ("diagnostics", re.compile(r"diagnostic|warning|warn\b|fault|health|error", re.I)),
    ("freshness", re.compile(r"stale|fresh|old|latency|last update|timestamp|age\b", re.I)),
    ("overall", re.compile(r"ready|readiness|status|block|why|state|ok\b|healthy|problem|wrong", re.I)),
]

READ_ONLY_TOOLS = ("evaluate_readiness", "recent_events")


class Tools(Protocol):
    def evaluate_readiness(self, task: str, trace_id: str) -> ReadinessEvaluation: ...
    def recent_events(self, limit: int) -> list[dict[str, Any]]: ...


def is_action_request(q: str) -> bool:
    if any(r.search(q) for r in _ACTION_RE):
        return True
    return any(_SENTENCE_RE.search(s) for s in re.split(r"[.?!;\n]+", q))


def classify(q: str) -> str:
    if is_action_request(q):
        return "action_request"
    for name, rx in INTENTS:
        if rx.search(q):
            return name
    return "unsupported"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_time(t) -> str:
    if t is None:
        return "never received"
    s = t if isinstance(t, str) else t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return s


def _evidence_line(c) -> str:
    e = c.evidence[0] if c.evidence else None
    if e is None:
        return f"- [{c.outcome.value}] {c.summary}"
    age = f"age {e.freshness.age_s:.2f} s" if e.freshness.age_s is not None else "no observation"
    return (f"- [{c.outcome.value}] {c.summary} (source {e.source}, received {_fmt_time(e.observed_at)}, "
            f"{age}, {e.freshness.result.value} within {e.freshness.max_age_s:g} s)")


def render(ev: ReadinessEvaluation, focus: Optional[str] = None, limit: int = 8) -> str:
    checks = ev.checks
    # A focus narrows the passing checks shown; anything that fails or is undecided is always shown.
    not_ok = [c for c in checks if c.outcome.value != "pass"]
    if focus == "diagnostics":
        checks = not_ok + [c for c in checks if c.subsystem == "diagnostics" and c not in not_ok] or checks
    elif focus == "freshness":
        stale = [c for c in checks if c.evidence and c.evidence[0].freshness.result.value != "fresh"]
        checks = not_ok + [c for c in stale if c not in not_ok] or checks
    # Failures and unknowns first: they are what the question is usually about.
    order = {"error": 0, "fail": 1, "unknown": 2, "pass": 3}
    checks = sorted(checks, key=lambda c: (order[c.outcome.value], c.severity.value != "warning"))
    shown = checks[:limit]
    lines = [f"{ev.status.value}: {ev.summary}"]
    lines += [_evidence_line(c) for c in shown]
    if len(checks) > len(shown):
        lines.append(f"- ... {len(checks) - len(shown)} more checks in the trace")
    nxt = next((c.next_check for c in shown if c.next_check), None)
    if nxt:
        lines.append(f"Next check: {nxt}")
    src = f"fixture '{ev.fixture_id}' (demo data)" if ev.source_mode.value == "fixture" else "live ROS adapter"
    lines.append(f"Source: {src}; evaluated at {_fmt_time(ev.evaluated_at)}; policy {ev.policy_version}; "
                 f"studio {ev.revisions.studio}; adapter {ev.revisions.adapter or 'n/a'}.")
    lines.append(f"Trace: {ev.trace_id}")
    return "\n".join(lines)


@dataclass
class Copilot:
    tools: Tools
    phrase: Optional[Callable[[str, str], tuple[Optional[str], str]]] = None  # (question, text) -> (model_text, provider)

    def answer(self, question: str, trace_id: str, subsystems: tuple[str, ...] = ("upper_body", "navigation")) -> AgentAnswer:
        calls: list[ToolCall] = []
        seq = 0

        def call(tool: str, args: dict, fn: Callable[[], Any], summarize: Callable[[Any], str]):
            nonlocal seq
            if tool not in READ_ONLY_TOOLS:
                raise PermissionError(tool)
            seq += 1
            t0 = _now()
            try:
                r = fn()
            except Exception as e:  # noqa: BLE001
                calls.append(ToolCall(trace_id=trace_id, seq=seq, tool=tool, args=args, started_at=t0,
                                      finished_at=_now(), outcome="error", result_summary=f"{type(e).__name__}: {e}"))
                raise
            calls.append(ToolCall(trace_id=trace_id, seq=seq, tool=tool, args=args, started_at=t0, finished_at=_now(),
                                  outcome="ok", result_summary=summarize(r)))
            return r

        intent = classify(question)
        if intent == "action_request":
            t = _now()
            calls.append(ToolCall(trace_id=trace_id, seq=1, tool="refuse", args={"question": question}, started_at=t,
                                  finished_at=t, outcome="refused",
                                  result_summary="action request refused before any tool call; no ROS side effect"))
            text = ("REFUSED: AI Studio is read-only. It cannot move, command, switch or configure anything on the "
                    "robot, and it has no tool that publishes, calls a mutating service or changes a controller. "
                    "Motion authority stays with the ROS 2 controllers, guards and operators. Ask about readiness, "
                    f"controllers, navigation status or diagnostics instead.\nTrace: {trace_id}")
            return AgentAnswer(trace_id=trace_id, question=question, intent=intent, status=None, refused=True,
                               text=text, evaluations=[], tool_calls=calls, provider="deterministic")
        if intent == "unsupported":
            text = ("UNKNOWN: that is outside the evidence AI Studio collects. It observes ROS graph presence, "
                    "controller_manager's controllers, /joint_states, /tf, /navigation/status, Nav2 lifecycle "
                    "states and /diagnostics. Try: 'Is the robot ready?', 'Why is navigation blocked?', "
                    f"'Are the arm controllers active?', 'Is any telemetry stale?'\nTrace: {trace_id}")
            return AgentAnswer(trace_id=trace_id, question=question, intent=intent, status=None, refused=False,
                               text=text, evaluations=[], tool_calls=calls, provider="deterministic")

        task = {"navigation": Task.navigation, "upper_body": Task.upper_body}.get(intent, Task.overall)
        n = 0

        def ev_for(tk: Task) -> ReadinessEvaluation:
            nonlocal n
            n += 1
            sub_trace = f"{trace_id}.{n}"
            return call("evaluate_readiness", {"task": tk.value, "trace_id": sub_trace},
                        lambda: self.tools.evaluate_readiness(tk.value, sub_trace),
                        lambda e: f"{e.task.value}: {e.status.value} ({len(e.checks)} checks, trace {e.trace_id})")

        evs = [ev_for(task)]
        if intent == "diagnostics":
            call("recent_events", {"limit": 5}, lambda: self.tools.recent_events(5),
                 lambda rows: f"{len(rows)} recent events")
        text = render(evs[0], focus=intent if intent in ("diagnostics", "freshness") else None)
        provider, model_text = "deterministic", None
        if self.phrase is not None:
            model_text, provider = self.phrase(question, text)
        return AgentAnswer(trace_id=trace_id, question=question, intent=intent, status=evs[0].status, refused=False,
                           text=text, evaluations=evs, tool_calls=calls, provider=provider, model_text=model_text)
