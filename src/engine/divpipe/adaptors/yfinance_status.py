# src/engine/divpipe/adaptors/yfinance_status.py

from __future__ import annotations

from collections import Counter
from typing import Final

from . import yfinance_models as ym
from . import yfinance_utils as yu


DIV_FOUND: Final = "div_found"
VERIFIED_EXISTS_BUT_NO_DIVIDENDS: Final = "verified_exists_but_no_dividends"
CANDIDATE_UNVERIFIED: Final = "candidate_unverified"
TICKER_NOT_FOUND: Final = "ticker_not_found"
UNSUPPORTED_VENDOR: Final = "unsupported_vendor"
WORKER_EXCEPTION: Final = "worker_exception"
UNKNOWN_STATUS: Final = "unknown_status"

_STATUS_ORDER: Final[tuple[str, ...]] = (
    DIV_FOUND,
    VERIFIED_EXISTS_BUT_NO_DIVIDENDS,
    CANDIDATE_UNVERIFIED,
    TICKER_NOT_FOUND,
    UNSUPPORTED_VENDOR,
    WORKER_EXCEPTION,
    UNKNOWN_STATUS,
)

_VALID_ERROR_STATUS_SET: Final[frozenset[str]] = frozenset(
    {
        VERIFIED_EXISTS_BUT_NO_DIVIDENDS,
        CANDIDATE_UNVERIFIED,
        TICKER_NOT_FOUND,
        WORKER_EXCEPTION,
    }
)


def status_for_resolution_failure(
    *,
    candidate_count_: int,
    exists_any: bool,
) -> str:
    if exists_any:
        return VERIFIED_EXISTS_BUT_NO_DIVIDENDS
    if candidate_count_ > 0:
        return CANDIDATE_UNVERIFIED
    return TICKER_NOT_FOUND


error_for_resolution_failure = status_for_resolution_failure


def no_div_status_for_resolution_failure(
    *,
    exists_any: bool,
) -> str:
    return VERIFIED_EXISTS_BUT_NO_DIVIDENDS if exists_any else CANDIDATE_UNVERIFIED


def init_status_counter() -> Counter[str]:
    return Counter({status: 0 for status in _STATUS_ORDER})


def extract_result_status(result: ym.FetchSingleRowResult) -> str:
    if result.discovered_candidate_rows:
        status = yu.clean_str(result.discovered_candidate_rows[0].get("resolution_status", ""))
        if status:
            return status

    if result.no_divs:
        status = yu.clean_str(result.no_divs[0].get("status", ""))
        if status:
            return status

    if result.errs:
        error = yu.clean_str(result.errs[0].get("error", ""))
        if error in _VALID_ERROR_STATUS_SET:
            return error

    return UNKNOWN_STATUS


def update_status_counter(counter: Counter[str], result: ym.FetchSingleRowResult) -> None:
    counter[extract_result_status(result)] += 1


def format_status_counter(counter: dict[str, int]) -> str:
    ordered_items: list[tuple[str, int]] = []
    seen: set[str] = set()

    for key in _STATUS_ORDER:
        value = int(counter.get(key, 0))
        if value > 0:
            ordered_items.append((key, value))
            seen.add(key)

    extra_items = [
        (str(key), int(value))
        for key, value in counter.items()
        if str(key) not in seen and int(value) > 0
    ]
    extra_items.sort(key=lambda item: item[0])

    ordered_items.extend(extra_items)

    if not ordered_items:
        return "none"

    return ", ".join(f"{key}={value}" for key, value in ordered_items)