# tests/test_ccy_normaliser.py

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.divpipe.utils.ccy import normalise_ccy, scale_amount


@pytest.mark.parametrize(
    ("input_val", "expected"),
    [
        (" usd ", "USD"),
        ("GBP", "GBP"),
        ("", pd.NA),
        (None, pd.NA),
        ("NAN", pd.NA),
        ("NON", pd.NA),
        ("<NA>", pd.NA),
        ("USDT", pd.NA),
        ("12", pd.NA),
    ],
)
def test_normalise_ccy_parametrised(input_val, expected) -> None:
    result = normalise_ccy(input_val)

    if pd.isna(expected):
        assert pd.isna(result)
    else:
        assert result == expected


@pytest.mark.parametrize(
    ("amount", "unit", "expected"),
    [
        (10, "pct", 0.1),
        (100, "bps", 0.01),
        ("1.23", None, 1.23),
        (1.23, None, 1.23),
        (None, "pct", pd.NA),
        ("abc", None, pd.NA),
        (np.nan, None, pd.NA),
    ],
)
def test_scale_amount_parametrised(amount, unit, expected) -> None:
    result = scale_amount(amount, unit)

    if pd.isna(expected):
        assert pd.isna(result)
    else:
        assert result == pytest.approx(expected)