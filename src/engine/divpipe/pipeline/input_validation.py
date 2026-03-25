# src/engine/divpipe/pipeline/input_validation.py

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

_NULL_LIKE_UNDERLYING = {
    "",
    "-",
    "--",
    "N/A",
    "NA",
    "NONE",
    "NULL",
    "NAN",
    "<NA>",
}

_ALLOWED_UNDERLYING_RE = re.compile(r"^[A-Z0-9.\-_/]+$")


@dataclass(frozen=True)
class UnderlyingValidationResult:
    raw_value: str
    normalised_value: str
    is_valid: bool
    reason: str


def normalise_underlying_text(x: Any) -> str:
    s = str(x or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def validate_underlying_value(x: Any) -> UnderlyingValidationResult:
    raw = "" if x is None else str(x)
    s = normalise_underlying_text(x)

    if not s:
        return UnderlyingValidationResult(raw, "", False, "blank_underlying")

    if s in _NULL_LIKE_UNDERLYING:
        return UnderlyingValidationResult(raw, s, False, "placeholder_underlying")

    if not any(ch.isalnum() for ch in s):
        return UnderlyingValidationResult(raw, s, False, "non_symbol_underlying")

    if not _ALLOWED_UNDERLYING_RE.fullmatch(s):
        return UnderlyingValidationResult(raw, s, False, "invalid_underlying_format")

    return UnderlyingValidationResult(raw, s, True, "")


def split_valid_and_rejected_universe(universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if universe is None or universe.empty:
        return universe.copy(), pd.DataFrame(
            columns=[
                "source",
                "underlying_raw",
                "underlying_normalised",
                "underlying_ccy",
                "isin",
                "reason",
                "holdings_tag",
                "holdings_file",
            ]
        )

    out = universe.copy()

    results = out["underlying"].map(validate_underlying_value)
    out["_underlying_raw"] = [r.raw_value for r in results]
    out["_underlying_normalised"] = [r.normalised_value for r in results]
    out["_underlying_is_valid"] = [r.is_valid for r in results]
    out["_underlying_reason"] = [r.reason for r in results]

    valid = out.loc[out["_underlying_is_valid"]].copy()
    valid["underlying"] = valid["_underlying_normalised"]

    rejected = out.loc[~out["_underlying_is_valid"]].copy()
    rejected = rejected.rename(
        columns={
            "_underlying_raw": "underlying_raw",
            "_underlying_normalised": "underlying_normalised",
            "_underlying_reason": "reason",
        }
    )

    for col in ["underlying_ccy", "isin", "holdings_tag", "holdings_file"]:
        if col not in rejected.columns:
            rejected[col] = ""

    rejected["source"] = "input_validation"

    rejected = rejected[
        [
            "source",
            "underlying_raw",
            "underlying_normalised",
            "underlying_ccy",
            "isin",
            "reason",
            "holdings_tag",
            "holdings_file",
        ]
    ].reset_index(drop=True)

    valid = valid.drop(
        columns=[
            "_underlying_raw",
            "_underlying_normalised",
            "_underlying_is_valid",
            "_underlying_reason",
        ],
        errors="ignore",
    ).reset_index(drop=True)

    return valid, rejected