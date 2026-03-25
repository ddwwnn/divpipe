# tests/test_link_events_vendor.py

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


def _single_debug_row() -> pd.DataFrame:
    return pd.DataFrame(
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


def _vendor_priority_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "vendor_b",
                "source_event_key": "row_b",
                "vendor_event_id": "VID_1",
                "underlying": "aaa",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "usd",
                "amount_ccy": "usd",
                "amount": 1.0,
                "ex_date": "2025-01-11",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
            {
                "source": "vendor_a",
                "source_event_key": "row_a",
                "vendor_event_id": "VID_1",
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
            },
        ]
    )


def _guardrail_fail_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "VID_1",
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
            },
            {
                "source": "vendor_a",
                "source_event_key": "row2",
                "vendor_event_id": "VID_1",
                "underlying": "BBB",
                "isin": "US0000000002",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.0,
                "ex_date": "2025-01-11",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )


def _guardrail_ok_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "VID_OK_1",
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
                "source_event_key": "row2",
                "vendor_event_id": "VID_OK_1",
                "underlying": "AAA",
                "isin": "US0000000001",
                "action_type": "cash_dividend",
                "share_class": "ordinary",
                "currency": "USD",
                "amount_ccy": "USD",
                "amount": 1.02,
                "ex_date": "2025-01-11",
                "record_date": "",
                "pay_date": "",
                "status": "historical",
            },
        ]
    )


def _preset_conflict_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source": "vendor_a",
                "source_event_key": "row1",
                "vendor_event_id": "VID_PRESET_1",
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
                "economic_event_id": "eco_manual_1",
            },
            {
                "source": "vendor_b",
                "source_event_key": "row2",
                "vendor_event_id": "VID_PRESET_1",
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
                "economic_event_id": "eco_manual_2",
            },
        ]
    )


def test_assign_economic_events_keep_debug_cols_preserves_debug_tie_raw() -> None:
    out = assign_economic_events(_single_debug_row(), keep_debug_cols=True)

    assert "debug_tie_raw" in out.columns
    assert len(out) == 1
    assert isinstance(out.loc[0, "debug_tie_raw"], str)
    assert out.loc[0, "debug_tie_raw"] != ""


def test_assign_economic_events_source_priority_changes_canonicalised_fields() -> None:
    df = _vendor_priority_rows()

    policy_a_first = LinkPolicy(source_priority={"VENDOR_A": 1, "VENDOR_B": 2})
    policy_b_first = LinkPolicy(source_priority={"VENDOR_A": 2, "VENDOR_B": 1})

    out_a_first = assign_economic_events(df, policy=policy_a_first)
    out_b_first = assign_economic_events(df, policy=policy_b_first)

    assert out_a_first["anchor_date"].astype(str).tolist() == ["2025-01-10", "2025-01-10"]
    assert out_b_first["anchor_date"].astype(str).tolist() == ["2025-01-11", "2025-01-11"]
    assert out_a_first["economic_event_id"].astype(str).tolist() != out_b_first["economic_event_id"].astype(str).tolist()


def test_assign_economic_events_respects_existing_economic_event_id() -> None:
    df = _base_rows()
    df.loc[0, "economic_event_id"] = "eco_preset_1"

    out = assign_economic_events(df, respect_existing=True)

    assert out.loc[0, "economic_event_id"] == "eco_preset_1"
    assert out.loc[0, "event_link_reason"] == "preset"


def test_assign_economic_events_vendor_event_id_guardrail_raises() -> None:
    with pytest.raises(ValueError, match="vendor_event_id group failed canonicalisation guardrail"):
        assign_economic_events(_guardrail_fail_rows())


def test_assign_economic_events_vendor_event_id_canonicalises_small_differences_within_guardrail() -> None:
    out = assign_economic_events(_guardrail_ok_rows())

    assert out["economic_event_id"].nunique() == 1
    assert out["primary_ident"].astype("string").nunique() == 1
    assert out["div_ccy"].astype("string").nunique() == 1
    assert out["anchor_date"].astype("string").nunique() == 1


def test_assign_economic_events_respect_existing_raises_on_preset_conflict_with_same_vendor_event_id() -> None:
    with pytest.raises(ValueError, match="conflicting preset economic_event_id for same vendor_event_id"):
        assign_economic_events(_preset_conflict_rows(), respect_existing=True)