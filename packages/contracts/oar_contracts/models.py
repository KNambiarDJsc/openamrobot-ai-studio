"""Shared typed contracts for OpenAMRobot AI Studio.

These models are the source of truth. `scripts/gen_contracts.py` exports them to
`packages/contracts/schema/contracts.schema.json` and `packages/contracts/ts/generated.ts`,
and a test fails if either file is out of date.

Vocabulary follows RFC Appendix A: READY, BLOCKED, UNKNOWN, ERROR. Every evidence record
carries a source, an observation time, a freshness decision, a software revision and a trace id.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Readiness(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class FreshnessResult(StrEnum):
    fresh = "fresh"
    stale = "stale"
    missing = "missing"


class CheckOutcome(StrEnum):
    passed = "pass"
    failed = "fail"
    unknown = "unknown"
    error = "error"


class SourceMode(StrEnum):
    live = "live"
    fixture = "fixture"


class Revisions(_Model):
    studio: str = Field(description="Git revision of AI Studio")
    adapter: Optional[str] = Field(default=None, description="Revision reported by the ROS adapter")
    robot_stack: Optional[str] = Field(default=None, description="Robot stack revision, if the adapter or fixture reports one")


class Observation(_Model):
    """One allowlisted fact as received from the ROS graph (or recorded in a fixture)."""

    source: str = Field(description="Allowlisted topic, service or graph query, e.g. /joint_states")
    kind: str = Field(description="joint_state | controllers | diagnostics | tf | navigation_status | lifecycle | graph")
    stamp: Optional[datetime] = Field(default=None, description="Header stamp of the message, in the publisher's clock (sim time in Gazebo)")
    received_at: datetime = Field(description="Wall-clock time the adapter received or queried it; freshness is judged on this")
    value: dict[str, Any] = Field(description="Typed message content, units preserved in key names")


class Snapshot(_Model):
    snapshot_id: str
    source_mode: SourceMode
    fixture_id: Optional[str] = None
    captured_at: datetime = Field(description="Wall-clock time the snapshot was assembled")
    graph_available: bool
    graph_error: Optional[str] = None
    revisions: Revisions
    observations: list[Observation]


class Freshness(_Model):
    age_s: Optional[float] = Field(description="Seconds since received_at at evaluation time; null when missing")
    max_age_s: float
    result: FreshnessResult


class EvidenceRecord(_Model):
    """RFC A.2 evidence record."""

    source: str
    observed_at: Optional[datetime] = Field(description="received_at of the observation; null if the source was never seen")
    stamp: Optional[datetime] = None
    freshness: Freshness
    value: dict[str, Any]
    severity: Severity
    software_revision: Revisions
    trace_id: str


class Check(_Model):
    id: str
    subsystem: str
    outcome: CheckOutcome
    severity: Severity
    summary: str
    next_check: Optional[str] = Field(default=None, description="Next human-verifiable check when the outcome is not pass")
    evidence: list[EvidenceRecord]


class Task(StrEnum):
    overall = "overall"
    upper_body = "upper_body"
    navigation = "navigation"


class ReadinessEvaluation(_Model):
    trace_id: str
    task: Task
    status: Readiness
    summary: str
    evaluated_at: datetime
    policy_version: str
    source_mode: SourceMode
    fixture_id: Optional[str] = None
    snapshot_id: str
    revisions: Revisions
    blocking: list[str] = Field(description="Ids of failed checks")
    unknown: list[str] = Field(description="Ids of checks that could not be decided")
    warnings: list[str] = Field(default_factory=list, description="Ids of checks that passed with a warning")
    checks: list[Check]
    disclaimer: str = Field(default="Software readiness from observed ROS state. Not a safety function, not physical acceptance.")


class ToolCall(_Model):
    trace_id: str
    seq: int
    tool: str
    args: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    outcome: Literal["ok", "refused", "error"]
    result_summary: str


class EventRecord(_Model):
    id: Optional[int] = None
    at: datetime
    subsystem: str
    severity: Severity
    kind: str = Field(description="status_change | diagnostic | connection | fixture | refusal")
    message: str
    trace_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class AgentQuery(_Model):
    question: str = Field(min_length=1, max_length=2000)


class AgentAnswer(_Model):
    trace_id: str
    question: str
    intent: str
    status: Optional[Readiness] = None
    refused: bool
    text: str
    evaluations: list[ReadinessEvaluation]
    tool_calls: list[ToolCall]
    provider: str = Field(description="deterministic | ollama | strands")
    model_text: Optional[str] = Field(default=None, description="Optional LLM phrasing; the deterministic text stays authoritative")


class ConnectionState(_Model):
    mode: SourceMode
    state: Literal["connected", "reconnecting", "disconnected", "fixture"]
    adapter_url: Optional[str] = None
    fixture_id: Optional[str] = None
    last_ok_at: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0


class ErrorBody(_Model):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    trace_id: Optional[str] = None


class ErrorResponse(_Model):
    error: ErrorBody


EXPORTED_MODELS = [
    Revisions, Observation, Snapshot, Freshness, EvidenceRecord, Check, ReadinessEvaluation,
    ToolCall, EventRecord, AgentQuery, AgentAnswer, ConnectionState, ErrorBody, ErrorResponse,
]
EXPORTED_ENUMS = [Readiness, Severity, FreshnessResult, CheckOutcome, SourceMode, Task]
