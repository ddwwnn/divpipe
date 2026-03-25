# src/engine/divpipe/schema/canonical.py

from __future__ import annotations

import logging
from typing import Callable, Literal

import pandas as pd

from .columns import CANON_COLUMNS, COLUMN_SPECS, ColType, ColumnSpec

logger = logging.getLogger(__name__)

ActionType = Literal["cash_dividend", "stock_dividend", "interest_on_capital", "capital_reduction", "unknown"]
PeriodType = Literal["final", "interim", "quarterly", "special", "unknown"]
ShareClass = Literal["common", "preferred", "class_a", "class_b", "unknown"]
AmountType = Literal["per_share", "total", "unknown"]

VALID_LITERAL_VALUES: dict[str, set[str]] = {
    "action_type": {
        "cash_dividend",
        "stock_dividend",
        "interest_on_capital",
        "capital_reduction",
        "unknown",
    },
    "period_type": {
        "final",
        "interim",
        "quarterly",
        "special",
        "unknown",
    },
    "share_class": {
        "common",
        "preferred",
        "class_a",
        "class_b",
        "unknown",
    },
    "amount_type": {
        "per_share",
        "total",
        "unknown",
    },
}


def _clean_string(
    s: pd.Series,
    *,
    upper: bool = False,
    strip_spaces: bool = True,
    remove_spaces: bool = False,
) -> pd.Series:
    x = s.astype("string").fillna("")
    if strip_spaces:
        x = x.str.strip()
    if upper:
        x = x.str.upper()
    if remove_spaces:
        x = x.str.replace(" ", "", regex=False)
    return x


def _normalise_literal_series(s: pd.Series) -> pd.Series:
    return s.astype("string").fillna("").str.strip().str.lower()


def _handle_numeric(series: pd.Series, spec: ColumnSpec) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if spec.coerce_int:
        out = out.astype("Int64")
    return out


def _handle_string_like(series: pd.Series, spec: ColumnSpec) -> pd.Series:
    return _clean_string(
        series,
        upper=spec.upper,
        strip_spaces=spec.strip,
        remove_spaces=spec.remove_spaces,
    )


_COLUMN_HANDLERS: dict[ColType, Callable[[pd.Series, ColumnSpec], pd.Series]] = {
    ColType.NUMERIC: _handle_numeric,
    ColType.STRING: _handle_string_like,
    ColType.ID: _handle_string_like,
    ColType.DATE: _handle_string_like,
}


def validate_literals(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    target_cols = set(VALID_LITERAL_VALUES.keys()) & set(out.columns)

    for col in target_cols:
        valid_values = VALID_LITERAL_VALUES[col]
        norm = _normalise_literal_series(out[col])
        invalid_mask = norm.ne("") & ~norm.isin(valid_values)

        if bool(invalid_mask.any()):
            logger.warning(
                "Canonical literal validation: column=%s invalid_count=%s -> coerced to 'unknown'",
                col,
                int(invalid_mask.sum()),
            )

        out[col] = norm.where(~invalid_mask, "unknown")

    return out


def _apply_column_spec(series: pd.Series, col: str) -> pd.Series:
    spec = COLUMN_SPECS[col]
    handler = _COLUMN_HANDLERS[spec.dtype]
    return handler(series, spec)


def enforce_canonical_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.reindex(columns=CANON_COLUMNS).copy()

    for col in CANON_COLUMNS:
        out[col] = _apply_column_spec(out[col], col)

    out = validate_literals(out)
    return out