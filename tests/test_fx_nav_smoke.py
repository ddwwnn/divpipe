# tests/test_fx_nav_smoke.py

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.divpipe.utils.fx import add_usd_value, build_usd_per_ccy_map


def test_nav_ccy_to_nav_usd_smoke_and_diagnostics() -> None:
    rates = pd.DataFrame([{"ccy": "HKD", "usd_per_ccy": 0.128}])
    fx_map = build_usd_per_ccy_map(rates)

    assert fx_map["HKD"] == 0.128

    df = pd.DataFrame(
        [
            {"nav_ccy": 100.0, "nav_ccy_code": "HKD"},   # FX exists
            {"nav_ccy": 200.0, "nav_ccy_code": "USD"},   # passthrough
            {"nav_ccy": 300.0, "nav_ccy_code": "EUR"},   # FX missing
            {"nav_ccy": 400.0, "nav_ccy_code": None},    # missing ccy
        ]
    )

    out, diag = add_usd_value(
        df=df,
        value_col="nav_ccy",
        ccy_col="nav_ccy_code",
        out_col="nav_usd",
        usd_per_ccy=fx_map,
    )

    assert out.loc[0, "nav_usd"] == 100.0 * 0.128
    assert out.loc[1, "nav_usd"] == 200.0
    assert pd.isna(out.loc[2, "nav_usd"])
    assert pd.isna(out.loc[3, "nav_usd"])

    assert pd.api.types.is_float_dtype(out["nav_usd"])

    assert diag.total_rows == 4
    assert diag.non_usd_rows == 2
    assert diag.missing_ccy_rows == 1
    assert diag.missing_fx_rows == 1
    assert diag.converted_rows == 2


def test_add_usd_value_handles_zero_and_nan_inputs() -> None:
    rates = pd.DataFrame([{"ccy": "HKD", "usd_per_ccy": 0.128}])
    fx_map = build_usd_per_ccy_map(rates)

    df = pd.DataFrame(
        [
            {"val": 0.0, "ccy": "HKD"},
            {"val": np.nan, "ccy": "HKD"},
            {"val": 50.0, "ccy": "USD"},
            {"val": 75.0, "ccy": "EUR"},
        ]
    )

    out, diag = add_usd_value(
        df=df,
        value_col="val",
        ccy_col="ccy",
        out_col="val_usd",
        usd_per_ccy=fx_map,
    )

    assert out.loc[0, "val_usd"] == 0.0
    assert pd.isna(out.loc[1, "val_usd"])
    assert out.loc[2, "val_usd"] == 50.0
    assert pd.isna(out.loc[3, "val_usd"])

    assert pd.api.types.is_float_dtype(out["val_usd"])

    assert diag.total_rows == 4
    assert diag.non_usd_rows == 3 # HKD, HKD, EUR
    assert diag.missing_ccy_rows == 0
    assert diag.missing_fx_rows == 1
    assert diag.converted_rows == 2