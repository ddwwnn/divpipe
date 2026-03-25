# tests/test_yfinance_candidate_arbitration.py

from __future__ import annotations

from src.engine.divpipe.adaptors import yfinance_candidate_resolution as ycr
from src.engine.divpipe.adaptors import yfinance_models as ym
from src.engine.divpipe.adaptors.yfinance_adaptor import YFinanceAdaptor


def _build_shared_caches() -> ym.SharedCaches:
    return ym.SharedCaches(
        isin_cache={},
        heuristic_cache={},
        div_cache={},
        exists_cache={},
    )


def test_prune_isin_sg_alias_pollution_drops_strict_isin_sg_when_non_sg_exists() -> None:
    candidates = [
        ym.Candidate(market="NASDAQ", yfinance_ticker="LEGN", method="isin_search"),
        ym.Candidate(market="Stuttgart", yfinance_ticker="US52490G1022.SG", method="isin_search"),
    ]

    out = ycr.prune_isin_sg_alias_pollution(candidates)

    assert [candidate.yfinance_ticker for candidate in out] == ["LEGN"]


def test_prune_isin_sg_alias_pollution_keeps_candidates_when_no_non_sg_exists() -> None:
    candidates = [
        ym.Candidate(market="Stuttgart", yfinance_ticker="US52490G1022.SG", method="isin_search"),
    ]

    out = ycr.prune_isin_sg_alias_pollution(candidates)

    assert [candidate.yfinance_ticker for candidate in out] == ["US52490G1022.SG"]


def test_canonicalise_india_ns_bo_candidates_prefers_ns_when_ns_exists() -> None:
    adaptor = YFinanceAdaptor()
    shared_caches = _build_shared_caches()

    row_ctx = ym.RowContext(
        underlying="TMCV",
        ccy="USD",
        isin="",
        country="India",
        weight=0.0,
        map_key="TMCV|USD",
        name="Test India Name",
        exchange="National Stock Exchange of India",
    )

    candidates = [
        ym.Candidate(market="BO", yfinance_ticker="TMCV.BO", method="heuristic"),
        ym.Candidate(market="NS", yfinance_ticker="TMCV.NS", method="heuristic"),
    ]

    def _get_ticker_obj(sym: str) -> None:
        del sym
        return None

    original = adaptor._ticker_exists

    try:
        def _fake_ticker_exists(
            ticker: str,
            *,
            period: str = "5d",
            retry_policy: ym.RetryPolicy | None = None,
            ticker_obj=None,
        ) -> bool:
            del period, retry_policy, ticker_obj
            return ticker.upper().endswith(".NS")

        adaptor._ticker_exists = _fake_ticker_exists  # type: ignore[method-assign]

        result = ycr.canonicalise_india_ns_bo_candidates(
            candidates=candidates,
            row_ctx=row_ctx,
            shared_caches=shared_caches,
            exists_lookback_period="5d",
            exists_retry_policy=ym.RetryPolicy(
                max_attempts=2,
                base_delay_sec=0.25,
                backoff_factor=2.0,
                jitter_ratio=0.25,
            ),
            get_ticker_obj=_get_ticker_obj,
            exists_checker=adaptor._ticker_exists,
        )
    finally:
        adaptor._ticker_exists = original  # type: ignore[method-assign]

    assert [candidate.yfinance_ticker for candidate in result.candidates] == ["TMCV.NS"]
    assert result.reason == "india_ns_canonical"


def test_canonicalise_india_ns_bo_candidates_applies_even_when_ccy_is_not_inr() -> None:
    adaptor = YFinanceAdaptor()
    shared_caches = _build_shared_caches()

    row_ctx = ym.RowContext(
        underlying="TMCV",
        ccy="USD",
        isin="",
        country="India",
        weight=0.0,
        map_key="TMCV|USD",
        name="Test India Name",
        exchange="BSE Ltd",
    )

    candidates = [
        ym.Candidate(market="BO", yfinance_ticker="TMCV.BO", method="heuristic"),
        ym.Candidate(market="NS", yfinance_ticker="TMCV.NS", method="heuristic"),
    ]

    def _get_ticker_obj(sym: str) -> None:
        del sym
        return None

    original = adaptor._ticker_exists

    try:
        def _fake_ticker_exists(
            ticker: str,
            *,
            period: str = "5d",
            retry_policy: ym.RetryPolicy | None = None,
            ticker_obj=None,
        ) -> bool:
            del ticker, period, retry_policy, ticker_obj
            return False

        adaptor._ticker_exists = _fake_ticker_exists  # type: ignore[method-assign]

        result = ycr.canonicalise_india_ns_bo_candidates(
            candidates=candidates,
            row_ctx=row_ctx,
            shared_caches=shared_caches,
            exists_lookback_period="5d",
            exists_retry_policy=ym.RetryPolicy(
                max_attempts=2,
                base_delay_sec=0.25,
                backoff_factor=2.0,
                jitter_ratio=0.25,
            ),
            get_ticker_obj=_get_ticker_obj,
            exists_checker=adaptor._ticker_exists,
        )
    finally:
        adaptor._ticker_exists = original  # type: ignore[method-assign]

    assert [candidate.yfinance_ticker for candidate in result.candidates] == ["TMCV.NS"]
    assert result.reason == "india_ns_default"


def test_canonicalise_india_ns_bo_candidates_prefers_bo_when_only_bo_exists() -> None:
    adaptor = YFinanceAdaptor()
    shared_caches = _build_shared_caches()

    row_ctx = ym.RowContext(
        underlying="TMCV",
        ccy="USD",
        isin="",
        country="India",
        weight=0.0,
        map_key="TMCV|USD",
        name="Test India Name",
        exchange="BSE Ltd",
    )

    candidates = [
        ym.Candidate(market="BO", yfinance_ticker="TMCV.BO", method="heuristic"),
        ym.Candidate(market="NS", yfinance_ticker="TMCV.NS", method="heuristic"),
    ]

    def _get_ticker_obj(sym: str) -> None:
        del sym
        return None

    original = adaptor._ticker_exists

    try:
        def _fake_ticker_exists(
            ticker: str,
            *,
            period: str = "5d",
            retry_policy: ym.RetryPolicy | None = None,
            ticker_obj=None,
        ) -> bool:
            del period, retry_policy, ticker_obj
            return ticker.upper().endswith(".BO")

        adaptor._ticker_exists = _fake_ticker_exists  # type: ignore[method-assign]

        result = ycr.canonicalise_india_ns_bo_candidates(
            candidates=candidates,
            row_ctx=row_ctx,
            shared_caches=shared_caches,
            exists_lookback_period="5d",
            exists_retry_policy=ym.RetryPolicy(
                max_attempts=2,
                base_delay_sec=0.25,
                backoff_factor=2.0,
                jitter_ratio=0.25,
            ),
            get_ticker_obj=_get_ticker_obj,
            exists_checker=adaptor._ticker_exists,
        )
    finally:
        adaptor._ticker_exists = original  # type: ignore[method-assign]

    assert [candidate.yfinance_ticker for candidate in result.candidates] == ["TMCV.BO"]
    assert result.reason == "india_bo_canonical"


def test_resolve_candidates_for_row_sets_preverified_exists_for_ns_choice() -> None:
    adaptor = YFinanceAdaptor()
    shared_caches = _build_shared_caches()

    row_ctx = ym.RowContext(
        underlying="TMCV",
        ccy="USD",
        isin="",
        country="India",
        weight=0.0,
        map_key="TMCV|USD",
        name="Test India Name",
        exchange="National Stock Exchange of India",
    )

    override = ym.OverrideResolution(
        ticker="",
        reason="",
        method="",
        source="",
        isin="",
    )

    def _get_ticker_obj(sym: str) -> None:
        del sym
        return None

    original = adaptor._ticker_exists
    original_candidates_from_heuristic = ycr.candidates_from_heuristic

    try:
        def _fake_ticker_exists(
            ticker: str,
            *,
            period: str = "5d",
            retry_policy: ym.RetryPolicy | None = None,
            ticker_obj=None,
        ) -> bool:
            del period, retry_policy, ticker_obj
            return ticker.upper().endswith(".NS")

        def _fake_candidates_from_heuristic(
            underlying: str,
            ccy: str,
            *,
            universe_region: str = "EM",
            country: str | None = None,
            exchange: str | None = None,
            isin: str | None = None,
        ) -> list[ym.Candidate]:
            del underlying, ccy, universe_region, country, exchange, isin
            return [
                ym.Candidate(market="BO", yfinance_ticker="TMCV.BO", method="heuristic"),
                ym.Candidate(market="NS", yfinance_ticker="TMCV.NS", method="heuristic"),
            ]

        adaptor._ticker_exists = _fake_ticker_exists  # type: ignore[method-assign]
        ycr.candidates_from_heuristic = _fake_candidates_from_heuristic  # type: ignore[assignment]

        result = ycr.resolve_candidates_for_row(
            row_ctx=row_ctx,
            row_isin="",
            override=override,
            shared_caches=shared_caches,
            isin_search_timeout_sec=10.0,
            isin_quotes_count=10,
            universe_region="EM",
            exists_lookback_period="5d",
            exists_retry_policy=ym.RetryPolicy(
                max_attempts=2,
                base_delay_sec=0.25,
                backoff_factor=2.0,
                jitter_ratio=0.25,
            ),
            get_ticker_obj=_get_ticker_obj,
            exists_checker=adaptor._ticker_exists,
        )
    finally:
        adaptor._ticker_exists = original  # type: ignore[method-assign]
        ycr.candidates_from_heuristic = original_candidates_from_heuristic  # type: ignore[assignment]

    assert [candidate.yfinance_ticker for candidate in result.candidates] == ["TMCV.NS"]
    assert result.reason == "india_ns_canonical"
    assert result.preverified_exists_any is True
    assert result.preverified_exists_ticker == "TMCV.NS"