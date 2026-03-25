# tests/test_link_events_basic.py

from __future__ import annotations

import pandas as pd
import pytest

from engine.divpipe.core.event_id import LinkPolicy
from engine.divpipe.pipeline.link_events import assign_economic_events


def _base_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "yfinance",
                "source_event_key": "AAA|USD|2025-01-10",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.00,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_b",
                "source_event_key": "AAA|USD|2025-01-12",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.05,
                "ex_date": "2025-01-12",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_c",
                "source_event_key": "AAA|USD|2025-02-20",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.30,
                "ex_date": "2025-02-20",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )


def _make_min_df(asof: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "underlying": "EEM",
                "div_ccy": "USD",
                "ex_date": "2025-12-12",
                "pay_date": "2025-12-20",
                "amount": 0.10,
                "asof": asof,
            },
            {
                "underlying": "EEM",
                "div_ccy": "USD",
                "ex_date": "2025-12-12",
                "pay_date": "2025-12-20",
                "amount": 0.10,
                "asof": asof,
            },
        ]
    )


def _make_zero_amount_rows(ex_a: str, ex_b: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 0.0,
                "ex_date": ex_a,
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_b",
                "source_event_key": "row2",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 0.1,
                "ex_date": ex_b,
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )


def _make_missing_amount_rows(ex_a: str, ex_b: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": None,
                "ex_date": ex_a,
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_b",
                "source_event_key": "row2",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 0.1,
                "ex_date": ex_b,
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )


def test_assign_economic_events_links_nearby_rows_and_splits_far_rows() -> None:
    df = _base_rows()

    out = assign_economic_events(
        df,
        policy=LinkPolicy(max_day_shift=5, max_amount_rel_move=0.20),
    )

    econ_ids = out["economic_event_id"].astype("string").tolist()

    assert econ_ids[0] == econ_ids[1]
    assert econ_ids[2] != econ_ids[0]


def test_assign_economic_events_is_shuffle_invariant() -> None:
    df = _base_rows()

    out1 = assign_economic_events(df).sort_values("source_event_key").reset_index(drop=True)

    shuffled = df.sample(frac=1.0, random_state=7).reset_index(drop=True)
    out2 = assign_economic_events(shuffled).sort_values("source_event_key").reset_index(drop=True)

    cols = ["source_event_key", "economic_event_id", "event_link_reason"]
    pd.testing.assert_frame_equal(out1[cols], out2[cols], check_dtype=False)


def test_assign_economic_events_can_split_same_anchor_date_when_rows_do_not_link() -> None:
    df = pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 0.0,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_b",
                "source_event_key": "row2",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 0.1,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )

    out = assign_economic_events(
        df,
        policy=LinkPolicy(allow_zero_amount_link=False),
    )

    econ_ids = out["economic_event_id"].astype("string").tolist()
    assert econ_ids[0] != econ_ids[1]


def test_assign_economic_events_zero_amount_blocks_link_by_default() -> None:
    df = _make_zero_amount_rows("2025-01-10", "2025-01-11")

    out = assign_economic_events(
        df,
        policy=LinkPolicy(
            allow_zero_amount_link=False,
            max_day_shift=5,
        ),
    )

    econ_ids = out["economic_event_id"].astype("string").tolist()
    assert econ_ids[0] != econ_ids[1]


def test_assign_economic_events_zero_amount_can_link_when_enabled() -> None:
    df = _make_zero_amount_rows("2025-01-10", "2025-01-11")

    out = assign_economic_events(
        df,
        policy=LinkPolicy(
            allow_zero_amount_link=True,
            max_day_shift=5,
        ),
    )

    econ_ids = out["economic_event_id"].astype("string").tolist()
    assert econ_ids[0] == econ_ids[1]


def test_assign_economic_events_zero_amount_enabled_still_respects_max_day_shift() -> None:
    df = _make_zero_amount_rows("2025-01-10", "2025-01-20")

    out = assign_economic_events(
        df,
        policy=LinkPolicy(
            allow_zero_amount_link=True,
            max_day_shift=5,
        ),
    )

    econ_ids = out["economic_event_id"].astype("string").tolist()
    assert econ_ids[0] != econ_ids[1]


def test_assign_economic_events_marks_invalid_rows_as_skip() -> None:
    df = pd.DataFrame(
        [
            {
                "source": "yfinance",
                "source_event_key": "AAA|?|2025-01-10",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "",
                "amount_ccy": "",
                "amount": 1.0,
                "ex_date": "",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            }
        ]
    )

    out = assign_economic_events(df)

    assert out.loc[0, "economic_event_id"] == ""
    assert str(out.loc[0, "event_link_reason"]).startswith("skip:")


def test_assign_economic_events_amount_format_noise_does_not_change_result() -> None:
    df1 = pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.0,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            }
        ]
    )

    df2 = df1.copy()
    df2.loc[0, "amount"] = 1.0000000001

    out1 = assign_economic_events(df1)
    out2 = assign_economic_events(df2)

    assert out1.loc[0, "economic_event_id"] == out2.loc[0, "economic_event_id"]


def test_assign_economic_events_preserves_output_row_order() -> None:
    df = _base_rows().sample(frac=1.0, random_state=123).reset_index(drop=True)
    expected_order = df["source_event_key"].tolist()

    out = assign_economic_events(df)

    assert out["source_event_key"].tolist() == expected_order


def test_assign_economic_events_is_stable_across_two_asof() -> None:
    df_a = _make_min_df("2025-12-12")
    df_b = _make_min_df("2025-12-13")

    out_a = assign_economic_events(df_a)
    out_b = assign_economic_events(df_b)

    assert "economic_event_id" in out_a.columns
    assert "economic_event_id" in out_b.columns
    assert out_a["economic_event_id"].astype(str).tolist() == out_b["economic_event_id"].astype(str).tolist()


def test_assign_economic_events_case_noise_in_ccy_and_text_does_not_split_event() -> None:
    df = pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "",
                "underlying": "aaa",
                "isin": "us0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "usd",
                "amount_ccy": "usd",
                "amount": 1.00,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_b",
                "source_event_key": "row2",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.00,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )

    out = assign_economic_events(df)

    econ_ids = out["economic_event_id"].astype("string").tolist()
    assert econ_ids[0] == econ_ids[1]


def test_assign_economic_events_tiny_amount_noise_does_not_split_event() -> None:
    df = pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1e-12,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_b",
                "source_event_key": "row2",
                "vendor_event_id": "",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 2e-12,
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )

    out = assign_economic_events(
        df,
        policy=LinkPolicy(
            min_absolute_diff_ignore=0.0,
            min_amount_denominator=1e-9,
        ),
    )

    econ_ids = out["economic_event_id"].astype("string").tolist()
    assert econ_ids[0] == econ_ids[1]


@pytest.mark.parametrize(
    ("mode", "ex_a", "ex_b", "policy", "expect_same_cluster"),
    [
        (
            "missing_amount_within_limit",
            "2025-01-10",
            "2025-01-11",
            LinkPolicy(max_day_shift=5, max_day_shift_when_amount_missing=1),
            True,
        ),
        (
            "missing_amount_beyond_limit",
            "2025-01-10",
            "2025-01-12",
            LinkPolicy(max_day_shift=5, max_day_shift_when_amount_missing=1),
            False,
        ),
        (
            "zero_amount_blocked",
            "2025-01-10",
            "2025-01-11",
            LinkPolicy(max_day_shift=5, allow_zero_amount_link=False),
            False,
        ),
        (
            "zero_amount_allowed",
            "2025-01-10",
            "2025-01-11",
            LinkPolicy(max_day_shift=5, allow_zero_amount_link=True),
            True,
        ),
    ],
)
def test_assign_economic_events_missing_and_zero_amount_table(
    mode: str,
    ex_a: str,
    ex_b: str,
    policy: LinkPolicy,
    expect_same_cluster: bool,
) -> None:
    if mode.startswith("missing_amount"):
        df = _make_missing_amount_rows(ex_a, ex_b)
    else:
        df = _make_zero_amount_rows(ex_a, ex_b)

    out = assign_economic_events(df, policy=policy)

    econ_ids = out["economic_event_id"].astype("string").tolist()

    if expect_same_cluster:
        assert econ_ids[0] == econ_ids[1]
    else:
        assert econ_ids[0] != econ_ids[1]