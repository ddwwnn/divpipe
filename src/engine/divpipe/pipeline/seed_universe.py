# src/engine/divpipe/pipeline/seed_universe.py

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# Conservative: allow only symbols that look like tickers / codes.
_ALLOWED_UNDERLYING = re.compile(r"^[0-9A-Za-z.\-_=]+$")

# If holdings is polluted with currency codes as "underlying" (e.g., HKD, KRW),
# drop those rows to avoid yfinance noise like "HKD.HK", "KRW.KS", etc.
_CCY_LIKE = {
    "HKD",
    "KRW",
    "TWD",
    "INR",
    "JPY",
    "CNY",
    "CNH",
    "USD",
    "EUR",
    "BRL",
    "THB",
    "COP",
    "HUF",
    "MYR",
    "EGP",
    "ZAR",
    "SAR",
    "QAR",
    "KWD",
    "PLN",
    "TRY",
    "PHP",
    "CLP",
    "CZK",
    "MXN",
}

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def load_holdings(path: Path, *, include_zero_weight: bool = False) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        dtype={
            "underlying": "string",
            "underlying_ccy": "string",
            "weight": "float64",
        },
        encoding="utf-8-sig",
    )

    df.columns = [str(c).strip() for c in df.columns]

    rename: dict[str, str] = {}
    for c in df.columns:
        cl = c.strip().lower()

        if cl in {"isin", "isin_code", "isincode", "isin code"}:
            rename[c] = "isin"

        if cl in {"ticker", "symbol"} and "underlying" not in df.columns:
            rename[c] = "underlying"

        if cl in {"ccy", "currency"} and "underlying_ccy" not in df.columns:
            rename[c] = "underlying_ccy"

        if cl in {"country", "country_code", "country code"} and "country" not in df.columns:
            rename[c] = "country"

        if cl in {"exchange", "exchange_code", "exchange code"} and "exchange" not in df.columns:
            rename[c] = "exchange"

        if cl in {"location"} and "location" not in df.columns:
            rename[c] = "location"

        if cl in {"coverage"} and "coverage" not in df.columns:
            rename[c] = "coverage"

    if rename:
        df = df.rename(columns=rename)

    required = {"underlying", "underlying_ccy"}
    if not required.issubset(set(df.columns)):
        raise ValueError("holdings must include columns: underlying, underlying_ccy")

    df["underlying"] = df["underlying"].astype("string").fillna("").str.strip()
    df["underlying_ccy"] = df["underlying_ccy"].astype("string").fillna("").str.strip().str.upper()

    if "isin" in df.columns:
        df["isin"] = (
            df["isin"]
            .astype("string")
            .fillna("")
            .str.strip()
            .str.upper()
            .str.replace(" ", "", regex=False)
        )
        df.loc[~df["isin"].str.match(_ISIN_RE, na=False), "isin"] = ""

    for col in ["country", "exchange", "location", "coverage"]:
        if col in df.columns:
            df[col] = df[col].astype("string").fillna("").str.strip()

    if "weight" in df.columns:
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
    else:
        df["weight"] = 1.0

    bad_len = df["underlying"].str.len() > 32
    bad_chars = ~df["underlying"].str.match(_ALLOWED_UNDERLYING)
    missing = df["underlying"].eq("") | df["underlying"].str.lower().eq("nan")
    ccy_as_underlying = df["underlying"].str.upper().isin(_CCY_LIKE)

    df["_is_bad_symbol"] = bad_len | bad_chars | missing | ccy_as_underlying

    cleaned = df.loc[~df["_is_bad_symbol"]].copy()
    cleaned = cleaned.drop(columns=["_is_bad_symbol"], errors="ignore")

    if not include_zero_weight:
        cleaned = cleaned.loc[cleaned["weight"] > 0].copy()

    return cleaned.reset_index(drop=True)


def build_universe(holdings: pd.DataFrame) -> pd.DataFrame:
    cols = ["underlying", "underlying_ccy"]

    for optional_col in ["isin", "weight", "exchange", "country", "location", "coverage"]:
        if optional_col in holdings.columns and optional_col not in cols:
            cols.append(optional_col)

    return holdings[cols].drop_duplicates().copy()