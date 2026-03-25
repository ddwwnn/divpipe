# src/engine/divpipe/adaptors/yfinance_http.py

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from . import yfinance_utils as yu

logger = logging.getLogger(__name__)


def http_get_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        logger.warning(
            "HTTP error: url=%s status=%s reason=%s",
            url,
            exc.code,
            exc.reason,
        )
        raise
    except (URLError, TimeoutError) as exc:
        logger.warning(
            "Transport error: url=%s error_type=%s error=%s",
            url,
            type(exc).__name__,
            exc,
        )
        raise
    except Exception as exc:
        logger.warning(
            "Unexpected transport error: url=%s error_type=%s error=%s",
            url,
            type(exc).__name__,
            exc,
        )
        raise


def yahoo_finance_search(
    query: str,
    *,
    quotes_count: int = 10,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    query_text = (query or "").strip()
    if not query_text:
        return []

    params = {
        "q": query_text,
        "quotesCount": int(quotes_count),
        "newsCount": 0,
        "listsCount": 0,
        "enableFuzzyQuery": "false",
    }
    url = "https://query2.finance.yahoo.com/v1/finance/search?" + urlencode(params)

    try:
        data = http_get_json(url, timeout=timeout)
    except Exception as exc:
        logger.warning(
            "Yahoo search failed: query=%s error_type=%s error=%s",
            query_text,
            type(exc).__name__,
            exc,
        )
        return []

    quotes = data.get("quotes")
    return quotes if isinstance(quotes, list) else []


def fetch_dividends_from_chart_events(
    ticker: str,
    *,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    timeout: float = 10.0,
) -> pd.Series | None:
    ticker_key = yu.normalise_ticker_key(ticker)
    if not ticker_key:
        return None

    params = {
        "period1": yu.unix_ts_floor(start),
        "period2": yu.unix_ts_ceil_exclusive(end),
        "interval": "1d",
        "events": "div",
        "includeAdjustedClose": "true",
    }
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker_key}?" + urlencode(params)

    try:
        data = http_get_json(url, timeout=timeout)
    except Exception as exc:
        logger.debug(
            "Chart-event fallback transport failure: ticker=%s error_type=%s error=%s",
            ticker_key,
            type(exc).__name__,
            exc,
        )
        return None

    try:
        result = data.get("chart", {}).get("result") or []
        if not result:
            return None

        first_result = result[0]
        if not isinstance(first_result, dict):
            return None

        dividends = first_result.get("events", {}).get("dividends") or {}
        if not isinstance(dividends, dict) or not dividends:
            return None

        rows: list[tuple[pd.Timestamp, float]] = []
        for item in dividends.values():
            if not isinstance(item, dict):
                continue

            raw_ts = item.get("date")
            raw_amt = item.get("amount")
            if raw_ts in (None, "") or raw_amt in (None, ""):
                continue

            ex_dt = pd.to_datetime(int(raw_ts), unit="s", utc=True).tz_convert(None).normalize()
            amount = yu.parse_amount(raw_amt)
            rows.append((ex_dt, amount))

        if not rows:
            return None

        rows.sort(key=lambda row: row[0])
        dts, amts = zip(*rows)
        return pd.Series(amts, index=dts, dtype="float64")

    except Exception as exc:
        logger.debug(
            "Chart-event fallback parse failure: ticker=%s error_type=%s error=%s",
            ticker_key,
            type(exc).__name__,
            exc,
        )
        return None