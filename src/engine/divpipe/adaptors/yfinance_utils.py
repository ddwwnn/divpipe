# src/engine/divpipe/adaptors/yfinance_utils.py

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Mapping

import pandas as pd

from engine.divpipe.utils.ccy import normalise_ccy

from . import yfinance_models as ym


_BAD_SYMBOL_CHARS = re.compile(r"[\s\$\*]")
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_STRICT_ISIN_SG_TICKER_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]\.SG$")
_AMOUNT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")

_EMPTY_TEXT_VALUES = {"", "nan", "none", "<na>"}
_FAST_INFO_KEYS = ("currency", "exchange", "quoteType", "timezone", "lastPrice", "previousClose")
_INFO_KEYS = ("symbol", "exchange", "quoteType", "currency", "market", "regularMarketPrice")
_MISSING_MAPPING_VALUES = (None, "", [], {}, 0)


def sanitise_symbol(sym: str) -> str:
    text = (sym or "").strip()
    return _BAD_SYMBOL_CHARS.sub("", text)


def normalise_ticker_key(ticker: str) -> str:
    return sanitise_symbol(ticker).upper()


def clean_str(x: Any) -> str:
    if x is None:
        return ""

    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass

    text = str(x).strip()
    return "" if text.lower() in _EMPTY_TEXT_VALUES else text


def normalise_ccy_safe(x: Any) -> str:
    ccy = normalise_ccy(x)
    return "" if pd.isna(ccy) else str(ccy)


def map_key(underlying: str, ccy: str) -> str:
    underlying_text = str(underlying or "").strip()
    ccy_text = normalise_ccy_safe(ccy)
    return f"{underlying_text}|{ccy_text}"


def parse_amount(x: Any) -> float:
    if x is None:
        raise ValueError("amount is None")

    if isinstance(x, (int, float)):
        if pd.isna(x):
            raise ValueError("amount is NaN")
        return float(x)

    text = str(x).strip()
    normalised = (
        text.replace(",", "")
        .replace("$", "")
        .replace("USD", "")
        .strip()
    )

    if not _AMOUNT_RE.fullmatch(normalised):
        raise ValueError(f"cannot parse amount from: {text!r}")

    return float(normalised)


def parse_optional_float(x: Any) -> float | None:
    text = clean_str(x)
    if not text:
        return None

    try:
        value = float(text)
    except (TypeError, ValueError):
        return None

    return None if pd.isna(value) else value


def parse_yyyymmdd(s: str | None) -> pd.Timestamp | None:
    text = (s or "").strip()
    if not text:
        return None
    return pd.to_datetime(text, format="%Y%m%d", errors="raise")


def unix_ts_floor(ts: pd.Timestamp | None) -> int:
    if ts is None:
        return 0
    return int(pd.Timestamp(ts).timestamp())


def unix_ts_ceil_exclusive(ts: pd.Timestamp | None) -> int:
    if ts is None:
        return int(pd.Timestamp.now("UTC").timestamp())
    return int((pd.Timestamp(ts) + pd.Timedelta(days=1)).timestamp())


def extract_isin_prefix(isin: str) -> str:
    text = clean_str(isin).upper().replace(" ", "")
    if len(text) >= 2 and text[:2].isalpha():
        return text[:2]
    return ""


def derive_listing_market_from_ticker(
    ticker: str,
    *,
    unsupported_ticker_prefix: str = "UNSUPPORTED_",
) -> str:
    text = str(ticker or "").strip().upper()
    if not text:
        return ""

    if text.startswith(unsupported_ticker_prefix):
        return ""

    if "." not in text:
        return ""

    return text.rsplit(".", 1)[-1]


def is_strict_isin_sg_ticker(ticker: str) -> bool:
    return bool(_STRICT_ISIN_SG_TICKER_RE.fullmatch(ticker))


def looks_like_isin(x: Any) -> bool:
    text = str(x or "").strip().upper().replace(" ", "")
    if not text:
        return False
    return bool(_ISIN_RE.fullmatch(text))


def looks_like_yfinance_string_dtype_bug(exc: Exception) -> bool:
    return isinstance(exc, TypeError) and "Invalid value '0' for dtype 'str'" in str(exc)


def sleep_with_jitter(base_delay_sec: float, jitter_ratio: float) -> None:
    if base_delay_sec <= 0:
        return

    lower = max(0.0, 1.0 - jitter_ratio)
    upper = 1.0 + jitter_ratio
    time.sleep(base_delay_sec * random.uniform(lower, upper))


def cache_get(
    cache: dict[ym.K, ym.V],
    key: ym.K,
    lock: threading.Lock,
) -> tuple[bool, ym.V | None]:
    with lock:
        if key in cache:
            return True, cache[key]
    return False, None


def cache_set(
    cache: dict[ym.K, ym.V],
    key: ym.K,
    value: ym.V,
    lock: threading.Lock,
) -> None:
    with lock:
        cache[key] = value


def serialise_candidates_json(candidates: list[str]) -> str:
    return json.dumps([str(x) for x in candidates], ensure_ascii=False)


def candidate_count(candidates: list[str]) -> int:
    return sum(1 for candidate in candidates if str(candidate).strip())


def is_plain_ticker(ticker: str) -> bool:
    return bool(ticker) and "." not in ticker


def is_local_ticker(ticker: str) -> bool:
    return bool(ticker) and "." in ticker


def quiet_call(fn):
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            return fn()


def _count_present_mapping_values(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> int:
    return sum(1 for key in keys if mapping.get(key) not in _MISSING_MAPPING_VALUES)


def _count_present_getter_values(getter, keys: tuple[str, ...]) -> int:
    present = 0

    for key in keys:
        try:
            value = getter(key)
        except Exception:
            value = None

        if value not in _MISSING_MAPPING_VALUES:
            present += 1

    return present


def has_strong_fast_info_signal(ticker_obj: Any) -> bool:
    try:
        fast_info = getattr(ticker_obj, "fast_info", None)
        if fast_info is None:
            return False

        getter = getattr(fast_info, "get", None)
        if getter is None:
            return False

        return _count_present_getter_values(getter, _FAST_INFO_KEYS) >= 2
    except Exception:
        return False


def has_strong_info_signal(ticker_obj: Any) -> bool:
    try:
        info = getattr(ticker_obj, "info", None)
        if not isinstance(info, dict) or not info:
            return False

        return _count_present_mapping_values(info, _INFO_KEYS) >= 2
    except Exception:
        return False


def find_candidate_by_ticker(
    candidates: list[ym.Candidate],
    ticker: str,
) -> ym.Candidate | None:
    if not ticker:
        return None

    for candidate in candidates:
        if candidate.yfinance_ticker == ticker:
            return candidate

    return None