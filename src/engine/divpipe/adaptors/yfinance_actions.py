# src/engine/divpipe/adaptors/yfinance_actions.py

from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from . import yfinance_http as yh
from . import yfinance_models as ym
from . import yfinance_utils as yu

logger = logging.getLogger(__name__)


def get_ticker_obj(
    ticker: str,
    *,
    ticker_cache: dict[str, Any],
    ticker_lock,
    logger: logging.Logger,
) -> Any | None:
    ticker_key = yu.normalise_ticker_key(ticker)
    if not ticker_key:
        return None

    found, cached = yu.cache_get(ticker_cache, ticker_key, ticker_lock)
    if found:
        return cached

    try:
        ticker_obj = yf.Ticker(ticker_key)
    except Exception as exc:
        logger.debug(
            "Ticker object creation failed: ticker=%s error_type=%s error=%s",
            ticker_key,
            type(exc).__name__,
            exc,
        )
        return None

    yu.cache_set(ticker_cache, ticker_key, ticker_obj, ticker_lock)
    return ticker_obj


def try_one(
    ticker: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    *,
    retry_policy: ym.RetryPolicy | None = None,
    ticker_obj: Any | None = None,
    chart_fallback_fetcher: Callable[..., pd.Series | None] | None = None,
) -> pd.Series | None:
    ticker_key = yu.normalise_ticker_key(ticker)
    if not ticker_key:
        return None

    fallback_fetcher = chart_fallback_fetcher or yh.fetch_dividends_from_chart_events
    end_eff = (end + pd.Timedelta(days=1)) if end is not None else None
    yf_ticker = ticker_obj if ticker_obj is not None else yf.Ticker(ticker_key)

    policy = retry_policy or ym.RetryPolicy(
        max_attempts=3,
        base_delay_sec=0.4,
        backoff_factor=2.0,
        jitter_ratio=0.25,
    )

    for attempt in range(1, policy.max_attempts + 1):
        try:
            hist = yu.quiet_call(
                lambda: yf_ticker.history(
                    start=start,
                    end=end_eff,
                    actions=True,
                    auto_adjust=False,
                )
            )

            if hist is None or len(hist) == 0 or "Dividends" not in hist.columns:
                return None

            div = hist["Dividends"]
            div = div[div != 0]
            if len(div) == 0:
                return None

            return div

        except Exception as exc:
            if yu.looks_like_yfinance_string_dtype_bug(exc):
                logger.warning(
                    "Dividend fetch hit yfinance/pandas string-dtype bug; falling back to chart events: "
                    "ticker=%s attempt=%s/%s",
                    ticker_key,
                    attempt,
                    policy.max_attempts,
                )
                div = fallback_fetcher(
                    ticker_key,
                    start=start,
                    end=end,
                )
                if div is not None and len(div) > 0:
                    return div

            if attempt >= policy.max_attempts:
                logger.debug(
                    "Dividend fetch failed after retries: ticker=%s attempts=%s error_type=%s error=%s",
                    ticker_key,
                    attempt,
                    type(exc).__name__,
                    exc,
                )
                return None

            delay = policy.base_delay_sec * (policy.backoff_factor ** (attempt - 1))
            logger.debug(
                "Dividend fetch retry: ticker=%s attempt=%s/%s delay=%.2fs error_type=%s error=%s",
                ticker_key,
                attempt,
                policy.max_attempts,
                delay,
                type(exc).__name__,
                exc,
            )
            yu.sleep_with_jitter(delay, policy.jitter_ratio)

    return None


def ticker_exists(
    ticker: str,
    *,
    period: str = "1mo",
    retry_policy: ym.RetryPolicy | None = None,
    ticker_obj: Any | None = None,
) -> bool:
    ticker_key = yu.normalise_ticker_key(ticker)
    if not ticker_key:
        return False

    yf_ticker = ticker_obj if ticker_obj is not None else yf.Ticker(ticker_key)

    policy = retry_policy or ym.RetryPolicy(
        max_attempts=2,
        base_delay_sec=0.25,
        backoff_factor=2.0,
        jitter_ratio=0.25,
    )

    for attempt in range(1, policy.max_attempts + 1):
        try:
            hist = yu.quiet_call(lambda: yf_ticker.history(period=period, actions=False))
            if hist is not None and len(hist) > 0:
                return True

            if yu.has_strong_fast_info_signal(yf_ticker):
                return True

            if yu.has_strong_info_signal(yf_ticker):
                return True

            return False

        except Exception as exc:
            if attempt >= policy.max_attempts:
                logger.debug(
                    "Exists check failed after retries: ticker=%s attempts=%s error_type=%s error=%s",
                    ticker_key,
                    attempt,
                    type(exc).__name__,
                    exc,
                )
                return False

            delay = policy.base_delay_sec * (policy.backoff_factor ** (attempt - 1))
            logger.debug(
                "Exists check retry: ticker=%s attempt=%s/%s delay=%.2fs error_type=%s error=%s",
                ticker_key,
                attempt,
                policy.max_attempts,
                delay,
                type(exc).__name__,
                exc,
            )
            yu.sleep_with_jitter(delay, policy.jitter_ratio)

    return False