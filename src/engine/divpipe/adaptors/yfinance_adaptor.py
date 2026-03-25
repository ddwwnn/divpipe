# src/engine/divpipe/adaptors/yfinance_adaptor.py

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import pandas as pd

from engine.divpipe.schema.canonical import enforce_canonical_dtypes

from . import yfinance_actions as ya
from . import yfinance_candidate_resolution as ycr
from . import yfinance_http as yh
from . import yfinance_models as ym
from . import yfinance_overrides as yo
from . import yfinance_rows as yr
from . import yfinance_status as ys
from . import yfinance_utils as yu

logger = logging.getLogger(__name__)


class YFinanceAdaptor:
    name: str = "yfinance"

    def _build_row_context(self, row: Any) -> ym.RowContext | None:
        underlying = yu.clean_str(getattr(row, "underlying", ""))
        ccy = yu.normalise_ccy_safe(getattr(row, "underlying_ccy", ""))
        if not underlying or not ccy:
            return None

        return ym.RowContext(
            underlying=underlying,
            ccy=ccy,
            isin=yu.clean_str(getattr(row, "isin", "")).upper(),
            country=yu.clean_str(getattr(row, "country", "")) or None,
            weight=yu.parse_optional_float(getattr(row, "weight", None)),
            map_key=yu.map_key(underlying, ccy),
            name=yu.clean_str(getattr(row, "name", "")),
            exchange=yu.clean_str(getattr(row, "exchange", "")),
        )

    def _get_ticker_obj(self, ticker: str, *, shared_caches: ym.SharedCaches) -> Any | None:
        return ya.get_ticker_obj(
            ticker,
            ticker_cache=shared_caches.ticker_cache,
            ticker_lock=shared_caches.ticker_lock,
            logger=logger,
        )

    def _build_get_ticker_obj(self, *, shared_caches: ym.SharedCaches) -> Callable[[str], Any | None]:
        def _getter(ticker: str) -> Any | None:
            return self._get_ticker_obj(ticker, shared_caches=shared_caches)

        return _getter

    def _ticker_exists(
        self,
        ticker: str,
        *,
        period: str = "5d",
        retry_policy: ym.RetryPolicy | None = None,
        ticker_obj: Any | None = None,
    ) -> bool:
        return ya.ticker_exists(
            ticker,
            period=period,
            retry_policy=retry_policy,
            ticker_obj=ticker_obj,
        )

    def _build_shared_caches(self) -> ym.SharedCaches:
        return ym.SharedCaches(
            isin_cache={},
            heuristic_cache={},
            div_cache={},
            exists_cache={},
        )

    def _build_retry_policies(self) -> tuple[ym.RetryPolicy, ym.RetryPolicy]:
        return (
            ym.RetryPolicy(
                max_attempts=3,
                base_delay_sec=0.4,
                backoff_factor=2.0,
                jitter_ratio=0.25,
            ),
            ym.RetryPolicy(
                max_attempts=2,
                base_delay_sec=0.25,
                backoff_factor=2.0,
                jitter_ratio=0.25,
            ),
        )

    def _resolve_asof_eff(
        self,
        *,
        asof_date: str | None,
        end_ts: pd.Timestamp | None,
    ) -> str:
        asof_eff = (asof_date or "").strip()
        if asof_eff:
            return asof_eff

        if end_ts is not None:
            return pd.Timestamp(end_ts).date().isoformat()

        return pd.Timestamp.now("UTC").date().isoformat()

    def _build_output_frames(
        self,
        *,
        rows: list[dict[str, Any]],
        errs: list[dict[str, Any]],
        no_divs: list[dict[str, Any]],
        discovered_candidate_rows: list[dict[str, Any]],
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        base = pd.DataFrame(rows)
        df = enforce_canonical_dtypes(base) if len(base) else enforce_canonical_dtypes(pd.DataFrame())
        err_df = yr.build_stage1_error_df(errs)
        no_div_df = yr.build_stage1_no_div_df(no_divs)
        discovered_candidate_df = yr.build_discovered_candidate_df(discovered_candidate_rows)
        return df, err_df, no_div_df, discovered_candidate_df

    def _choose_candidate_with_dividends(
        self,
        *,
        candidates: list[ym.Candidate],
        shared_caches: ym.SharedCaches,
        start: str,
        end: str,
        start_ts: pd.Timestamp | None,
        end_ts: pd.Timestamp | None,
        try_one_retry_policy: ym.RetryPolicy,
    ) -> tuple[ym.Candidate | None, pd.Series | None]:
        for candidate in candidates:
            ticker = candidate.yfinance_ticker
            div_key: ym.DivCacheKey = (ticker, start or "", end or "")

            found, div = yu.cache_get(shared_caches.div_cache, div_key, shared_caches.div_lock)
            if not found:
                ticker_obj = self._get_ticker_obj(ticker, shared_caches=shared_caches)
                div = ya.try_one(
                    ticker,
                    start_ts,
                    end_ts,
                    retry_policy=try_one_retry_policy,
                    ticker_obj=ticker_obj,
                    chart_fallback_fetcher=yh.fetch_dividends_from_chart_events,
                )
                yu.cache_set(shared_caches.div_cache, div_key, div, shared_caches.div_lock)

            if div is not None:
                return candidate, div

        return None, None

    def _probe_existing_candidate(
        self,
        *,
        candidates: list[ym.Candidate],
        candidate_resolution: ym.CandidateResolution,
        exists_lookback_period: str,
        shared_caches: ym.SharedCaches,
        exists_retry_policy: ym.RetryPolicy,
    ) -> tuple[bool, str]:
        if candidate_resolution.preverified_exists_any:
            return True, candidate_resolution.preverified_exists_ticker

        for candidate in ycr.order_probe_candidates(candidates):
            ticker = candidate.yfinance_ticker
            if not ticker:
                continue

            exists_key: ym.ExistsCacheKey = (ticker, exists_lookback_period)
            found, ok = yu.cache_get(shared_caches.exists_cache, exists_key, shared_caches.exists_lock)
            if not found:
                ticker_obj = self._get_ticker_obj(ticker, shared_caches=shared_caches)
                ok = self._ticker_exists(
                    ticker,
                    period=exists_lookback_period,
                    retry_policy=exists_retry_policy,
                    ticker_obj=ticker_obj,
                )
                yu.cache_set(shared_caches.exists_cache, exists_key, ok, shared_caches.exists_lock)

            if ok:
                return True, ticker

        return False, ""

    def _make_override_candidate(
        self,
        *,
        ticker: str,
        row_isin: str,
        override: ym.OverrideResolution,
    ) -> ym.Candidate:
        return ym.Candidate(
            market=yu.derive_listing_market_from_ticker(ticker),
            yfinance_ticker=ticker,
            method=override.method or "override",
            origin=override.source or "chosen_map",
            canonical_exchange="",
            guess_source="override",
            isin_prefix=yu.extract_isin_prefix(row_isin),
            prefix_exchange_consistent=None,
        )

    def _finalise_resolution_metadata(
        self,
        *,
        row_isin: str,
        override: ym.OverrideResolution,
        chosen_ticker: str,
        chosen_candidate: ym.Candidate | None,
    ) -> dict[str, Any]:
        chosen_market = ""
        chosen_origin = ""
        resolution_source = ""
        guess_source = ""
        canonical_exchange = ""
        isin_prefix = yu.extract_isin_prefix(row_isin)
        prefix_exchange_consistent: bool | None = None

        if chosen_candidate is not None:
            chosen_market = yu.derive_listing_market_from_ticker(chosen_candidate.yfinance_ticker) or str(
                chosen_candidate.market or ""
            )
            chosen_origin = str(chosen_candidate.origin or "")
            resolution_source = str(chosen_candidate.origin or "")
            guess_source = str(chosen_candidate.guess_source or "")
            canonical_exchange = str(chosen_candidate.canonical_exchange or "")
            if chosen_candidate.isin_prefix:
                isin_prefix = str(chosen_candidate.isin_prefix or "")
            prefix_exchange_consistent = chosen_candidate.prefix_exchange_consistent
        elif override.is_present:
            chosen_market = yu.derive_listing_market_from_ticker(chosen_ticker)
            chosen_origin = override.source or ""
            resolution_source = override.source or ""
            guess_source = "override"

        if prefix_exchange_consistent is None:
            prefix_exchange_consistent = yr.derive_prefix_exchange_consistency(row_isin, canonical_exchange)

        return {
            "chosen_market": chosen_market,
            "chosen_origin": chosen_origin,
            "resolution_source": resolution_source,
            "guess_source": guess_source,
            "canonical_exchange": canonical_exchange,
            "isin_prefix": isin_prefix,
            "prefix_exchange_consistent": prefix_exchange_consistent,
        }

    def _handle_unsupported_override(
        self,
        *,
        row_ctx: ym.RowContext,
        row_isin: str,
        override: ym.OverrideResolution,
        start: str,
        end: str,
    ) -> ym.FetchSingleRowResult:
        out = ym.empty_fetch_single_row_result()
        unsupported_ticker = override.ticker.strip().upper()
        candidate_values = [unsupported_ticker]

        metadata = self._finalise_resolution_metadata(
            row_isin=row_isin,
            override=override,
            chosen_ticker=unsupported_ticker,
            chosen_candidate=None,
        )

        out.discovered_candidate_rows.append(
            yr.build_discovered_candidate_row(
                source=self.name,
                row_ctx=row_ctx,
                row_isin=row_isin,
                chosen_ticker=unsupported_ticker,
                candidate_market=metadata["chosen_market"],
                candidate_origin=metadata["chosen_origin"],
                resolution_status="unsupported_vendor",
                resolution_reason=override.reason or "unsupported_vendor:yfinance",
                resolution_method=override.method or "override",
                resolution_source=metadata["resolution_source"],
                exists_ticker=unsupported_ticker,
                preverified_exists_any=False,
                preverified_exists_ticker="",
                candidate_values=candidate_values,
                start=start,
                end=end,
                guess_source=metadata["guess_source"],
                canonical_exchange=metadata["canonical_exchange"],
                isin_prefix=metadata["isin_prefix"],
                prefix_exchange_consistent=metadata["prefix_exchange_consistent"],
            )
        )

        out.no_divs.append(
            yr.build_no_div_row(
                source=self.name,
                row_ctx=row_ctx,
                row_isin=row_isin,
                exists_ticker=unsupported_ticker,
                candidates=[
                    self._make_override_candidate(
                        ticker=unsupported_ticker,
                        row_isin=row_isin,
                        override=override,
                    )
                ],
                start=start,
                end=end,
                status="unsupported_vendor",
            )
        )

        return out

    def _resolve_failure_choice(
        self,
        *,
        override: ym.OverrideResolution,
        candidate_resolution: ym.CandidateResolution,
        exists_any: bool,
        exists_ticker: str,
    ) -> tuple[str, str, ym.Candidate | None]:
        if override.is_present:
            chosen_guess = yu.normalise_ticker_key(override.ticker)
            chosen_method = override.method or "override"
            chosen_candidate = yu.find_candidate_by_ticker(candidate_resolution.candidates, chosen_guess)
            return chosen_guess, chosen_method, chosen_candidate

        if exists_any:
            chosen_guess = exists_ticker
            chosen_candidate = yu.find_candidate_by_ticker(candidate_resolution.candidates, chosen_guess)
            chosen_method = chosen_candidate.method if chosen_candidate is not None else ""
            return chosen_guess, chosen_method, chosen_candidate

        if candidate_resolution.candidates:
            first = candidate_resolution.candidates[0]
            return first.yfinance_ticker, first.method or "", first

        return "", "", None

    def _emit_resolution_failure(
        self,
        *,
        row_ctx: ym.RowContext,
        row_isin: str,
        override: ym.OverrideResolution,
        candidate_resolution: ym.CandidateResolution,
        exists_any: bool,
        exists_ticker: str,
        start: str,
        end: str,
    ) -> ym.FetchSingleRowResult:
        out = ym.empty_fetch_single_row_result()

        chosen_guess, chosen_method, chosen_candidate = self._resolve_failure_choice(
            override=override,
            candidate_resolution=candidate_resolution,
            exists_any=exists_any,
            exists_ticker=exists_ticker,
        )

        candidate_values = [candidate.yfinance_ticker for candidate in candidate_resolution.candidates]
        candidate_count_ = yu.candidate_count(candidate_values)

        metadata = self._finalise_resolution_metadata(
            row_isin=row_isin,
            override=override,
            chosen_ticker=chosen_guess,
            chosen_candidate=chosen_candidate,
        )

        resolution_status = ys.status_for_resolution_failure(
            candidate_count_=candidate_count_,
            exists_any=exists_any,
        )

        effective_preverified_exists_any = bool(candidate_resolution.preverified_exists_any or exists_any)
        effective_preverified_exists_ticker = (
            candidate_resolution.preverified_exists_ticker or exists_ticker or ""
        )

        out.discovered_candidate_rows.append(
            yr.build_discovered_candidate_row(
                source=self.name,
                row_ctx=row_ctx,
                row_isin=row_isin,
                chosen_ticker=chosen_guess,
                candidate_market=metadata["chosen_market"],
                candidate_origin=metadata["chosen_origin"],
                resolution_status=resolution_status,
                resolution_reason=candidate_resolution.reason or ("override" if override.is_present else ""),
                resolution_method=chosen_method,
                resolution_source=metadata["resolution_source"],
                exists_ticker=exists_ticker,
                preverified_exists_any=effective_preverified_exists_any,
                preverified_exists_ticker=effective_preverified_exists_ticker,
                candidate_values=candidate_values,
                start=start,
                end=end,
                guess_source=metadata["guess_source"],
                canonical_exchange=metadata["canonical_exchange"],
                isin_prefix=metadata["isin_prefix"],
                prefix_exchange_consistent=metadata["prefix_exchange_consistent"],
            )
        )

        if exists_any or candidate_count_ > 0:
            out.no_divs.append(
                yr.build_no_div_row(
                    source=self.name,
                    row_ctx=row_ctx,
                    row_isin=row_isin,
                    exists_ticker=exists_ticker,
                    candidates=candidate_resolution.candidates,
                    start=start,
                    end=end,
                    status=ys.no_div_status_for_resolution_failure(exists_any=exists_any),
                )
            )
        else:
            out.errs.append(
                yr.build_error_row(
                    source=self.name,
                    row_ctx=row_ctx,
                    row_isin=row_isin,
                    error=ys.error_for_resolution_failure(
                        candidate_count_=candidate_count_,
                        exists_any=exists_any,
                    ),
                    candidates=candidate_resolution.candidates,
                    start=start,
                    end=end,
                )
            )

        return out

    def _build_success_result(
        self,
        *,
        row_ctx: ym.RowContext,
        row_isin: str,
        override: ym.OverrideResolution,
        candidate_resolution: ym.CandidateResolution,
        chosen: ym.Candidate,
        div: pd.Series,
        start: str,
        end: str,
        asof_eff: str,
    ) -> ym.FetchSingleRowResult:
        out = ym.empty_fetch_single_row_result()

        chosen_ticker = chosen.yfinance_ticker
        candidate_values = [candidate.yfinance_ticker for candidate in candidate_resolution.candidates]

        metadata = self._finalise_resolution_metadata(
            row_isin=row_isin,
            override=override,
            chosen_ticker=chosen_ticker,
            chosen_candidate=chosen,
        )

        out.discovered_candidate_rows.append(
            yr.build_discovered_candidate_row(
                source=self.name,
                row_ctx=row_ctx,
                row_isin=row_isin,
                chosen_ticker=chosen_ticker,
                candidate_market=metadata["chosen_market"],
                candidate_origin=metadata["chosen_origin"],
                resolution_status="div_found",
                resolution_reason=candidate_resolution.reason or ("override" if override.is_present else "div_found"),
                resolution_method=chosen.method or ("override" if override.is_present else ""),
                resolution_source=chosen.origin or (override.source if override.is_present else "auto_search"),
                exists_ticker=chosen_ticker,
                preverified_exists_any=bool(candidate_resolution.preverified_exists_any),
                preverified_exists_ticker=candidate_resolution.preverified_exists_ticker,
                candidate_values=candidate_values,
                start=start,
                end=end,
                guess_source=chosen.guess_source,
                canonical_exchange=metadata["canonical_exchange"],
                isin_prefix=metadata["isin_prefix"],
                prefix_exchange_consistent=metadata["prefix_exchange_consistent"],
            )
        )

        div_rows, div_errs = yr.build_dividend_rows(
            source=self.name,
            row_ctx=row_ctx,
            row_isin=row_isin,
            chosen=chosen,
            div=div,
            candidates=candidate_resolution.candidates,
            start=start,
            end=end,
            asof_eff=asof_eff,
        )

        out.rows.extend(div_rows)
        out.errs.extend(div_errs)
        return out

    def _fetch_single_row(
        self,
        row: Any,
        *,
        start: str,
        end: str,
        start_ts: pd.Timestamp | None,
        end_ts: pd.Timestamp | None,
        exists_lookback_period: str,
        isin_search_timeout_sec: float,
        isin_quotes_count: int,
        universe_region: str,
        asof_eff: str,
        chosen_map_cache: dict[str, ym.OverrideResolution],
        shared_caches: ym.SharedCaches,
        try_one_retry_policy: ym.RetryPolicy,
        exists_retry_policy: ym.RetryPolicy,
    ) -> ym.FetchSingleRowResult:
        row_ctx = self._build_row_context(row)
        if row_ctx is None:
            return ym.empty_fetch_single_row_result()

        override = yo.resolve_override_for_row(
            row,
            row_ctx=row_ctx,
            chosen_map_cache=chosen_map_cache,
        )
        row_isin = row_ctx.isin or override.isin or ""

        if override.is_unsupported_vendor:
            return self._handle_unsupported_override(
                row_ctx=row_ctx,
                row_isin=row_isin,
                override=override,
                start=start,
                end=end,
            )

        candidate_resolution = ycr.resolve_candidates_for_row(
            row_ctx=row_ctx,
            row_isin=row_isin,
            override=override,
            shared_caches=shared_caches,
            isin_search_timeout_sec=isin_search_timeout_sec,
            isin_quotes_count=isin_quotes_count,
            universe_region=universe_region,
            exists_lookback_period=exists_lookback_period,
            exists_retry_policy=exists_retry_policy,
            get_ticker_obj=self._build_get_ticker_obj(shared_caches=shared_caches),
            exists_checker=self._ticker_exists,
        )

        chosen, div = self._choose_candidate_with_dividends(
            candidates=candidate_resolution.candidates,
            shared_caches=shared_caches,
            start=start,
            end=end,
            start_ts=start_ts,
            end_ts=end_ts,
            try_one_retry_policy=try_one_retry_policy,
        )

        if chosen is None or div is None:
            exists_any, exists_ticker = self._probe_existing_candidate(
                candidates=candidate_resolution.candidates,
                candidate_resolution=candidate_resolution,
                exists_lookback_period=exists_lookback_period,
                shared_caches=shared_caches,
                exists_retry_policy=exists_retry_policy,
            )
            return self._emit_resolution_failure(
                row_ctx=row_ctx,
                row_isin=row_isin,
                override=override,
                candidate_resolution=candidate_resolution,
                exists_any=exists_any,
                exists_ticker=exists_ticker,
                start=start,
                end=end,
            )

        return self._build_success_result(
            row_ctx=row_ctx,
            row_isin=row_isin,
            override=override,
            candidate_resolution=candidate_resolution,
            chosen=chosen,
            div=div,
            start=start,
            end=end,
            asof_eff=asof_eff,
        )

    def _should_log_progress(
        self,
        *,
        completed: int,
        total: int,
        progress_every: int,
        last_logged_completed: int,
    ) -> bool:
        if completed == last_logged_completed:
            return False

        return completed == 1 or completed == total or (progress_every > 0 and completed % progress_every == 0)

    def _log_progress(
        self,
        *,
        completed: int,
        total: int,
        rows: list[dict[str, Any]],
        errs: list[dict[str, Any]],
        no_divs: list[dict[str, Any]],
        status_counter: dict[str, int],
    ) -> None:
        logger.warning(
            "[yfa] progress completed=%s/%s rows=%s errs=%s no_divs=%s status_counts=%s",
            completed,
            total,
            len(rows),
            len(errs),
            len(no_divs),
            ys.format_status_counter(status_counter),
        )

    def _run_parallel_fetch(
        self,
        *,
        universe: pd.DataFrame,
        start: str,
        end: str,
        start_ts: pd.Timestamp | None,
        end_ts: pd.Timestamp | None,
        exists_lookback_period: str,
        isin_search_timeout_sec: float,
        isin_quotes_count: int,
        universe_region: str,
        asof_eff: str,
        chosen_map_cache: dict[str, ym.OverrideResolution],
        shared_caches: ym.SharedCaches,
        try_one_retry_policy: ym.RetryPolicy,
        exists_retry_policy: ym.RetryPolicy,
        max_workers: int,
        progress_every: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        rows: list[dict[str, Any]] = []
        errs: list[dict[str, Any]] = []
        no_divs: list[dict[str, Any]] = []
        discovered_candidate_rows: list[dict[str, Any]] = []

        total = len(universe)
        completed = 0
        last_logged_completed = 0
        max_workers_eff = max(1, min(int(max_workers), max(1, total)))
        status_counter = ys.init_status_counter()

        logger.warning(
            "[yfa] start rows=%s max_workers=%s universe_region=%s start=%s end=%s",
            total,
            max_workers_eff,
            universe_region,
            start,
            end,
        )

        with ThreadPoolExecutor(max_workers=max_workers_eff) as executor:
            future_to_row = {
                executor.submit(
                    self._fetch_single_row,
                    row,
                    start=start,
                    end=end,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    exists_lookback_period=exists_lookback_period,
                    isin_search_timeout_sec=isin_search_timeout_sec,
                    isin_quotes_count=isin_quotes_count,
                    universe_region=universe_region,
                    asof_eff=asof_eff,
                    chosen_map_cache=chosen_map_cache,
                    shared_caches=shared_caches,
                    try_one_retry_policy=try_one_retry_policy,
                    exists_retry_policy=exists_retry_policy,
                ): row
                for row in universe.itertuples(index=False)
            }

            for future in as_completed(future_to_row):
                row_obj = future_to_row[future]

                try:
                    result = future.result()
                    ys.update_status_counter(status_counter, result)
                    rows.extend(result.rows)
                    errs.extend(result.errs)
                    no_divs.extend(result.no_divs)
                    discovered_candidate_rows.extend(result.discovered_candidate_rows)
                except Exception as exc:
                    logger.exception(
                        "[yfa] worker failure underlying=%s ccy=%s error_type=%s error=%s",
                        yu.clean_str(getattr(row_obj, "underlying", "")),
                        yu.normalise_ccy_safe(getattr(row_obj, "underlying_ccy", "")),
                        type(exc).__name__,
                        exc,
                    )
                    errs.append(
                        yr.build_worker_exception_error_row(
                            source=self.name,
                            row=row_obj,
                            start=start,
                            end=end,
                            exc=exc,
                        )
                    )
                    status_counter[ys.WORKER_EXCEPTION] += 1

                completed += 1

                if self._should_log_progress(
                    completed=completed,
                    total=total,
                    progress_every=progress_every,
                    last_logged_completed=last_logged_completed,
                ):
                    self._log_progress(
                        completed=completed,
                        total=total,
                        rows=rows,
                        errs=errs,
                        no_divs=no_divs,
                        status_counter=status_counter,
                    )
                    last_logged_completed = completed

        return rows, errs, no_divs, discovered_candidate_rows, status_counter

    def fetch_dividends(
        self,
        universe: pd.DataFrame,
        *,
        start: str = "",
        end: str = "",
        sleep_sec: float = 0.0,
        progress_every: int = 50,
        exists_lookback_period: str = "5d",
        chosen_map_path: str = "",
        return_details: bool = False,
        isin_search_timeout_sec: float = 10.0,
        isin_quotes_count: int = 10,
        universe_region: str = "EM",
        asof_date: str | None = None,
        max_workers: int = 8,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        del return_details

        if sleep_sec:
            logger.warning("sleep_sec is ignored in parallel mode: sleep_sec=%s", sleep_sec)

        start_ts = yu.parse_yyyymmdd(start)
        end_ts = yu.parse_yyyymmdd(end)
        asof_eff = self._resolve_asof_eff(asof_date=asof_date, end_ts=end_ts)

        chosen_map_cache = yo.load_chosen_map(chosen_map_path)
        shared_caches = self._build_shared_caches()
        try_one_retry_policy, exists_retry_policy = self._build_retry_policies()

        rows, errs, no_divs, discovered_candidate_rows, status_counter = self._run_parallel_fetch(
            universe=universe,
            start=start,
            end=end,
            start_ts=start_ts,
            end_ts=end_ts,
            exists_lookback_period=exists_lookback_period,
            isin_search_timeout_sec=isin_search_timeout_sec,
            isin_quotes_count=isin_quotes_count,
            universe_region=universe_region,
            asof_eff=asof_eff,
            chosen_map_cache=chosen_map_cache,
            shared_caches=shared_caches,
            try_one_retry_policy=try_one_retry_policy,
            exists_retry_policy=exists_retry_policy,
            max_workers=max_workers,
            progress_every=progress_every,
        )

        df, err_df, no_div_df, discovered_candidate_df = self._build_output_frames(
            rows=rows,
            errs=errs,
            no_divs=no_divs,
            discovered_candidate_rows=discovered_candidate_rows,
        )

        logger.warning(
            "[yfa] done rows=%s errs=%s no_divs=%s discovered_candidate_rows=%s status_counts=%s",
            len(df),
            len(err_df),
            len(no_div_df),
            len(discovered_candidate_df),
            ys.format_status_counter(status_counter),
        )

        return df, err_df, no_div_df, discovered_candidate_df