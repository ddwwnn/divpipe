# src/engine/divpipe/utils/fx.py

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .ccy import normalise_ccy


@dataclass(frozen=True)
class FxDiagnostics:
    total_rows: int
    non_usd_rows: int
    missing_ccy_rows: int
    missing_fx_rows: int
    converted_rows: int


def build_usd_per_ccy_map(rates: pd.DataFrame) -> dict[str, float]:
    """
    Build a map: CCY -> USD per 1 CCY (e.g., HKD -> 0.128).

    Accepted input layouts:
      - columns: ccy, usd_per_ccy
      - columns: from_ccy, to_ccy, rate  (requires to_ccy == 'USD')

    Invalid currency codes or non-numeric rates are dropped.
    """
    if rates is None or rates.empty:
        return {}

    cols = {c.lower(): c for c in rates.columns}

    if "ccy" in cols and "usd_per_ccy" in cols:
        ccy_col = cols["ccy"]
        rate_col = cols["usd_per_ccy"]

        df = rates[[ccy_col, rate_col]].copy()
        df["ccy_norm"] = df[ccy_col].map(normalise_ccy)
        df["rate_num"] = pd.to_numeric(df[rate_col], errors="coerce")

        return (
            df.dropna(subset=["ccy_norm", "rate_num"])
            .set_index("ccy_norm")["rate_num"]
            .to_dict()
        )

    if "from_ccy" in cols and "to_ccy" in cols and "rate" in cols:
        from_col = cols["from_ccy"]
        to_col = cols["to_ccy"]
        rate_col = cols["rate"]

        df = rates[[from_col, to_col, rate_col]].copy()
        df["from_ccy_norm"] = df[from_col].map(normalise_ccy)
        df["to_ccy_norm"] = df[to_col].map(normalise_ccy)
        df["rate_num"] = pd.to_numeric(df[rate_col], errors="coerce")

        mask = (
            df["from_ccy_norm"].notna()
            & df["to_ccy_norm"].eq("USD")
            & df["rate_num"].notna()
        )

        return (
            df.loc[mask]
            .set_index("from_ccy_norm")["rate_num"]
            .to_dict()
        )

    return {}


def add_usd_value(
    df: pd.DataFrame,
    value_col: str,
    ccy_col: str,
    out_col: str,
    usd_per_ccy: dict[str, float],
) -> tuple[pd.DataFrame, FxDiagnostics]:
    """
    Add df[out_col] = df[value_col] * usd_per_ccy[df[ccy_col]],
    with passthrough for USD rows.

    Returns (df2, diagnostics).
    """
    if df is None or df.empty:
        return (df.copy() if df is not None else pd.DataFrame()), FxDiagnostics(0, 0, 0, 0, 0)

    out = df.copy()

    if ccy_col in out.columns:
        ccy = out[ccy_col].map(normalise_ccy)
    else:
        ccy = pd.Series(pd.NA, index=out.index, dtype="object")

    if value_col in out.columns:
        val = pd.to_numeric(out[value_col], errors="coerce")
    else:
        val = pd.Series(pd.NA, index=out.index, dtype="float64")

    is_missing_ccy = ccy.isna()
    is_usd = ccy.eq("USD")
    is_non_usd = ccy.notna() & (~is_usd)

    rates = pd.to_numeric(ccy.map(usd_per_ccy), errors="coerce")
    rates = rates.where(~is_usd, 1.0)

    out[out_col] = val * rates

    is_missing_fx = is_non_usd & rates.isna()
    is_converted = out[out_col].notna()

    diag = FxDiagnostics(
        total_rows=int(len(out)),
        non_usd_rows=int(is_non_usd.sum()),
        missing_ccy_rows=int(is_missing_ccy.sum()),
        missing_fx_rows=int(is_missing_fx.sum()),
        converted_rows=int(is_converted.sum()),
    )
    return out, diag