# tests/test_ticker_resolution_cache.py

from __future__ import annotations

from pathlib import Path

import pandas as pd

from engine.divpipe.pipeline.ticker_resolution_cache import (
    build_cache_updates_from_discovered_candidates,
    build_effective_chosen_map,
    load_override_table,
    load_resolution_cache,
    upsert_resolution_cache,
)


def test_load_override_table_returns_empty_when_missing(tmp_path: Path) -> None:
    out = load_override_table(tmp_path / "missing.csv")
    assert out.empty
    assert list(out.columns) == [
        "underlying",
        "underlying_ccy",
        "chosen_ticker",
        "reason",
        "method",
        "isin",
        "exists_ns",
        "exists_bo",
    ]


def test_load_resolution_cache_returns_empty_when_missing(tmp_path: Path) -> None:
    out = load_resolution_cache(tmp_path / "missing.csv")
    assert out.empty
    assert list(out.columns) == [
        "underlying",
        "underlying_ccy",
        "isin",
        "chosen_ticker",
        "reason",
        "method",
        "exists_ns",
        "exists_bo",
        "resolution_status",
        "candidate_market",
        "resolution_source",
        "first_seen_asof",
        "last_seen_asof",
        "last_validated_run_id",
    ]


def test_build_effective_chosen_map_prefers_override(tmp_path: Path) -> None:
    override_path = tmp_path / "chosen_ticker_overrides.csv"
    cache_path = tmp_path / "ticker_resolution_cache.csv"

    pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "usd",
                "chosen_ticker": "ABC.OVR",
                "reason": "manual_override",
                "method": "override",
                "isin": "US0000000001",
                "exists_ns": False,
                "exists_bo": False,
            }
        ]
    ).to_csv(override_path, index=False, encoding="utf-8-sig")

    pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "chosen_ticker": "ABC.CACHE",
                "reason": "div_found",
                "method": "cache",
                "exists_ns": False,
                "exists_bo": False,
                "resolution_status": "DIV_FOUND",
                "candidate_market": "US",
                "resolution_source": "cache",
                "first_seen_asof": "20260213",
                "last_seen_asof": "20260213",
                "last_validated_run_id": "run1",
            }
        ]
    ).to_csv(cache_path, index=False, encoding="utf-8-sig")

    out = build_effective_chosen_map(
        override_path=override_path,
        cache_path=cache_path,
    )

    assert len(out) == 1
    assert out.loc[0, "chosen_ticker"] == "ABC.OVR"
    assert out.loc[0, "method"] == "override"


def test_build_cache_updates_from_discovered_candidates_filters_statuses() -> None:
    discovered = pd.DataFrame(
        [
            {
                "underlying": "PBBANK",
                "underlying_ccy": "MYR",
                "isin": "MYL1295OO004",
                "chosen_ticker": "PBBANK.KL",
                "candidate_market": "KL",
                "resolution_status": "div_found",
                "resolution_reason": "override",
                "resolution_method": "override",
                "resolution_source": "chosen_map",
                "exists_ns": False,
                "exists_bo": False,
            },
            {
                "underlying": "BAD",
                "underlying_ccy": "USD",
                "isin": "",
                "chosen_ticker": "",
                "candidate_market": "",
                "resolution_status": "ticker_not_found",
                "resolution_reason": "",
                "resolution_method": "",
                "resolution_source": "",
                "exists_ns": False,
                "exists_bo": False,
            },
        ]
    )

    out = build_cache_updates_from_discovered_candidates(
        discovered,
        asof_date="20260213",
        run_id="run_001",
        accepted_statuses=("div_found",),
    )

    assert len(out) == 1
    assert out.loc[0, "underlying"] == "PBBANK"
    assert out.loc[0, "chosen_ticker"] == "PBBANK.KL"
    assert out.loc[0, "resolution_status"] == "DIV_FOUND"
    assert out.loc[0, "first_seen_asof"] == "20260213"
    assert out.loc[0, "last_seen_asof"] == "20260213"


def test_upsert_resolution_cache_adds_div_found_rows(tmp_path: Path) -> None:
    cache_path = tmp_path / "ticker_resolution_cache.csv"

    discovered = pd.DataFrame(
        [
            {
                "underlying": "PBBANK",
                "underlying_ccy": "MYR",
                "isin": "MYL1295OO004",
                "chosen_ticker": "PBBANK.KL",
                "candidate_market": "KL",
                "resolution_status": "div_found",
                "resolution_reason": "override",
                "resolution_method": "override",
                "resolution_source": "chosen_map",
                "exists_ns": False,
                "exists_bo": False,
            }
        ]
    )

    out = upsert_resolution_cache(
        cache_path=cache_path,
        discovered_candidate_df=discovered,
        asof_date="20260213",
        run_id="run_001",
        accepted_statuses=("div_found",),
    )

    assert len(out) == 1
    assert out.loc[0, "underlying"] == "PBBANK"
    assert out.loc[0, "chosen_ticker"] == "PBBANK.KL"
    assert out.loc[0, "first_seen_asof"] == "20260213"
    assert out.loc[0, "last_seen_asof"] == "20260213"
    assert out.loc[0, "last_validated_run_id"] == "run_001"


def test_upsert_resolution_cache_updates_existing_and_preserves_first_seen(tmp_path: Path) -> None:
    cache_path = tmp_path / "ticker_resolution_cache.csv"

    pd.DataFrame(
        [
            {
                "underlying": "PBBANK",
                "underlying_ccy": "MYR",
                "isin": "MYL1295OO004",
                "chosen_ticker": "OLD.KL",
                "reason": "old",
                "method": "old",
                "exists_ns": False,
                "exists_bo": False,
                "resolution_status": "DIV_FOUND",
                "candidate_market": "KL",
                "resolution_source": "cache",
                "first_seen_asof": "20250101",
                "last_seen_asof": "20250101",
                "last_validated_run_id": "old_run",
            }
        ]
    ).to_csv(cache_path, index=False, encoding="utf-8-sig")

    discovered = pd.DataFrame(
        [
            {
                "underlying": "PBBANK",
                "underlying_ccy": "MYR",
                "isin": "MYL1295OO004",
                "chosen_ticker": "PBBANK.KL",
                "candidate_market": "KL",
                "resolution_status": "div_found",
                "resolution_reason": "override",
                "resolution_method": "override",
                "resolution_source": "chosen_map",
                "exists_ns": False,
                "exists_bo": False,
            }
        ]
    )

    out = upsert_resolution_cache(
        cache_path=cache_path,
        discovered_candidate_df=discovered,
        asof_date="20260213",
        run_id="run_002",
        accepted_statuses=("div_found",),
    )

    assert len(out) == 1
    assert out.loc[0, "chosen_ticker"] == "PBBANK.KL"
    assert out.loc[0, "first_seen_asof"] == "20250101"
    assert out.loc[0, "last_seen_asof"] == "20260213"
    assert out.loc[0, "last_validated_run_id"] == "run_002"


def test_upsert_resolution_cache_uses_latest_row_for_same_key(tmp_path: Path) -> None:
    cache_path = tmp_path / "ticker_resolution_cache.csv"

    pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "chosen_ticker": "ABC.OLD",
                "reason": "old",
                "method": "old",
                "exists_ns": False,
                "exists_bo": False,
                "resolution_status": "DIV_FOUND",
                "candidate_market": "US",
                "resolution_source": "cache",
                "first_seen_asof": "20250101",
                "last_seen_asof": "20250101",
                "last_validated_run_id": "run_001",
            }
        ]
    ).to_csv(cache_path, index=False, encoding="utf-8-sig")

    discovered = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "USD",
                "isin": "US0000000001",
                "chosen_ticker": "ABC.NEW",
                "candidate_market": "US",
                "resolution_status": "div_found",
                "resolution_reason": "mapped",
                "resolution_method": "cache_refresh",
                "resolution_source": "chosen_map",
                "exists_ns": False,
                "exists_bo": False,
            }
        ]
    )

    out = upsert_resolution_cache(
        cache_path=cache_path,
        discovered_candidate_df=discovered,
        asof_date="20260213",
        run_id="run_999",
        accepted_statuses=("div_found",),
    )

    assert len(out) == 1
    assert out.loc[0, "chosen_ticker"] == "ABC.NEW"

def test_build_cache_updates_from_discovered_candidates_keeps_last_accepted_duplicate() -> None:
    discovered = pd.DataFrame(
        [
            {
                "underlying": "ABC",
                "underlying_ccy": "MYR",
                "isin": "MY0000000001",
                "chosen_ticker": "ABC.KL",
                "candidate_market": "KL",
                "resolution_status": "div_found",
                "resolution_reason": "heuristic",
                "resolution_method": "auto_search",
                "resolution_source": "auto_search",
                "exists_ns": False,
                "exists_bo": False,
            },
            {
                "underlying": "ABC",
                "underlying_ccy": "MYR",
                "isin": "MY0000000001",
                "chosen_ticker": "ABC.NS",
                "candidate_market": "NS",
                "resolution_status": "candidate_unverified",
                "resolution_reason": "heuristic",
                "resolution_method": "auto_search",
                "resolution_source": "auto_search",
                "exists_ns": True,
                "exists_bo": False,
            },
            {
                "underlying": "ABC",
                "underlying_ccy": "MYR",
                "isin": "MY0000000001",
                "chosen_ticker": "ABC2.KL",
                "candidate_market": "KL",
                "resolution_status": "div_found",
                "resolution_reason": "override",
                "resolution_method": "override",
                "resolution_source": "chosen_map",
                "exists_ns": False,
                "exists_bo": False,
            },
        ]
    )

    out = build_cache_updates_from_discovered_candidates(
        discovered,
        asof_date="20260213",
        run_id="run_dup",
        accepted_statuses=("div_found",),
    )

    assert len(out) == 1
    assert out.loc[0, "underlying"] == "ABC"
    assert out.loc[0, "underlying_ccy"] == "MYR"
    assert out.loc[0, "chosen_ticker"] == "ABC2.KL"
    assert out.loc[0, "resolution_status"] == "DIV_FOUND"