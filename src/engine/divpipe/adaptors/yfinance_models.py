# src/engine/divpipe/adaptors/yfinance_models.py

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, TypeVar

import pandas as pd


IsinCacheKey = str
HeuristicCacheKey = tuple[str, str, str | None, str, str, str]
DivCacheKey = tuple[str, str, str]
ExistsCacheKey = tuple[str, str]

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class Candidate:
    market: str
    yfinance_ticker: str
    method: str = ""
    origin: str = ""
    canonical_exchange: str = ""
    guess_source: str = ""
    isin_prefix: str = ""
    prefix_exchange_consistent: bool | None = None


@dataclass(frozen=True)
class RowContext:
    underlying: str
    ccy: str
    isin: str
    country: str | None
    weight: float | None
    map_key: str
    name: str
    exchange: str


@dataclass(frozen=True)
class OverrideResolution:
    ticker: str
    reason: str
    method: str
    source: str
    isin: str

    @property
    def is_present(self) -> bool:
        return bool(self.ticker.strip())

    @property
    def is_unsupported_vendor(self) -> bool:
        return self.ticker.strip().upper().startswith("UNSUPPORTED_")


@dataclass(frozen=True)
class CandidateResolution:
    candidates: list[Candidate]
    reason: str
    preverified_exists_any: bool = False
    preverified_exists_ticker: str = ""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_sec: float
    backoff_factor: float
    jitter_ratio: float


@dataclass
class SharedCaches:
    isin_cache: dict[IsinCacheKey, list[Candidate]]
    heuristic_cache: dict[HeuristicCacheKey, list[Candidate]]
    div_cache: dict[DivCacheKey, pd.Series | None]
    exists_cache: dict[ExistsCacheKey, bool]
    ticker_cache: dict[str, Any] = field(default_factory=dict)

    isin_lock: threading.Lock = field(default_factory=threading.Lock)
    heuristic_lock: threading.Lock = field(default_factory=threading.Lock)
    div_lock: threading.Lock = field(default_factory=threading.Lock)
    exists_lock: threading.Lock = field(default_factory=threading.Lock)
    ticker_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(slots=True)
class FetchSingleRowResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    errs: list[dict[str, Any]] = field(default_factory=list)
    no_divs: list[dict[str, Any]] = field(default_factory=list)
    discovered_candidate_rows: list[dict[str, Any]] = field(default_factory=list)


def empty_fetch_single_row_result() -> FetchSingleRowResult:
    return FetchSingleRowResult()