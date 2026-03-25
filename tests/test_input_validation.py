# tests/test_input_validation.py

from __future__ import annotations

import pandas as pd

from engine.divpipe.pipeline.input_validation import (
    normalise_underlying_text,
    split_valid_and_rejected_universe,
    validate_underlying_value,
)


def test_normalise_underlying_text_uppercases_and_strips() -> None:
    assert normalise_underlying_text("  pdd  ") == "PDD"
    assert normalise_underlying_text(" gulf.r ") == "GULF.R"


def test_validate_underlying_value_blank() -> None:
    out = validate_underlying_value("")
    assert out.is_valid is False
    assert out.reason == "blank_underlying"


def test_validate_underlying_value_placeholder() -> None:
    for value in ["-", "--", "N/A", "na", "none", "null", "nan", "<na>"]:
        out = validate_underlying_value(value)
        assert out.is_valid is False
        assert out.reason == "placeholder_underlying"


def test_validate_underlying_value_non_symbol() -> None:
    out = validate_underlying_value("***")
    assert out.is_valid is False
    assert out.reason == "non_symbol_underlying"


def test_validate_underlying_value_invalid_format() -> None:
    out = validate_underlying_value("ABC?")
    assert out.is_valid is False
    assert out.reason == "invalid_underlying_format"


def test_validate_underlying_value_valid_examples() -> None:
    for value in ["PDD", "0005", "GULF.R", "532483", "20", "PRIO3", "TMCV"]:
        out = validate_underlying_value(value)
        assert out.is_valid is True
        assert out.reason == ""


def test_split_valid_and_rejected_universe() -> None:
    universe = pd.DataFrame(
        [
            {
                "underlying": "PDD",
                "underlying_ccy": "USD",
                "isin": "US7223041028",
                "holdings_tag": "EEM",
                "holdings_file": "holdings_EEM.csv",
            },
            {
                "underlying": "-",
                "underlying_ccy": "USD",
                "isin": "",
                "holdings_tag": "EFA",
                "holdings_file": "holdings_EFA.csv",
            },
            {
                "underlying": "***",
                "underlying_ccy": "EUR",
                "isin": "",
                "holdings_tag": "EFA",
                "holdings_file": "holdings_EFA.csv",
            },
        ]
    )

    valid, rejected = split_valid_and_rejected_universe(universe)

    assert len(valid) == 1
    assert len(rejected) == 2

    assert valid.iloc[0]["underlying"] == "PDD"

    assert rejected["reason"].tolist() == [
        "placeholder_underlying",
        "non_symbol_underlying",
    ]
    assert rejected["underlying_raw"].tolist() == ["-", "***"]
    assert rejected["underlying_normalised"].tolist() == ["-", "***"]


def test_split_valid_and_rejected_universe_empty() -> None:
    universe = pd.DataFrame(columns=["underlying", "underlying_ccy", "isin"])
    valid, rejected = split_valid_and_rejected_universe(universe)

    assert valid.empty
    assert rejected.empty
    assert list(rejected.columns) == [
        "source",
        "underlying_raw",
        "underlying_normalised",
        "underlying_ccy",
        "isin",
        "reason",
        "holdings_tag",
        "holdings_file",
    ]