# src/engine/divpipe/utils/ccy.py

from __future__ import annotations

from typing import Any

import pandas as pd


def normalise_ccy(x: Any) -> Any:
    """
    Return a normalised 3-letter currency code.

    Examples:
      - 'usd ' -> 'USD'
      - None / NaN / pd.NA / invalid length -> pd.NA
    """
    if pd.isna(x):
        return pd.NA

    s = str(x).strip().upper()
    if len(s) != 3 or s in {"NAN", "NON", "<NA>"}:
        return pd.NA

    return s


def scale_amount(amount: Any, unit: str | None) -> Any:
    """
    Minimal scaling:
      - unit == 'pct' => divide by 100
      - unit == 'bps' => divide by 10000
      - otherwise => passthrough

    Invalid / non-numeric inputs return pd.NA.
    """
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return pd.NA

    if pd.isna(val):
        return pd.NA

    u = str(unit or "").strip().lower()
    if u == "pct":
        return val / 100.0
    if u == "bps":
        return val / 10000.0
    return val