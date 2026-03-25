# tests/test_event_id.py

from __future__ import annotations

from datetime import date

import pytest

from engine.divpipe.core.event_id import (
    LinkPolicy,
    make_observation_id,
    should_link_events,
)


def test_link_policy_rejects_negative_max_day_shift() -> None:
    with pytest.raises(ValueError, match="max_day_shift"):
        LinkPolicy(max_day_shift=-1)


def test_link_policy_rejects_negative_missing_amount_day_shift() -> None:
    with pytest.raises(ValueError, match="max_day_shift_when_amount_missing"):
        LinkPolicy(max_day_shift_when_amount_missing=-1)


def test_link_policy_rejects_negative_max_amount_rel_move() -> None:
    with pytest.raises(ValueError, match="max_amount_rel_move"):
        LinkPolicy(max_amount_rel_move=-0.01)

def test_link_policy_rejects_max_amount_rel_move_above_one() -> None:
    with pytest.raises(ValueError, match="max_amount_rel_move"):
        LinkPolicy(max_amount_rel_move=1.01)

def test_link_policy_rejects_negative_min_absolute_diff_ignore() -> None:
    with pytest.raises(ValueError, match="min_absolute_diff_ignore"):
        LinkPolicy(min_absolute_diff_ignore=-0.001)


def test_link_policy_rejects_negative_min_amount_denominator() -> None:
    with pytest.raises(ValueError, match="min_amount_denominator"):
        LinkPolicy(min_amount_denominator=-1e-9)


def test_link_policy_rejects_negative_stable_amount_decimals() -> None:
    with pytest.raises(ValueError, match="stable_amount_decimals"):
        LinkPolicy(stable_amount_decimals=-1)


def test_link_policy_rejects_negative_vendor_group_max_anchor_spread_days() -> None:
    with pytest.raises(ValueError, match="vendor_group_max_anchor_spread_days"):
        LinkPolicy(vendor_group_max_anchor_spread_days=-1)


def test_link_policy_rejects_negative_vendor_group_max_amount_rel_spread() -> None:
    with pytest.raises(ValueError, match="vendor_group_max_amount_rel_spread"):
        LinkPolicy(vendor_group_max_amount_rel_spread=-0.1)


def test_link_policy_normalises_source_priority_keys() -> None:
    policy = LinkPolicy(source_priority={" vendor_a ": 1, "Vendor_B": 2})
    assert policy.source_priority == {"VENDOR_A": 1, "VENDOR_B": 2}


def test_link_policy_rejects_blank_source_priority_key() -> None:
    with pytest.raises(ValueError, match="source_priority key"):
        LinkPolicy(source_priority={"   ": 1})


def test_link_policy_rejects_non_int_source_priority_value() -> None:
    with pytest.raises(ValueError, match="source_priority value"):
        LinkPolicy(source_priority={"VENDOR_A": "1"})


def test_make_observation_id_normalises_provider_text() -> None:
    a = make_observation_id(" vendor_a ", None, "row1", "2025-01-10")
    b = make_observation_id("VENDOR_A", "", "row1", "2025-01-10")
    assert a == b


def test_make_observation_id_changes_when_asof_date_changes() -> None:
    a = make_observation_id("VENDOR_A", "EVT_1", "row1", "2025-01-10")
    b = make_observation_id("VENDOR_A", "EVT_1", "row1", "2025-01-11")
    assert a != b


def test_should_link_events_blocks_when_day_shift_exceeds_max() -> None:
    policy = LinkPolicy(max_day_shift=5)
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 16)

    ok, reason = should_link_events(d1, 1.0, d2, 1.0, policy)

    assert ok is False
    assert reason == "day_shift=6>max"


@pytest.mark.parametrize(
    ("amt_a", "amt_b", "expected_ok", "reason_fragment"),
    [
        (None, 0.1, True, "amount_missing"),
        (0.0, 0.1, False, "zero_amount_block"),
        (1.0, 1.2, True, "rel_move="),
        (1.0, 1.3, False, "rel_move="),
    ],
)
def test_should_link_events_core_cases(
    amt_a: float | None,
    amt_b: float | None,
    expected_ok: bool,
    reason_fragment: str,
) -> None:
    policy = LinkPolicy(
        min_absolute_diff_ignore=0.0,
        min_amount_denominator=1e-9,
        max_amount_rel_move=0.20,
    )
    d1 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, amt_a, d1, amt_b, policy)

    assert ok is expected_ok
    assert reason_fragment in reason


def test_should_link_events_allows_missing_amount_within_missing_day_limit() -> None:
    policy = LinkPolicy(max_day_shift=5, max_day_shift_when_amount_missing=1)
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 11)

    ok, reason = should_link_events(d1, None, d2, 0.1, policy)

    assert ok is True
    assert "amount_missing" in reason


def test_should_link_events_blocks_missing_amount_beyond_missing_day_limit() -> None:
    policy = LinkPolicy(max_day_shift=5, max_day_shift_when_amount_missing=1)
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 12)

    ok, reason = should_link_events(d1, None, d2, 0.1, policy)

    assert ok is False
    assert "missing_amount_max" in reason


def test_should_link_events_blocks_zero_amount_by_default() -> None:
    policy = LinkPolicy(allow_zero_amount_link=False)
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, 0.0, d2, 0.1, policy)

    assert ok is False
    assert reason == "zero_amount_block"


def test_should_link_events_allows_zero_amount_when_policy_enabled() -> None:
    policy = LinkPolicy(allow_zero_amount_link=True)
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, 0.0, d2, 0.1, policy)

    assert ok is True
    assert "zero_amount_allowed" in reason

def test_should_link_events_allows_zero_amount_within_missing_day_limit_when_enabled() -> None:
    policy = LinkPolicy(
        allow_zero_amount_link=True,
        max_day_shift=5,
        max_day_shift_when_amount_missing=1,
    )
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 11)

    ok, reason = should_link_events(d1, 0.0, d2, 0.1, policy)

    assert ok is True
    assert "zero_amount_allowed" in reason


def test_should_link_events_blocks_zero_amount_beyond_missing_day_limit_when_enabled() -> None:
    policy = LinkPolicy(
        allow_zero_amount_link=True,
        max_day_shift=5,
        max_day_shift_when_amount_missing=1,
    )
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 12)

    ok, reason = should_link_events(d1, 0.0, d2, 0.1, policy)

    assert ok is False
    assert "zero_amount_max" in reason


def test_should_link_events_allows_small_absolute_diff() -> None:
    policy = LinkPolicy(min_absolute_diff_ignore=0.001)
    d1 = date(2025, 1, 10)
    d2 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, 0.01, d2, 0.0105, policy)

    assert ok is True
    assert "abs_diff=" in reason
    assert "<=min_abs(" in reason


def test_should_link_events_allows_tiny_denominator() -> None:
    policy = LinkPolicy(
        min_absolute_diff_ignore=0.0,
        min_amount_denominator=1e-9,
    )
    d1 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, 1e-12, d1, 2e-12, policy)

    assert ok is True
    assert "small_amount_denom=" in reason


def test_should_link_events_allows_relative_move_within_threshold() -> None:
    policy = LinkPolicy(
        max_amount_rel_move=0.20,
        min_absolute_diff_ignore=0.0,
    )
    d1 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, 1.0, d1, 1.2, policy)

    assert ok is True
    assert "rel_move=" in reason
    assert "<=max_rel(" in reason


def test_should_link_events_blocks_relative_move_beyond_threshold() -> None:
    policy = LinkPolicy(
        max_amount_rel_move=0.20,
        min_absolute_diff_ignore=0.0,
    )
    d1 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, 1.0, d1, 1.3, policy)

    assert ok is False
    assert "rel_move=" in reason
    assert ">max_rel(" in reason


def test_should_link_events_handles_negative_amounts() -> None:
    policy = LinkPolicy(
        max_amount_rel_move=0.10,
        min_absolute_diff_ignore=0.0,
    )
    d1 = date(2025, 1, 10)

    ok, reason = should_link_events(d1, -1.0, d1, -1.05, policy)

    assert ok is True
    assert "rel_move=" in reason or "abs_diff=" in reason