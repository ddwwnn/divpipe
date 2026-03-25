# src/engine/divpipe/adaptors/yfinance_rows.py

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from engine.divpipe.schema.columns import (
    DISCOVERED_CANDIDATE_LEGACY_COLUMNS,
    DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
    STAGE1_ERRORS_REQUIRED_COLUMNS,
    STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
)

from . import yfinance_models as ym
from . import yfinance_utils as yu


_ISIN_PREFIX_TO_EXCHANGE_SUFFIXES: dict[str, set[str]] = {
    "AU": {"AX"},
    "BR": {"SA"},
    "CH": {"SW", "VX", "XC"},
    "DE": {"DE", "F", "BE", "DU", "HM", "MU", "SG"},
    "DK": {"CO"},
    "EG": {"CA"},
    "GB": {"L"},
    "HK": {"HK"},
    "ID": {"JK"},
    "IL": {"TA"},
    "IN": {"NS", "BO"},
    "JP": {"T"},
    "MX": {"MX"},
    "NL": {"AS"},
    "PH": {"PS"},
    "SA": {"SR"},
    "SE": {"ST"},
    "TW": {"TW"},
    "US": {"NASDAQ", "NYSE", "AMEX"},
    "ZA": {"JO"},
}

_CANDIDATE_DEFAULT_COLUMNS: dict[str, Any] = {
    "candidates": "",
    "candidates_json": "",
    "candidate_count": 0,
}

_DISCOVERED_LEGACY_DEFAULT_COLUMNS: dict[str, Any] = {
    "exists_ns": False,
    "exists_bo": False,
}

_EXCHANGE_TOKEN_RE = re.compile(r"[A-Z0-9]+")
_DEFAULT_YFINANCE_CONFIDENCE = 35


def _tokenise_exchange_text(text: str) -> set[str]:
    exchange_u = yu.clean_str(text).upper()
    if not exchange_u:
        return set()
    return set(_EXCHANGE_TOKEN_RE.findall(exchange_u))


def _derive_legacy_exists_flags(preverified_exists_ticker: str) -> tuple[bool, bool]:
    ticker = yu.normalise_ticker_key(preverified_exists_ticker)
    if not ticker:
        return False, False

    return ticker.endswith(".NS"), ticker.endswith(".BO")


def derive_prefix_exchange_consistency(
    row_isin: str,
    canonical_exchange: str,
) -> bool | None:
    prefix = yu.extract_isin_prefix(row_isin)
    if not prefix:
        return None

    allowed = _ISIN_PREFIX_TO_EXCHANGE_SUFFIXES.get(prefix)
    if not allowed:
        return None

    exchange_tokens = _tokenise_exchange_text(canonical_exchange)
    if not exchange_tokens:
        return None

    return bool(exchange_tokens & allowed)


def _apply_default_columns(
    df: pd.DataFrame,
    defaults: dict[str, Any],
) -> pd.DataFrame:
    for col, default_value in defaults.items():
        if col not in df.columns:
            df[col] = default_value
    return df


def _finalise_stage1_df(
    rows: list[dict[str, Any]],
    *,
    required_columns: list[str] | tuple[str, ...],
    ensure_candidate_defaults: bool,
    ensure_discovered_legacy_defaults: bool = False,
) -> pd.DataFrame:
    df = pd.DataFrame(rows)

    if ensure_candidate_defaults:
        df = _apply_default_columns(df, _CANDIDATE_DEFAULT_COLUMNS)

    if ensure_discovered_legacy_defaults:
        df = _apply_default_columns(df, _DISCOVERED_LEGACY_DEFAULT_COLUMNS)

    ordered_front = list(required_columns)

    if ensure_discovered_legacy_defaults:
        for col in DISCOVERED_CANDIDATE_LEGACY_COLUMNS:
            if col in df.columns and col not in ordered_front:
                ordered_front.append(col)

    ordered = ordered_front + [col for col in df.columns if col not in ordered_front]
    return df.reindex(columns=ordered)


def build_stage1_error_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return _finalise_stage1_df(
        rows,
        required_columns=STAGE1_ERRORS_REQUIRED_COLUMNS,
        ensure_candidate_defaults=True,
    )


def build_stage1_no_div_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return _finalise_stage1_df(
        rows,
        required_columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
        ensure_candidate_defaults=True,
    )


def build_discovered_candidate_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return _finalise_stage1_df(
        rows,
        required_columns=DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
        ensure_candidate_defaults=False,
        ensure_discovered_legacy_defaults=True,
    )


def build_discovered_candidate_row(
    *,
    source: str,
    row_ctx: ym.RowContext,
    row_isin: str,
    chosen_ticker: str,
    candidate_market: str,
    candidate_origin: str,
    resolution_status: str,
    resolution_reason: str,
    resolution_method: str,
    resolution_source: str,
    exists_ticker: str,
    preverified_exists_any: bool,
    preverified_exists_ticker: str,
    candidate_values: list[str],
    start: str,
    end: str,
    guess_source: str,
    canonical_exchange: str,
    isin_prefix: str,
    prefix_exchange_consistent: bool | None,
) -> dict[str, Any]:
    candidate_count = yu.candidate_count(candidate_values)
    candidates_json = yu.serialise_candidates_json(candidate_values)

    preverified_ticker = yu.normalise_ticker_key(preverified_exists_ticker)
    exists_ns, exists_bo = _derive_legacy_exists_flags(preverified_ticker)

    return {
        "source": source,
        "underlying": row_ctx.underlying,
        "underlying_ccy": row_ctx.ccy,
        "isin": row_isin,
        "chosen_ticker": chosen_ticker,
        "candidate_market": candidate_market,
        "candidate_origin": candidate_origin,
        "resolution_status": resolution_status,
        "resolution_reason": resolution_reason,
        "resolution_method": resolution_method,
        "resolution_source": resolution_source,
        "candidate_count": candidate_count,
        "candidates_json": candidates_json,
        "exists_ticker": exists_ticker,
        "preverified_exists_any": bool(preverified_exists_any),
        "preverified_exists_ticker": preverified_ticker,
        "start": start,
        "end": end,
        "guess_source": guess_source,
        "canonical_exchange": canonical_exchange,
        "isin_prefix": isin_prefix,
        "prefix_exchange_consistent": prefix_exchange_consistent,
        # legacy compatibility only
        "exists_ns": exists_ns,
        "exists_bo": exists_bo,
    }


def build_no_div_row(
    *,
    source: str,
    row_ctx: ym.RowContext,
    row_isin: str,
    exists_ticker: str,
    candidates: list[ym.Candidate],
    start: str,
    end: str,
    status: str,
) -> dict[str, Any]:
    candidate_values = [candidate.yfinance_ticker for candidate in candidates]
    candidate_count = yu.candidate_count(candidate_values)
    candidates_json = yu.serialise_candidates_json(candidate_values)

    return {
        "source": source,
        "underlying": row_ctx.underlying,
        "underlying_ccy": row_ctx.ccy,
        "isin": row_isin,
        "status": status,
        "exists_ticker": exists_ticker,
        "candidates": candidate_values,
        "candidates_json": candidates_json,
        "candidate_count": candidate_count,
        "start": start,
        "end": end,
    }


def build_error_row(
    *,
    source: str,
    row_ctx: ym.RowContext,
    row_isin: str,
    error: str,
    candidates: list[ym.Candidate],
    start: str,
    end: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_values = [candidate.yfinance_ticker for candidate in candidates]
    candidate_count = yu.candidate_count(candidate_values)
    candidates_json = yu.serialise_candidates_json(candidate_values)

    row = {
        "source": source,
        "underlying": row_ctx.underlying,
        "underlying_ccy": row_ctx.ccy,
        "isin": row_isin,
        "error": error,
        "candidates": candidate_values,
        "candidates_json": candidates_json,
        "candidate_count": candidate_count,
        "start": start,
        "end": end,
    }
    return row | (extra or {})


def _build_dividend_evidence(
    *,
    row_ctx: ym.RowContext,
    chosen: ym.Candidate,
    chosen_market: str,
    row_isin: str,
    raw_amount: Any,
    candidate_values: list[str],
) -> str:
    evidence = {
        "date_semantics": "yfinance_history_actions_dividends",
        "raw_amount": str(raw_amount),
        "weight": row_ctx.weight,
        "input_name": row_ctx.name,
        "input_exchange": row_ctx.exchange,
        "input_isin": row_isin,
        "resolution": {
            "method": chosen.method,
            "source": chosen.origin,
            "market": chosen_market,
            "guess_source": chosen.guess_source,
            "canonical_exchange": chosen.canonical_exchange,
            "isin_prefix": chosen.isin_prefix,
            "prefix_exchange_consistent": chosen.prefix_exchange_consistent,
        },
        "candidates": {
            "values": candidate_values,
            "count": yu.candidate_count(candidate_values),
        },
    }

    return json.dumps(evidence, ensure_ascii=False)


def _build_dividend_row(
    *,
    source: str,
    row_ctx: ym.RowContext,
    row_isin: str,
    chosen_ticker: str,
    chosen_market: str,
    ex_date: str,
    amount: float,
    raw_amount: Any,
    chosen: ym.Candidate,
    candidate_values: list[str],
    asof_eff: str,
    ingest_ts: str,
) -> dict[str, Any]:
    source_event_key = f"{chosen_ticker}|{row_ctx.ccy}|{ex_date}"

    return {
        "economic_event_id": "",
        "vendor_event_id": "",
        "source": source,
        "source_event_key": source_event_key,
        "underlying": row_ctx.underlying,
        "isin": row_isin,
        "market": chosen_market,
        "currency": row_ctx.ccy,
        "yfinance_ticker": chosen_ticker,
        "action_type": "cash_dividend",
        "period_type": "unknown",
        "share_class": "unknown",
        "status": "historical",
        "declared_date": "",
        "ex_date": ex_date,
        "record_date": "",
        "pay_date": "",
        "amount": amount,
        "amount_type": "per_share",
        "amount_ccy": row_ctx.ccy,
        "confidence": _DEFAULT_YFINANCE_CONFIDENCE,
        "evidence_json": _build_dividend_evidence(
            row_ctx=row_ctx,
            chosen=chosen,
            chosen_market=chosen_market,
            row_isin=row_isin,
            raw_amount=raw_amount,
            candidate_values=candidate_values,
        ),
        "asof_date": asof_eff,
        "ingest_ts": ingest_ts,
    }


def build_dividend_rows(
    *,
    source: str,
    row_ctx: ym.RowContext,
    row_isin: str,
    chosen: ym.Candidate,
    div: pd.Series,
    candidates: list[ym.Candidate],
    start: str,
    end: str,
    asof_eff: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errs: list[dict[str, Any]] = []

    chosen_ticker = yu.normalise_ticker_key(chosen.yfinance_ticker)
    chosen_market = yu.derive_listing_market_from_ticker(chosen_ticker) or str(chosen.market or "").strip().upper()
    ingest_ts = pd.Timestamp.utcnow().isoformat()
    candidate_values = [candidate.yfinance_ticker for candidate in candidates]

    for dt, amt in div.items():
        ex_date = pd.Timestamp(dt).date().isoformat()

        try:
            amount = yu.parse_amount(amt)
        except Exception as exc:
            errs.append(
                build_error_row(
                    source=source,
                    row_ctx=row_ctx,
                    row_isin=row_isin,
                    error="bad_amount",
                    candidates=candidates,
                    start=start,
                    end=end,
                    extra={
                        "yfinance_ticker": chosen_ticker,
                        "ex_date": ex_date,
                        "raw_amount": str(amt),
                        "exception": str(exc),
                    },
                )
            )
            continue

        rows.append(
            _build_dividend_row(
                source=source,
                row_ctx=row_ctx,
                row_isin=row_isin,
                chosen_ticker=chosen_ticker,
                chosen_market=chosen_market,
                ex_date=ex_date,
                amount=amount,
                raw_amount=amt,
                chosen=chosen,
                candidate_values=candidate_values,
                asof_eff=asof_eff,
                ingest_ts=ingest_ts,
            )
        )

    return rows, errs


def build_worker_exception_error_row(
    *,
    source: str,
    row: Any,
    start: str,
    end: str,
    exc: Exception,
) -> dict[str, Any]:
    return {
        "source": source,
        "underlying": yu.clean_str(getattr(row, "underlying", "")),
        "underlying_ccy": yu.normalise_ccy_safe(getattr(row, "underlying_ccy", "")),
        "isin": yu.clean_str(getattr(row, "isin", "")).upper(),
        "error": "worker_exception",
        "candidates": [],
        "candidates_json": "[]",
        "candidate_count": 0,
        "start": start,
        "end": end,
        "exception_type": type(exc).__name__,
        "exception": str(exc),
    }