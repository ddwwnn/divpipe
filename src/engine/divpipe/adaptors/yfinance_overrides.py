# src/engine/divpipe/adaptors/yfinance_overrides.py

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import yfinance_models as ym
from . import yfinance_utils as yu


_REQUIRED_BASE_COLUMNS = (
    "underlying",
    "chosen_ticker",
)

_OPTIONAL_COLUMNS = (
    "ccy",
    "underlying_ccy",
    "resolution_reason",
    "resolution_method",
    "reason",
    "method",
    "isin",
    # Forward-compatible passthrough columns.
    # These are intentionally tolerated here even if OverrideResolution
    # does not currently consume them directly.
    "preverified_exists_any",
    "preverified_exists_ticker",
    # Legacy compatibility only.
    "exists_ns",
    "exists_bo",
)


def _empty_override_resolution() -> ym.OverrideResolution:
    return ym.OverrideResolution(
        ticker="",
        reason="",
        method="",
        source="",
        isin="",
    )


def _load_raw_chosen_map_df(path: str) -> pd.DataFrame:
    file_path = Path(path)
    if not path or not file_path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(file_path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def _normalise_chosen_map_df(path: str) -> pd.DataFrame:
    raw_df = _load_raw_chosen_map_df(path)
    if raw_df.empty:
        return pd.DataFrame()

    required_missing = [col for col in _REQUIRED_BASE_COLUMNS if col not in raw_df.columns]
    for col in required_missing:
        raw_df[col] = ""

    for col in _OPTIONAL_COLUMNS:
        if col not in raw_df.columns:
            raw_df[col] = ""

    ordered_front = list(_REQUIRED_BASE_COLUMNS) + list(_OPTIONAL_COLUMNS)
    ordered_columns = ordered_front + [col for col in raw_df.columns if col not in ordered_front]

    return raw_df.reindex(columns=ordered_columns).copy()


def _pick_ccy_column(df: pd.DataFrame) -> str:
    if "underlying_ccy" in df.columns:
        populated_underlying_ccy = df["underlying_ccy"].astype(str).str.strip().ne("").any()
        if populated_underlying_ccy:
            return "underlying_ccy"

    return "ccy"


def _build_override_resolution(
    *,
    ticker: Any,
    resolution_reason: Any = "",
    reason: Any = "",
    resolution_method: Any = "",
    method: Any = "",
    source: str,
    isin: Any = "",
) -> ym.OverrideResolution:
    return ym.OverrideResolution(
        ticker=yu.clean_str(ticker),
        reason=yu.clean_str(resolution_reason or reason) or "override",
        method=yu.clean_str(resolution_method or method) or "override",
        source=source,
        isin=yu.clean_str(isin).upper(),
    )


def load_chosen_map(path: str) -> dict[str, ym.OverrideResolution]:
    df = _normalise_chosen_map_df(path)
    if df.empty:
        return {}

    ccy_col = _pick_ccy_column(df)
    out: dict[str, ym.OverrideResolution] = {}

    for row in df.itertuples(index=False):
        underlying = yu.clean_str(getattr(row, "underlying", ""))
        underlying_ccy = yu.normalise_ccy_safe(getattr(row, ccy_col, ""))
        chosen_ticker = yu.clean_str(getattr(row, "chosen_ticker", ""))

        if not underlying or not underlying_ccy or not chosen_ticker:
            continue

        out[yu.map_key(underlying, underlying_ccy)] = _build_override_resolution(
            ticker=getattr(row, "chosen_ticker", ""),
            resolution_reason=getattr(row, "resolution_reason", ""),
            reason=getattr(row, "reason", ""),
            resolution_method=getattr(row, "resolution_method", ""),
            method=getattr(row, "method", ""),
            source="chosen_map",
            isin=getattr(row, "isin", ""),
        )

    return out


def resolve_override_for_row(
    row: Any,
    *,
    row_ctx: ym.RowContext,
    chosen_map_cache: dict[str, ym.OverrideResolution],
) -> ym.OverrideResolution:
    cached = chosen_map_cache.get(row_ctx.map_key)
    if cached is not None:
        return cached

    row_ticker = yu.clean_str(getattr(row, "chosen_ticker", ""))
    if not row_ticker:
        return _empty_override_resolution()

    return _build_override_resolution(
        ticker=getattr(row, "chosen_ticker", ""),
        resolution_reason=getattr(row, "resolution_reason", ""),
        reason=getattr(row, "reason", ""),
        resolution_method=getattr(row, "resolution_method", ""),
        method=getattr(row, "method", ""),
        source="row_override",
        isin=getattr(row, "isin", ""),
    )