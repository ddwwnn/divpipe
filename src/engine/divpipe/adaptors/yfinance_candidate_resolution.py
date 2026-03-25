# src/engine/divpipe/adaptors/yfinance_candidate_resolution.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from engine.divpipe.utils.ticker_map import guess_yfinance_tickers

from . import yfinance_http as yh
from . import yfinance_models as ym
from . import yfinance_utils as yu


_INDIA_COUNTRY_TOKENS = {"INDIA"}
_INDIA_EXCHANGE_TOKENS = {
    "NATIONAL STOCK EXCHANGE OF INDIA",
    "NSE",
    "BSE LTD",
    "BSE",
}
_PLAIN_LOCAL_COUNTRY_TOKENS = {
    "ISRAEL",
    "UNITED KINGDOM",
    "UK",
    "GREAT BRITAIN",
}

_PRIORITY_OVERRIDE = 0
_PRIORITY_ISIN_SEARCH = 1
_PRIORITY_EXCHANGE_RULE = 2
_PRIORITY_COUNTRY_FALLBACK = 3
_PRIORITY_CCY_FALLBACK = 4
_PRIORITY_HEURISTIC = 5
_PRIORITY_DEFAULT = 9


@dataclass(frozen=True)
class _CanonicalisationResult:
    candidates: list[ym.Candidate]
    reason: str
    preverified_exists_any: bool = False
    preverified_exists_ticker: str = ""


def dedupe_candidates(candidates: list[ym.Candidate]) -> list[ym.Candidate]:
    seen: set[str] = set()
    out: list[ym.Candidate] = []

    for candidate in candidates:
        ticker = candidate.yfinance_ticker
        if not ticker or ticker in seen:
            continue

        seen.add(ticker)
        out.append(candidate)

    return out


def prune_isin_sg_alias_pollution(candidates: list[ym.Candidate]) -> list[ym.Candidate]:
    if not candidates:
        return candidates

    has_strict_isin_sg = False
    has_non_sg = False
    non_strict_candidates: list[ym.Candidate] = []

    for candidate in candidates:
        ticker = candidate.yfinance_ticker
        is_strict_isin_sg = yu.is_strict_isin_sg_ticker(ticker)

        if is_strict_isin_sg:
            has_strict_isin_sg = True
        else:
            non_strict_candidates.append(candidate)

        if not ticker.endswith(".SG"):
            has_non_sg = True

    if has_strict_isin_sg and has_non_sg:
        return non_strict_candidates

    return candidates


def row_looks_india_related(row_ctx: ym.RowContext) -> bool:
    country_u = yu.clean_str(row_ctx.country).upper()
    exchange_u = yu.clean_str(row_ctx.exchange).upper()

    if country_u in _INDIA_COUNTRY_TOKENS:
        return True
    if exchange_u in _INDIA_EXCHANGE_TOKENS:
        return True
    if "NATIONAL STOCK EXCHANGE OF INDIA" in exchange_u:
        return True
    if "BSE" in exchange_u:
        return True
    if "INDIA" in exchange_u:
        return True

    return False


def row_looks_plain_local_canonicalisable(row_ctx: ym.RowContext) -> bool:
    country_u = yu.clean_str(row_ctx.country).upper()
    return country_u in _PLAIN_LOCAL_COUNTRY_TOKENS


def candidates_from_isin(
    isin: str,
    *,
    quotes_count: int = 10,
    timeout: float = 10.0,
) -> list[ym.Candidate]:
    isin_key = str(isin or "").strip().upper().replace(" ", "")
    if not yu.looks_like_isin(isin_key):
        return []

    quotes = yh.yahoo_finance_search(
        isin_key,
        quotes_count=quotes_count,
        timeout=timeout,
    )
    if not quotes:
        return []

    out: list[ym.Candidate] = []
    for quote in quotes:
        ticker = yu.normalise_ticker_key(str(quote.get("symbol", "") or ""))
        if not ticker:
            continue

        quote_type = str(quote.get("quoteType", "") or "").upper()
        if quote_type and quote_type not in {"EQUITY", "ETF"}:
            continue

        market = str(quote.get("exchDisp", "") or quote.get("exchange", "") or "UNK").strip()

        out.append(
            ym.Candidate(
                market=market,
                yfinance_ticker=ticker,
                method="isin_search",
                origin="auto_search",
                canonical_exchange="",
                guess_source="isin_search",
                isin_prefix=yu.extract_isin_prefix(isin_key),
                prefix_exchange_consistent=None,
            )
        )

    return out


def candidates_from_heuristic(
    underlying: str,
    ccy: str,
    *,
    universe_region: str = "EM",
    country: str | None = None,
    exchange: str | None = None,
    isin: str | None = None,
) -> list[ym.Candidate]:
    guesses = guess_yfinance_tickers(
        underlying,
        ccy,
        country=country,
        exchange=exchange,
        isin=isin,
        universe_region=universe_region,
    )

    out: list[ym.Candidate] = []
    for guess in guesses:
        ticker = yu.normalise_ticker_key(str(guess.yfinance_ticker))
        if not ticker:
            continue

        out.append(
            ym.Candidate(
                market=str(guess.market),
                yfinance_ticker=ticker,
                method="heuristic",
                origin="auto_search",
                canonical_exchange=str(guess.canonical_exchange),
                guess_source=str(guess.guess_source),
                isin_prefix=str(guess.isin_prefix),
                prefix_exchange_consistent=guess.prefix_exchange_consistent,
            )
        )

    return out


def candidate_probe_rank(candidate: ym.Candidate) -> tuple[int, str]:
    method = str(candidate.method or "").strip().lower()
    guess_source = str(candidate.guess_source or "").strip().lower()
    ticker = candidate.yfinance_ticker

    if method == "override":
        priority = _PRIORITY_OVERRIDE
    elif method == "isin_search":
        priority = _PRIORITY_ISIN_SEARCH
    elif guess_source == "exchange_rule":
        priority = _PRIORITY_EXCHANGE_RULE
    elif guess_source == "country_fallback":
        priority = _PRIORITY_COUNTRY_FALLBACK
    elif guess_source == "ccy_fallback":
        priority = _PRIORITY_CCY_FALLBACK
    elif method == "heuristic":
        priority = _PRIORITY_HEURISTIC
    else:
        priority = _PRIORITY_DEFAULT

    return priority, ticker


def order_probe_candidates(candidates: list[ym.Candidate]) -> list[ym.Candidate]:
    if not candidates:
        return []
    return sorted(candidates, key=candidate_probe_rank)


def _get_exists_with_cache(
    *,
    ticker: str,
    shared_caches: ym.SharedCaches,
    exists_lookback_period: str,
    exists_retry_policy: ym.RetryPolicy,
    get_ticker_obj: Callable[[str], Any | None],
    exists_checker: Callable[..., bool],
) -> bool:
    exists_key: ym.ExistsCacheKey = (ticker, exists_lookback_period)
    found, exists_value = yu.cache_get(
        shared_caches.exists_cache,
        exists_key,
        shared_caches.exists_lock,
    )
    if found:
        return bool(exists_value)

    exists_value = exists_checker(
        ticker,
        period=exists_lookback_period,
        retry_policy=exists_retry_policy,
        ticker_obj=get_ticker_obj(ticker),
    )
    exists_value = bool(exists_value)

    yu.cache_set(
        shared_caches.exists_cache,
        exists_key,
        exists_value,
        shared_caches.exists_lock,
    )
    return exists_value


def canonicalise_india_ns_bo_candidates(
    *,
    candidates: list[ym.Candidate],
    row_ctx: ym.RowContext,
    shared_caches: ym.SharedCaches,
    exists_lookback_period: str,
    exists_retry_policy: ym.RetryPolicy,
    get_ticker_obj: Callable[[str], Any | None],
    exists_checker: Callable[..., bool],
) -> _CanonicalisationResult:
    if not candidates:
        return _CanonicalisationResult(candidates=candidates, reason="")

    ns_candidates = [candidate for candidate in candidates if candidate.yfinance_ticker.endswith(".NS")]
    bo_candidates = [candidate for candidate in candidates if candidate.yfinance_ticker.endswith(".BO")]

    ns_ticker = ns_candidates[0].yfinance_ticker if ns_candidates else ""
    bo_ticker = bo_candidates[0].yfinance_ticker if bo_candidates else ""

    if not (ns_ticker and bo_ticker):
        return _CanonicalisationResult(candidates=candidates, reason="")

    if not row_looks_india_related(row_ctx):
        return _CanonicalisationResult(candidates=candidates, reason="")

    exists_ns = _get_exists_with_cache(
        ticker=ns_ticker,
        shared_caches=shared_caches,
        exists_lookback_period=exists_lookback_period,
        exists_retry_policy=exists_retry_policy,
        get_ticker_obj=get_ticker_obj,
        exists_checker=exists_checker,
    )
    exists_bo = _get_exists_with_cache(
        ticker=bo_ticker,
        shared_caches=shared_caches,
        exists_lookback_period=exists_lookback_period,
        exists_retry_policy=exists_retry_policy,
        get_ticker_obj=get_ticker_obj,
        exists_checker=exists_checker,
    )

    if exists_ns:
        return _CanonicalisationResult(
            candidates=[ns_candidates[0]],
            reason="india_ns_canonical",
            preverified_exists_any=True,
            preverified_exists_ticker=ns_ticker,
        )

    if exists_bo:
        return _CanonicalisationResult(
            candidates=[bo_candidates[0]],
            reason="india_bo_canonical",
            preverified_exists_any=True,
            preverified_exists_ticker=bo_ticker,
        )

    return _CanonicalisationResult(
        candidates=[ns_candidates[0]],
        reason="india_ns_default",
    )


def canonicalise_plain_over_local_candidates(
    *,
    candidates: list[ym.Candidate],
    row_ctx: ym.RowContext,
    shared_caches: ym.SharedCaches,
    exists_lookback_period: str,
    exists_retry_policy: ym.RetryPolicy,
    get_ticker_obj: Callable[[str], Any | None],
    exists_checker: Callable[..., bool],
) -> _CanonicalisationResult:
    if len(candidates) != 2:
        return _CanonicalisationResult(candidates=candidates, reason="")

    if not row_looks_plain_local_canonicalisable(row_ctx):
        return _CanonicalisationResult(candidates=candidates, reason="")

    plain_candidates = [candidate for candidate in candidates if yu.is_plain_ticker(candidate.yfinance_ticker)]
    local_candidates = [candidate for candidate in candidates if yu.is_local_ticker(candidate.yfinance_ticker)]

    if len(plain_candidates) != 1 or len(local_candidates) != 1:
        return _CanonicalisationResult(candidates=candidates, reason="")

    plain = plain_candidates[0]
    local = local_candidates[0]

    exists_plain = _get_exists_with_cache(
        ticker=plain.yfinance_ticker,
        shared_caches=shared_caches,
        exists_lookback_period=exists_lookback_period,
        exists_retry_policy=exists_retry_policy,
        get_ticker_obj=get_ticker_obj,
        exists_checker=exists_checker,
    )
    exists_local = _get_exists_with_cache(
        ticker=local.yfinance_ticker,
        shared_caches=shared_caches,
        exists_lookback_period=exists_lookback_period,
        exists_retry_policy=exists_retry_policy,
        get_ticker_obj=get_ticker_obj,
        exists_checker=exists_checker,
    )

    if exists_plain and not exists_local:
        return _CanonicalisationResult(
            candidates=[plain],
            reason="plain_over_local_canonical",
        )

    if exists_local and not exists_plain:
        return _CanonicalisationResult(
            candidates=[local],
            reason="local_over_plain_canonical",
        )

    return _CanonicalisationResult(candidates=candidates, reason="")


def resolve_candidates_for_row(
    *,
    row_ctx: ym.RowContext,
    row_isin: str,
    override: ym.OverrideResolution,
    shared_caches: ym.SharedCaches,
    isin_search_timeout_sec: float,
    isin_quotes_count: int,
    universe_region: str,
    exists_lookback_period: str,
    exists_retry_policy: ym.RetryPolicy,
    get_ticker_obj: Callable[[str], Any | None],
    exists_checker: Callable[..., bool],
) -> ym.CandidateResolution:
    if override.is_present:
        ticker = yu.normalise_ticker_key(override.ticker)
        candidates = [
            ym.Candidate(
                market=yu.derive_listing_market_from_ticker(override.ticker),
                yfinance_ticker=ticker,
                method=override.method or "override",
                origin=override.source or "chosen_map",
                canonical_exchange="",
                guess_source="override",
                isin_prefix=yu.extract_isin_prefix(row_isin),
                prefix_exchange_consistent=None,
            )
        ]
        return ym.CandidateResolution(
            candidates=candidates,
            reason=override.reason or "override",
            preverified_exists_any=False,
            preverified_exists_ticker="",
        )

    candidates: list[ym.Candidate] = []

    if yu.looks_like_isin(row_isin):
        found, isin_candidates = yu.cache_get(
            shared_caches.isin_cache,
            row_isin,
            shared_caches.isin_lock,
        )
        if not found:
            isin_candidates = candidates_from_isin(
                row_isin,
                quotes_count=isin_quotes_count,
                timeout=isin_search_timeout_sec,
            )
            yu.cache_set(
                shared_caches.isin_cache,
                row_isin,
                isin_candidates,
                shared_caches.isin_lock,
            )
        candidates.extend(isin_candidates or [])

    heur_key: ym.HeuristicCacheKey = (
        row_ctx.underlying,
        row_ctx.ccy,
        row_ctx.country,
        row_ctx.exchange,
        row_isin,
        universe_region,
    )
    found, heuristic_candidates = yu.cache_get(
        shared_caches.heuristic_cache,
        heur_key,
        shared_caches.heuristic_lock,
    )
    if not found:
        heuristic_candidates = candidates_from_heuristic(
            row_ctx.underlying,
            row_ctx.ccy,
            universe_region=universe_region,
            country=row_ctx.country,
            exchange=row_ctx.exchange,
            isin=row_isin,
        )
        yu.cache_set(
            shared_caches.heuristic_cache,
            heur_key,
            heuristic_candidates,
            shared_caches.heuristic_lock,
        )

    candidates.extend(heuristic_candidates or [])

    candidates = dedupe_candidates(candidates)
    candidates = prune_isin_sg_alias_pollution(candidates)

    india_result = canonicalise_india_ns_bo_candidates(
        candidates=candidates,
        row_ctx=row_ctx,
        shared_caches=shared_caches,
        exists_lookback_period=exists_lookback_period,
        exists_retry_policy=exists_retry_policy,
        get_ticker_obj=get_ticker_obj,
        exists_checker=exists_checker,
    )

    plain_local_result = canonicalise_plain_over_local_candidates(
        candidates=india_result.candidates,
        row_ctx=row_ctx,
        shared_caches=shared_caches,
        exists_lookback_period=exists_lookback_period,
        exists_retry_policy=exists_retry_policy,
        get_ticker_obj=get_ticker_obj,
        exists_checker=exists_checker,
    )

    reason = india_result.reason
    if plain_local_result.reason:
        reason = plain_local_result.reason

    preverified_exists_any = india_result.preverified_exists_any
    preverified_exists_ticker = india_result.preverified_exists_ticker

    return ym.CandidateResolution(
        candidates=plain_local_result.candidates,
        reason=reason,
        preverified_exists_any=preverified_exists_any,
        preverified_exists_ticker=preverified_exists_ticker,
    )