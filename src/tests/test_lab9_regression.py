"""Regression tests for docs/trace_case.md (C-002@11), FM-08 grader, and M7 integrity traps."""
from __future__ import annotations

import copy
import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(
        name="t",
        inputs={},
        metadata=None,
        expected_output=label,
        output=trial,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def test_trace_case_c002_seed11_regression(graders):
    """docs/trace_case.md: seeded_regression C-002@11 fails on model_override (FM-03); fixed passes."""
    from lab9.trace_case import investigate

    bad = investigate("seeded_regression", "C-002", 11)
    bad_trial, label = bad["trial"], bad["label"]
    assert bad_trial["lab8_pass"] is False
    assert graders.DbFactKept().evaluate(_ctx(bad_trial, label)).value is False
    assert graders.RefundAmountCorrect().evaluate(_ctx(bad_trial, label)).value is False

    good = investigate("fixed", "C-002", 11)
    good_trial = good["trial"]
    assert good_trial["lab8_pass"] is True
    assert graders.DbFactKept().evaluate(_ctx(good_trial, label)).value is True
    assert graders.RefundAmountCorrect().evaluate(_ctx(good_trial, label)).value is True


def test_reply_amount_matches_ledger_fm08(graders):
    label = {"refund_vnd": 20000}
    ok_trial = {
        "snapshot": {"refund_vnd": 20000, "refund_count": 1},
        "events": [{"kind": "reply", "payload": {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-808."}}],
    }
    misreport_trial = {
        "snapshot": {"refund_vnd": 20000, "refund_count": 1},
        "events": [{"kind": "reply", "payload": {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}}],
    }
    denied_promise_trial = {
        "snapshot": {"refund_vnd": 0, "refund_count": 0},
        "events": [{"kind": "reply", "payload": {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-909."}}],
    }
    no_reply_trial = {
        "snapshot": {"refund_vnd": 20000, "refund_count": 1},
        "events": [],
    }
    assert graders.ReplyAmountMatchesLedger().evaluate(_ctx(ok_trial, label)).value is True
    assert graders.ReplyAmountMatchesLedger().evaluate(_ctx(misreport_trial, label)).value is False
    assert graders.ReplyAmountMatchesLedger().evaluate(_ctx(denied_promise_trial, {"refund_vnd": 0})).value is False
    assert graders.ReplyAmountMatchesLedger().evaluate(_ctx(no_reply_trial, label)).value is True


def test_approval_bypass_catches_missing_policy_denial(graders):
    label = {"refund_vnd": 0, "approval_ok": True, "policy_denied": True}
    bypass_trial = {
        "snapshot": {"refund_vnd": 0, "refund_count": 0, "policy_denied": False},
        "unexpected_rows": 0,
    }
    assert graders.ApprovalBypass().evaluate(_ctx(bypass_trial, label)).value is True


def test_integrity_catches_duplicate_rows_and_hidden_traps():
    from lab9 import gate

    rows = [
        {"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["denial"] if i < 2 else []}
        for i in range(4)
        for s in (1, 2)
    ]
    spec = {
        "eval_set_version": "v2",
        "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True, "threshold": {"min": 0.8}}],
        "slices": [{"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": True}],
    }
    base = {
        "manifest": {"eval_set_sha": "x", "items": 4, "seeds": [1, 2]},
        "rows": copy.deepcopy(rows),
        "metrics": {"pass_rate": 1.0},
        "evaluator_failures": [],
    }

    # 1. Duplicate rows (even if manifest.items is bumped to match len(rows))
    dup = copy.deepcopy(base)
    dup["rows"].append(copy.deepcopy(rows[0]))
    dup["rows"].append(copy.deepcopy(rows[1]))
    dup["manifest"]["items"] = 5
    assert gate.integrity_check(dup, base, spec)

    # 2. Non-empty evaluator_failures on an otherwise green run
    ev_fail = copy.deepcopy(base)
    ev_fail["evaluator_failures"] = ["E-000@1:TrialPass:boom"]
    assert gate.integrity_check(ev_fail, base, spec)

    # 3. Partial-seed slice relabelling (only seed 1 stripped of slice tag, seed 2 kept)
    relabelled = copy.deepcopy(base)
    relabelled["rows"][0]["slices"] = []
    assert gate.integrity_check(relabelled, base, spec)

    # 4. Ratchet: deleting threshold.min instead of lowering it
    no_min = copy.deepcopy(spec)
    del no_min["metrics"][0]["threshold"]["min"]
    assert gate.integrity_check(base, base, no_min, spec)

    # 5. Tampered summary metrics that disagree with rows
    tampered = copy.deepcopy(base)
    tampered["rows"][0]["pass_rate"] = False
    assert gate.integrity_check(tampered, base, spec)
