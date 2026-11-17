"""Readiness classification, freshness and failure handling (RFC Appendix A rules)."""
import copy
from datetime import timedelta

import pytest

from conftest import load_fixture
from oar_contracts import CheckOutcome, FreshnessResult, Readiness, Task
from studio_api import profile as P
from studio_api.diagnostics import evaluate, freshness, roll_up

EXPECTED = {
    # fixture: (overall, upper_body, navigation)
    "healthy": ("READY", "READY", "READY"),
    "inactive_controller": ("BLOCKED", "BLOCKED", "READY"),
    "stale_telemetry": ("UNKNOWN", "UNKNOWN", "UNKNOWN"),
    "missing_graph": ("ERROR", "ERROR", "ERROR"),
    "conflicting_state": ("UNKNOWN", "READY", "UNKNOWN"),
    "diagnostic_warning": ("READY", "READY", "READY"),
}


@pytest.mark.parametrize("fid", sorted(EXPECTED))
def test_fixture_classification(fid):
    snap, now, _ = load_fixture(fid)
    got = tuple(evaluate(snap, t, now, "diag-t").status.value for t in (Task.overall, Task.upper_body, Task.navigation))
    assert got == EXPECTED[fid]


def test_every_fixture_has_an_expectation():
    from conftest import FIXTURE_IDS
    assert sorted(EXPECTED) == FIXTURE_IDS


def test_deterministic_same_input_same_output():
    snap, now, _ = load_fixture("conflicting_state")
    a = evaluate(snap, Task.overall, now, "diag-same").model_dump(mode="json")
    b = evaluate(snap, Task.overall, now, "diag-same").model_dump(mode="json")
    assert a == b


def test_every_check_carries_full_evidence_records():
    for fid in EXPECTED:
        snap, now, _ = load_fixture(fid)
        ev = evaluate(snap, Task.overall, now, "diag-ev")
        assert ev.checks, fid
        for c in ev.checks:
            assert c.evidence, (fid, c.id)
            for e in c.evidence:
                assert e.source and e.trace_id == "diag-ev" and e.software_revision.studio
                assert e.freshness.max_age_s > 0
                if e.freshness.result == FreshnessResult.missing:
                    assert e.observed_at is None and e.freshness.age_s is None


def test_inactive_controller_names_the_blocker_and_next_check():
    snap, now, _ = load_fixture("inactive_controller")
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    assert ev.blocking == ["controller.lift_controller"]
    c = next(c for c in ev.checks if c.id == "controller.lift_controller")
    assert "inactive" in c.summary and c.next_check and c.evidence[0].value["state"] == "inactive"


def test_stale_is_unknown_never_ready_or_blocked():
    snap, now, _ = load_fixture("stale_telemetry")
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    js = next(c for c in ev.checks if c.id == "joint_states")
    assert js.outcome == CheckOutcome.unknown
    assert js.evidence[0].freshness.result == FreshnessResult.stale
    assert js.evidence[0].freshness.age_s == pytest.approx(4.2)


def test_conflict_reports_both_sides_unknown():
    snap, now, _ = load_fixture("conflicting_state")
    ev = evaluate(snap, Task.navigation, now, "diag-t")
    by = {c.id: c for c in ev.checks}
    assert by["navigation_status.readiness"].outcome == CheckOutcome.unknown
    assert by["lifecycle.controller_server"].outcome == CheckOutcome.unknown
    assert "Contradictory" in by["lifecycle.controller_server"].summary
    assert ev.blocking == []


def test_inactive_node_without_contradiction_blocks():
    snap, now, _ = load_fixture("conflicting_state")
    for o in snap.observations:
        if o.kind == "navigation_status":
            o.value["navigation_readiness"] = 0
            o.value["not_ready_reasons"] = [1004]
    ev = evaluate(snap, Task.navigation, now, "diag-t")
    assert ev.status == Readiness.BLOCKED
    assert "NAV_NODE_INACTIVE" in next(c for c in ev.checks if c.id == "navigation_status.readiness").summary
    assert "lifecycle.controller_server" in ev.blocking


def test_warning_passes_with_severity_warning():
    snap, now, _ = load_fixture("diagnostic_warning")
    ev = evaluate(snap, Task.overall, now, "diag-t")
    assert ev.status == Readiness.READY
    assert "diagnostic.navigation_status_node: sensor scan_rear" in ev.warnings
    assert "navigation_status.health" in ev.warnings


@pytest.mark.parametrize("age,expected", [(0.0, "fresh"), (1.0, "fresh"), (1.001, "stale"), (-1.0, "fresh"),
                                          (-1.6, "stale")])
def test_freshness_boundaries(age, expected):
    snap, now, _ = load_fixture("healthy")
    js = next(o for o in snap.observations if o.kind == "joint_state")
    js = js.model_copy(update={"received_at": now - timedelta(seconds=age)})
    assert freshness(js, "joint_state", now).result.value == expected
    assert freshness(None, "joint_state", now).result == FreshnessResult.missing


def _healthy_with(mutate):
    snap, now, _ = load_fixture("healthy")
    snap = snap.model_copy(deep=True)
    mutate(snap)
    return snap, now


def test_missing_joint_states_is_unknown():
    snap, now = _healthy_with(lambda s: setattr(s, "observations", [o for o in s.observations if o.kind != "joint_state"]))
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    assert ev.status == Readiness.UNKNOWN and "joint_states" in ev.unknown


def test_non_finite_joint_blocks():
    def m(s):
        js = next(o for o in s.observations if o.kind == "joint_state")
        js.value["position"][js.value["name"].index("lift_joint")] = None  # adapter maps NaN to null
    snap, now = _healthy_with(m)
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    assert ev.status == Readiness.BLOCKED and "lift_joint" in ev.checks[-1].summary


def test_active_controller_without_its_joint_is_contradictory():
    def m(s):
        js = next(o for o in s.observations if o.kind == "joint_state")
        i = js.value["name"].index("lift_joint")
        for k in ("name", "position", "velocity"):
            js.value[k].pop(i)
    snap, now = _healthy_with(m)
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    assert ev.status == Readiness.UNKNOWN
    assert "Contradictory" in next(c for c in ev.checks if c.id == "joint_states").summary


def test_list_controllers_timeout_is_error():
    def m(s):
        c = next(o for o in s.observations if o.kind == "controllers")
        c.value.clear()
        c.value.update(available=True, error="timeout after 1.0 s")
    snap, now = _healthy_with(m)
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    assert ev.status == Readiness.ERROR and "timeout" in ev.summary


def test_controller_manager_not_running_blocks():
    def m(s):
        c = next(o for o in s.observations if o.kind == "controllers")
        c.value.clear()
        c.value.update(available=False, controllers=[])
    snap, now = _healthy_with(m)
    assert evaluate(snap, Task.upper_body, now, "diag-t").status == Readiness.BLOCKED


def test_unloaded_controller_blocks():
    def m(s):
        c = next(o for o in s.observations if o.kind == "controllers")
        c.value["controllers"] = [x for x in c.value["controllers"] if x["name"] != "right_gripper_controller"]
    snap, now = _healthy_with(m)
    ev = evaluate(snap, Task.upper_body, now, "diag-t")
    assert ev.blocking == ["controller.right_gripper_controller"]


def test_navigation_missing_is_unknown_not_blocked():
    snap, now = _healthy_with(lambda s: setattr(s, "observations",
                                                [o for o in s.observations if o.kind not in ("navigation_status", "lifecycle")]))
    assert evaluate(snap, Task.navigation, now, "diag-t").status == Readiness.UNKNOWN


def test_overall_respects_expected_subsystems():
    snap, now = _healthy_with(lambda s: setattr(s, "observations",
                                                [o for o in s.observations if o.kind not in ("navigation_status", "lifecycle", "diagnostics")]))
    assert evaluate(snap, Task.overall, now, "diag-t").status == Readiness.UNKNOWN
    assert evaluate(snap, Task.overall, now, "diag-t", subsystems=("upper_body",)).status == Readiness.READY


def test_unknown_reason_code_is_named_not_dropped():
    def m(s):
        n = next(o for o in s.observations if o.kind == "navigation_status")
        n.value.update(navigation_readiness=0, not_ready_reasons=[9001, 9999])
    snap, now = _healthy_with(m)
    ev = evaluate(snap, Task.navigation, now, "diag-t")
    assert "BASE_LINK_LOST" in ev.summary and "UNKNOWN_REASON_9999" in ev.summary


def test_roll_up_precedence():
    snap, now, _ = load_fixture("healthy")
    base = evaluate(snap, Task.upper_body, now, "diag-t").checks
    def with_(outcome):
        c = copy.deepcopy(base)
        c[1] = c[1].model_copy(update={"outcome": outcome})
        return c
    assert roll_up(base) == Readiness.READY
    assert roll_up(with_(CheckOutcome.unknown)) == Readiness.UNKNOWN
    assert roll_up(with_(CheckOutcome.failed)) == Readiness.BLOCKED
    assert roll_up(with_(CheckOutcome.error)) == Readiness.ERROR
    assert roll_up([]) == Readiness.UNKNOWN


def test_profile_matches_upstream_counts():
    assert len(P.UPPER_BODY_CONTROLLERS) == 6
    assert len(P.UPPER_BODY_JOINTS) == 17
    assert len(P.NAV2_MANAGED_NODES) == 10
