# src/engine/divpipe/pipeline/venue_policy.py

from __future__ import annotations

import json
import logging
import re
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

POLICY_BUCKET_CLEAN = "clean"
POLICY_BUCKET_UNSUPPORTED = "unsupported"
POLICY_BUCKET_COVERAGE_LIMITED_REVIEW = "coverage_limited_review"
POLICY_BUCKET_CANDIDATE_AMBIGUITY_REVIEW = "candidate_ambiguity_review"
POLICY_BUCKET_VENUE_PRECEDENCE_REVIEW = "venue_precedence_review"
POLICY_BUCKET_VENUE_POLICY_REVIEW = "venue_policy_review"
POLICY_BUCKET_GENERIC_REVIEW = "generic_review"

POLICY_REASON_NONE = "none"
POLICY_REASON_RU_LOCAL_UNSUPPORTED = "ru_local_unsupported"
POLICY_REASON_UAE_SYMBOL_POLICY_GAP = "uae_symbol_policy_gap"
POLICY_REASON_PS_COVERAGE_LIMITED = "ps_coverage_limited"
POLICY_REASON_NS_BO_DUAL_LISTING = "ns_bo_dual_listing"
POLICY_REASON_UNCLASSIFIED_NO_DIV = "unclassified_no_div"

_NO_DIV_STATUSES = {
    "VERIFIED_EXISTS_BUT_NO_DIVIDENDS",
    "CANDIDATE_UNVERIFIED",
    "TICKER_NOT_FOUND",
}

_RU_LOCAL_SUFFIXES = (
    ".ME",
    ".MOEX",
    ".RM",
)

_RU_NON_LOCAL_SUFFIXES = (
    ".L",
    ".US",
    ".N",
    ".O",
    ".K",
    ".SW",
    ".DE",
    ".F",
)

_UAE_SUFFIXES = (
    ".AD",
    ".AB",
    ".DU",
)

_PS_SUFFIXES = (
    ".PS",
)

_NS_SUFFIXES = (
    ".NS",
)

_BO_SUFFIXES = (
    ".BO",
)

_RU_COUNTRY_TOKENS = (
    "RUSSIA",
    "RUSSIAN FEDERATION",
)

_RU_EXCHANGE_TOKENS = (
    "MOEX",
    "MOSCOW",
    "STANDARD-CLASSICA-FORTS",
    "FORTS",
)

_UAE_COUNTRY_TOKENS = (
    "UNITED ARAB EMIRATES",
    "UAE",
)

_UAE_EXCHANGE_TOKENS = (
    "ABU DHABI",
    "ADX",
    "DUBAI",
    "DFM",
)

_PS_COUNTRY_TOKENS = (
    "PHILIPPINES",
)

_PS_EXCHANGE_TOKENS = (
    "PHILIPP",
    "PSE",
)

_JSON_ARRAY_RE = re.compile(r"^\s*\[.*\]\s*$")
_SPLIT_RE = re.compile(r"\s*,\s*")


def _empty_string_series(df: pd.DataFrame) -> pd.Series:
    return pd.Series("", index=df.index, dtype="string")


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _require_any_column_group(
    df: pd.DataFrame,
    groups: dict[str, tuple[str, ...]],
) -> None:
    missing_groups: dict[str, tuple[str, ...]] = {}

    for group_name, candidates in groups.items():
        if not any(col in df.columns for col in candidates):
            missing_groups[group_name] = candidates

    if missing_groups:
        details = ", ".join(
            f"{group_name}={list(candidates)}"
            for group_name, candidates in missing_groups.items()
        )
        raise ValueError(f"Missing required column group(s): {details}")


def _normalise_string_series(series: pd.Series | None, *, upper: bool = True) -> pd.Series:
    if series is None:
        return pd.Series(dtype="string")

    out = series.astype("string").fillna("").str.strip()
    if upper:
        out = out.str.upper()
    return out


def _first_present_series(df: pd.DataFrame, columns: Iterable[str], *, upper: bool = True) -> pd.Series:
    for col in columns:
        if col in df.columns:
            return _normalise_string_series(df[col], upper=upper)
    return _empty_string_series(df)


def _contains_any_token(series: pd.Series, tokens: Iterable[str]) -> pd.Series:
    token_list = [str(token).strip().upper() for token in tokens if str(token).strip()]
    if not token_list:
        return pd.Series(False, index=series.index)

    out = pd.Series(False, index=series.index)
    for token in token_list:
        out = out | series.str.contains(re.escape(token), regex=True, na=False)
    return out


def _endswith_any_suffix(series: pd.Series, suffixes: Iterable[str]) -> pd.Series:
    suffix_list = tuple(str(suffix).strip().upper() for suffix in suffixes if str(suffix).strip())
    if not suffix_list:
        return pd.Series(False, index=series.index)
    return series.str.endswith(suffix_list, na=False)


def _split_candidates(raw: object) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            text = str(item).strip().upper()
            if text:
                out.append(text)
        return out

    text = str(raw).strip()
    if not text:
        return []

    if _JSON_ARRAY_RE.match(text):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                out = []
                for item in parsed:
                    item_text = str(item).strip().upper()
                    if item_text:
                        out.append(item_text)
                return out
        except Exception:
            pass

    trimmed = text.strip("[](){}")
    if not trimmed:
        return []

    parts = _SPLIT_RE.split(trimmed)
    out = []
    for part in parts:
        item = part.strip().strip("'").strip('"').strip("() ").upper()
        if item:
            out.append(item)
    return out


def _candidate_series(df: pd.DataFrame) -> pd.Series:
    if "candidates_json" in df.columns:
        raw = df["candidates_json"]
    elif "candidates" in df.columns:
        raw = df["candidates"]
    else:
        return pd.Series([[] for _ in range(len(df))], index=df.index, dtype="object")

    return raw.map(_split_candidates)


def _candidate_has_any_suffix(candidate_series: pd.Series, suffixes: Iterable[str]) -> pd.Series:
    suffix_list = tuple(str(suffix).strip().upper() for suffix in suffixes if str(suffix).strip())
    if not suffix_list:
        return pd.Series(False, index=candidate_series.index)

    return candidate_series.map(
        lambda items: any(str(item).upper().endswith(suffix_list) for item in items)
    )


def annotate_policy_columns(df: pd.DataFrame) -> pd.DataFrame:
    _require_columns(df, ["status", "isin"])
    _require_any_column_group(
        df,
        {
            "ticker_source": ("chosen_ticker", "exists_ticker"),
            "candidate_source": ("candidates_json", "candidates"),
            "country_source": ("country", "candidate_country"),
            "exchange_source": ("exchange", "candidate_exchange"),
        },
    )

    out = df.copy()

    status = _first_present_series(out, ["status"])
    country = _first_present_series(out, ["country", "candidate_country"])
    exchange = _first_present_series(out, ["exchange", "candidate_exchange"])
    isin = _first_present_series(out, ["isin"])
    chosen_ticker = _first_present_series(out, ["chosen_ticker", "exists_ticker"], upper=True)
    exists_ticker = _first_present_series(out, ["exists_ticker"], upper=True)

    if "candidate_count" in out.columns:
        candidate_count = pd.to_numeric(out["candidate_count"], errors="coerce").fillna(0)
    else:
        candidate_count = pd.Series(0, index=out.index, dtype="float64")
        sample_underlyings: list[str] = []
        if "underlying" in out.columns:
            sample_underlyings = (
                out["underlying"]
                .astype("string")
                .fillna("")
                .loc[lambda s: s.ne("")]
                .head(5)
                .tolist()
            )

        logger.warning(
            "candidate_count missing; defaulting to 0 for all rows rows=%s sample_underlyings=%s",
            len(out),
            sample_underlyings,
        )

    candidates = _candidate_series(out)

    no_div_like = status.isin(_NO_DIV_STATUSES)

    chosen_is_ru_local = _endswith_any_suffix(chosen_ticker, _RU_LOCAL_SUFFIXES)
    chosen_is_ru_non_local = _endswith_any_suffix(chosen_ticker, _RU_NON_LOCAL_SUFFIXES)
    candidates_have_ru_local = _candidate_has_any_suffix(candidates, _RU_LOCAL_SUFFIXES)
    candidates_have_ru_non_local = _candidate_has_any_suffix(candidates, _RU_NON_LOCAL_SUFFIXES)

    ru_country_case = (
        _contains_any_token(country, _RU_COUNTRY_TOKENS)
        | _contains_any_token(exchange, _RU_EXCHANGE_TOKENS)
        | isin.str.startswith("RU", na=False)
    )

    ru_local_case = (
        no_div_like
        & ru_country_case
        & (
            chosen_is_ru_local
            | candidates_have_ru_local
            | (~chosen_is_ru_non_local & ~candidates_have_ru_non_local)
        )
    )

    uae_country_case = (
        _contains_any_token(country, _UAE_COUNTRY_TOKENS)
        | _contains_any_token(exchange, _UAE_EXCHANGE_TOKENS)
    )
    chosen_is_uae = _endswith_any_suffix(chosen_ticker, _UAE_SUFFIXES)
    candidates_have_uae = _candidate_has_any_suffix(candidates, _UAE_SUFFIXES)
    uae_policy_gap = no_div_like & uae_country_case & (chosen_is_uae | candidates_have_uae)

    ps_country_case = (
        _contains_any_token(country, _PS_COUNTRY_TOKENS)
        | _contains_any_token(exchange, _PS_EXCHANGE_TOKENS)
    )
    chosen_is_ps = _endswith_any_suffix(chosen_ticker, _PS_SUFFIXES)
    candidates_have_ps = _candidate_has_any_suffix(candidates, _PS_SUFFIXES)
    ps_coverage_limited = no_div_like & ps_country_case & (chosen_is_ps | candidates_have_ps)


    chosen_is_ns = _endswith_any_suffix(chosen_ticker, _NS_SUFFIXES)
    chosen_is_bo = _endswith_any_suffix(chosen_ticker, _BO_SUFFIXES)
    candidates_have_ns = _candidate_has_any_suffix(candidates, _NS_SUFFIXES)
    candidates_have_bo = _candidate_has_any_suffix(candidates, _BO_SUFFIXES)
    ns_bo_dual_listing_case = (
        no_div_like
        & (candidate_count > 1)
        & (
            (chosen_is_ns & candidates_have_bo)
            | (chosen_is_bo & candidates_have_ns)
            | (candidates_have_ns & candidates_have_bo)
        )
    )

    unresolved_exists_gap = no_div_like & (
        chosen_ticker.eq("")
        | ((candidate_count > 1) & ~ns_bo_dual_listing_case)
        | (
            status.eq("VERIFIED_EXISTS_BUT_NO_DIVIDENDS")
            & exists_ticker.eq("")
        )
    )

    out["policy_bucket"] = POLICY_BUCKET_CLEAN
    out["policy_reason"] = POLICY_REASON_NONE

    out.loc[ru_local_case, "policy_bucket"] = POLICY_BUCKET_UNSUPPORTED
    out.loc[ru_local_case, "policy_reason"] = POLICY_REASON_RU_LOCAL_UNSUPPORTED

    out.loc[uae_policy_gap, "policy_bucket"] = POLICY_BUCKET_VENUE_POLICY_REVIEW
    out.loc[uae_policy_gap, "policy_reason"] = POLICY_REASON_UAE_SYMBOL_POLICY_GAP

    out.loc[ps_coverage_limited, "policy_bucket"] = POLICY_BUCKET_COVERAGE_LIMITED_REVIEW
    out.loc[ps_coverage_limited, "policy_reason"] = POLICY_REASON_PS_COVERAGE_LIMITED

    out.loc[ns_bo_dual_listing_case, "policy_bucket"] = POLICY_BUCKET_VENUE_PRECEDENCE_REVIEW
    out.loc[ns_bo_dual_listing_case, "policy_reason"] = POLICY_REASON_NS_BO_DUAL_LISTING

    generic_review_case = (
        no_div_like
        & out["policy_bucket"].eq(POLICY_BUCKET_CLEAN)
        & unresolved_exists_gap
    )
    out.loc[generic_review_case, "policy_bucket"] = POLICY_BUCKET_GENERIC_REVIEW
    out.loc[generic_review_case, "policy_reason"] = POLICY_REASON_UNCLASSIFIED_NO_DIV

    out["policy_bucket"] = out["policy_bucket"].astype("category")
    out["policy_reason"] = out["policy_reason"].astype("category")

    return out