# tests/test_schema_contract.py

from __future__ import annotations

import pandas as pd

from engine.divpipe.pipeline.overrides import OPT_COLS, REQ_COLS
from engine.divpipe.schema.canonical import enforce_canonical_dtypes
from engine.divpipe.schema.columns import (
    INPUT_HOLDINGS_REQUIRED_COLUMNS,
    STAGE1_DIVIDENDS_REQUIRED_COLUMNS,
    STAGE1_ERRORS_REQUIRED_COLUMNS,
    STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
)


def _assert_required_columns(df: pd.DataFrame, required: list[str], artefact: str) -> None:
    missing = [c for c in required if c not in df.columns]
    assert not missing, f"Missing required columns for {artefact}: {missing}"


def test_schema_contract_required_columns_lists_are_sane() -> None:
    """
    Lightweight schema contract test.
    It validates that the required-columns contract is well-formed and internally consistent.
    This test does not touch network or filesystem.
    """
    required: dict[str, list[str]] = {
        "input_holdings": INPUT_HOLDINGS_REQUIRED_COLUMNS,
        "seed_yfinance_dividends_all.csv": STAGE1_DIVIDENDS_REQUIRED_COLUMNS,
        "seed_yfinance_errors_all.csv": STAGE1_ERRORS_REQUIRED_COLUMNS,
        "seed_yfinance_no_dividends_all.csv": STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
        "seed_yfinance_dividends_all__linked_severity.csv": [
            "economic_event_id",
            "event_link_reason",
            "severity_tier",
        ],
        "econ_severity_summary.csv": [
            "economic_event_id",
            "severity_tier",
            "row_count",
            "amount_nunique",
            "anchor_spread_days",
        ],
        "qa_queue__econ.csv": [
            "economic_event_id",
            "severity_tier",
            "row_count",
        ],
        "qa_queue__rows.csv": [
            "economic_event_id",
            "severity_tier",
        ],
        "fixture_debug__case_tag_severity.csv": [
            "case_tag",
            "economic_event_id",
            "severity_tier",
        ],
        "fixture_debug__o3_within_run_pairs.csv": [
            "underlying",
            "econ_id_a",
            "econ_id_b",
            "ex_date_abs_shift_days",
            "amount_abs_diff",
        ],
        "rows__brazil.csv": [
            "economic_event_id",
            "severity_tier",
        ],
        "rows__non_brazil.csv": [
            "economic_event_id",
            "severity_tier",
        ],
        "rows__korea.csv": [
            "economic_event_id",
            "severity_tier",
        ],
        "no_div__brazil.csv": [
            "source",
            "underlying",
            "underlying_ccy",
            "status",
        ],
        "no_div__korea.csv": [
            "source",
            "underlying",
            "underlying_ccy",
            "status",
        ],
        "qa_decisions_template.csv": REQ_COLS + OPT_COLS,
        "qa_queue__o3_pairs.csv": [
            "underlying",
            "econ_id_a",
            "econ_id_b",
            "ex_date_abs_shift_days",
            "amount_abs_diff",
        ],
        "qa_queue__o3_econ.csv": [
            "economic_event_id",
            "severity_tier",
            "row_count",
        ],
    }

    for artefact, cols in required.items():
        assert cols, f"Empty required columns list: {artefact}"
        assert all(isinstance(c, str) and c.strip() for c in cols), f"Bad column name in {artefact}: {cols}"
        assert len(set(cols)) == len(cols), f"Duplicate required columns in {artefact}: {cols}"


def test_stage1_dividends_required_columns_are_subset_of_canonical() -> None:
    """
    Stage1 dividends artefact must be compatible with the canonical schema.
    """
    canon = enforce_canonical_dtypes(pd.DataFrame())
    _assert_required_columns(canon, STAGE1_DIVIDENDS_REQUIRED_COLUMNS, "seed_yfinance_dividends_all.csv")


def test_validate_literals_coerces_invalid_values_to_unknown() -> None:
    df = pd.DataFrame(
        {
            "action_type": ["cash_dividend", "weird_value", " Interest_On_Capital "],
            "period_type": ["final", "bad_period", " Quarterly "],
            "share_class": ["common", "bad_class", "PREFERRED"],
            "amount_type": ["per_share", "bad_amount_type", " TOTAL "],
        }
    )

    out = enforce_canonical_dtypes(df)

    assert out["action_type"].tolist() == ["cash_dividend", "unknown", "interest_on_capital"]
    assert out["period_type"].tolist() == ["final", "unknown", "quarterly"]
    assert out["share_class"].tolist() == ["common", "unknown", "preferred"]
    assert out["amount_type"].tolist() == ["per_share", "unknown", "total"]


def test_enforce_canonical_dtypes_applies_string_and_numeric_rules() -> None:
    df = pd.DataFrame(
        {
            "isin": [" us 0378331005 ", None],
            "currency": [" usd ", "krw"],
            "amount_ccy": [" usd ", " eur "],
            "yfinance_ticker": [" aapl ", "005930.ks"],
            "amount": ["1.25", "bad"],
            "confidence": ["7", None],
        }
    )

    out = enforce_canonical_dtypes(df)

    assert out["isin"].tolist() == ["US0378331005", ""]
    assert out["currency"].tolist() == ["USD", "KRW"]
    assert out["amount_ccy"].tolist() == ["USD", "EUR"]
    assert out["yfinance_ticker"].tolist() == ["AAPL", "005930.KS"]

    assert float(out.loc[0, "amount"]) == 1.25
    assert pd.isna(out.loc[1, "amount"])

    assert str(out["confidence"].dtype) == "Int64"
    assert out["confidence"].tolist() == [7, pd.NA]


def test_enforce_canonical_dtypes_reindexes_to_canonical_columns_only() -> None:
    df = pd.DataFrame(
        {
            "source": ["yfinance"],
            "underlying": ["AAPL"],
            "amount": [0.25],
            "junk_column": ["drop_me"],
        }
    )

    out = enforce_canonical_dtypes(df)

    assert "junk_column" not in out.columns
    assert "source" in out.columns
    assert "underlying" in out.columns
    assert "amount" in out.columns