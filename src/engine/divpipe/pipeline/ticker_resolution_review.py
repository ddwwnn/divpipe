# src/engine/divpipe/pipeline/ticker_resolution_review.py

from __future__ import annotations

import json
from typing import Sequence

import pandas as pd

from .ticker_qa import UniverseWeightMaps, build_ticker_map_report
from .ticker_resolution_canonical import (
    FAILURE_STATUSES,
    STATUS_CANDIDATE_UNVERIFIED,
)

REVIEW_BASE_COLUMNS = [
    "underlying",
    "underlying_ccy",
    "isin",
    "chosen_ticker",
    "candidate_market",
    "candidate_origin",
    "resolution_status",
    "review_reason",
    "review_tags_json",
    "review_tags_text",
    "resolution_reason",
    "resolution_method",
    "resolution_source",
    "candidate_count",
    "candidates_json",
    "guess_source",
    "canonical_exchange",
    "isin_prefix",
    "prefix_exchange_consistent",
    "exists_probe_symbol",
    "exists_probe_result",
    "weight",
    "weight_matched",
    "weight_match_method",
    "is_failed",
    "is_anomaly",
    "holdings_tag",
    "holdings_file",
    "source",
    "start",
    "end",
]


def _empty_review_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=REVIEW_BASE_COLUMNS)


def _clean_text_series(s: pd.Series, *, upper: bool = False) -> pd.Series:
    out = s.astype("string").fillna("").str.strip()
    out = out.replace(
        {
            "<NA>": "",
            "None": "",
            "NONE": "",
            "nan": "",
            "NaN": "",
            "NAN": "",
        }
    )
    if upper:
        out = out.str.upper()
    return out


def _serialise_review_tags(tags: list[str]) -> str:
    return json.dumps(tags, ensure_ascii=False)


def _serialise_review_tags_text(tags: list[str]) -> str:
    return "|".join(tags)


def _dedupe_keep_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys([str(value).strip() for value in values if str(value).strip()]))


def _bool_series(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype="bool")
    return df[col].fillna(default).astype("bool")


def _string_series(df: pd.DataFrame, col: str, *, upper: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="string")
    return _clean_text_series(df[col], upper=upper)


def _is_explicit_prefix_inconsistent(value: object) -> bool:
    if pd.isna(value):
        return False
    return bool(value) is False


def _is_explicit_guess_source_anomaly(value: str) -> bool:
    text = str(value).strip().lower()
    return text in {"country_fallback", "ccy_fallback"}


def _build_review_tag_lists(
    report: pd.DataFrame,
    *,
    suspect_statuses_norm: set[str],
    include_statuses_norm: set[str],
    include_anomalies: bool,
) -> list[list[str]]:
    status = _string_series(report, "resolution_status", upper=True)
    guess_source = _string_series(report, "guess_source", upper=False)
    is_failed = _bool_series(report, "is_failed")
    weight_matched = _bool_series(report, "weight_matched", default=False)
    is_anomaly = (
        _bool_series(report, "is_anomaly", default=False)
        if include_anomalies
        else pd.Series([False] * len(report), index=report.index, dtype="bool")
    )

    if "prefix_exchange_consistent" in report.columns:
        prefix_exchange_consistent = report["prefix_exchange_consistent"]
    else:
        prefix_exchange_consistent = pd.Series([pd.NA] * len(report), index=report.index, dtype="boolean")

    candidate_unverified_statuses = suspect_statuses_norm | {STATUS_CANDIDATE_UNVERIFIED}
    hard_failure_statuses = {
        str(x).strip().upper()
        for x in FAILURE_STATUSES
        if str(x).strip().upper() not in candidate_unverified_statuses
    }

    tags_per_row: list[list[str]] = []

    for idx in report.index:
        row_tags: list[str] = []

        row_status = str(status.loc[idx]).strip().upper()
        row_guess_source = str(guess_source.loc[idx]).strip().lower()
        row_is_failed = bool(is_failed.loc[idx])
        row_weight_matched = bool(weight_matched.loc[idx])
        row_is_anomaly = bool(is_anomaly.loc[idx])

        row_prefix_bad = _is_explicit_prefix_inconsistent(prefix_exchange_consistent.loc[idx])
        row_guess_anomaly = _is_explicit_guess_source_anomaly(row_guess_source)

        row_has_explicit_anomaly_signal = row_guess_anomaly or row_prefix_bad
        row_include_anomaly = include_anomalies and row_is_anomaly and row_has_explicit_anomaly_signal

        if row_status in hard_failure_statuses:
            row_tags.append("hard_failure")
        elif row_status in include_statuses_norm and row_status in candidate_unverified_statuses:
            row_tags.append("candidate_unverified")
        elif row_status in candidate_unverified_statuses:
            row_tags.append("candidate_unverified")

        if row_is_failed and not row_weight_matched and row_status not in candidate_unverified_statuses:
            row_tags.append("failed_weight_unmatched")

        if row_include_anomaly:
            row_tags.append("anomaly_review")

            if row_guess_anomaly:
                row_tags.append(row_guess_source)

            if row_prefix_bad:
                row_tags.append("prefix_exchange_inconsistent")

        row_tags = _dedupe_keep_order(row_tags)
        tags_per_row.append(row_tags)

    return tags_per_row


def _build_review_tags_json(tag_lists: list[list[str]], index: pd.Index) -> pd.Series:
    return pd.Series(
        [_serialise_review_tags(tags) for tags in tag_lists],
        index=index,
        dtype="string",
    )


def _build_review_tags_text(tag_lists: list[list[str]], index: pd.Index) -> pd.Series:
    return pd.Series(
        [_serialise_review_tags_text(tags) for tags in tag_lists],
        index=index,
        dtype="string",
    )


def _pick_primary_review_reason(tag_lists: list[list[str]], index: pd.Index) -> pd.Series:
    priority_order = [
        "hard_failure",
        "failed_weight_unmatched",
        "candidate_unverified",
        "anomaly_review",
    ]

    reasons: list[str] = []

    for tags in tag_lists:
        reason = ""
        for tag in priority_order:
            if tag in tags:
                reason = tag
                break
        reasons.append(reason)

    return pd.Series(reasons, index=index, dtype="string")


def _review_reason_rank(s: pd.Series) -> pd.Series:
    rank_map = {
        "hard_failure": 0,
        "failed_weight_unmatched": 1,
        "candidate_unverified": 2,
        "anomaly_review": 3,
    }
    return s.astype("string").map(rank_map).fillna(99).astype("int64")


def build_ticker_resolution_review_queue(
    discovered_candidate_df: pd.DataFrame | None,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: UniverseWeightMaps | None = None,
    suspect_no_div_statuses: Sequence[str] = ("candidate_unverified",),
    include_statuses: Sequence[str] = ("ticker_not_found", "candidate_unverified"),
    include_anomalies: bool = True,
) -> pd.DataFrame:
    if discovered_candidate_df is None or discovered_candidate_df.empty:
        return _empty_review_frame()

    original = discovered_candidate_df.copy()

    report = build_ticker_map_report(
        discovered_candidate_df,
        universe_df=universe_df,
        universe_maps=universe_maps,
        run_materiality_gate=False,
    )

    suspect_statuses_norm = {str(x).strip().upper() for x in suspect_no_div_statuses if str(x).strip()}
    include_statuses_norm = {str(x).strip().upper() for x in include_statuses if str(x).strip()}

    status = _string_series(report, "resolution_status", upper=True)
    is_failed = _bool_series(report, "is_failed")
    weight_matched = _bool_series(report, "weight_matched", default=False)
    is_anomaly = (
        _bool_series(report, "is_anomaly", default=False)
        if include_anomalies
        else pd.Series([False] * len(report), index=report.index, dtype="bool")
    )
    guess_source = _string_series(report, "guess_source", upper=False).str.strip().str.lower()

    if "prefix_exchange_consistent" in report.columns:
        prefix_exchange_consistent = report["prefix_exchange_consistent"]
    else:
        prefix_exchange_consistent = pd.Series([pd.NA] * len(report), index=report.index, dtype="boolean")

    candidate_unverified_statuses = suspect_statuses_norm | {STATUS_CANDIDATE_UNVERIFIED}
    hard_failure_statuses = {
        str(x).strip().upper()
        for x in FAILURE_STATUSES
        if str(x).strip().upper() not in candidate_unverified_statuses
    }

    status_review_mask = status.isin(include_statuses_norm)
    candidate_unverified_mask = status.isin(candidate_unverified_statuses)
    hard_failure_mask = status.isin(hard_failure_statuses)
    failed_weight_unmatched_mask = is_failed & ~weight_matched & ~candidate_unverified_mask

    guess_anomaly_mask = guess_source.isin({"country_fallback", "ccy_fallback"})
    prefix_bad_mask = prefix_exchange_consistent.fillna(True).eq(False)
    explicit_anomaly_mask = is_anomaly & (guess_anomaly_mask | prefix_bad_mask) if include_anomalies else pd.Series(
        [False] * len(report), index=report.index, dtype="bool"
    )

    review_mask = (
        status_review_mask
        | hard_failure_mask
        | candidate_unverified_mask
        | failed_weight_unmatched_mask
        | explicit_anomaly_mask
    )

    report = report.loc[review_mask].copy()
    original = original.loc[review_mask].copy()

    if report.empty:
        extra_cols = [c for c in discovered_candidate_df.columns if c not in REVIEW_BASE_COLUMNS]
        return pd.DataFrame(columns=REVIEW_BASE_COLUMNS + extra_cols)

    tag_lists = _build_review_tag_lists(
        report,
        suspect_statuses_norm=suspect_statuses_norm,
        include_statuses_norm=include_statuses_norm,
        include_anomalies=include_anomalies,
    )

    report["review_tags_json"] = _build_review_tags_json(tag_lists, report.index)
    report["review_tags_text"] = _build_review_tags_text(tag_lists, report.index)
    report["review_reason"] = _pick_primary_review_reason(tag_lists, report.index)

    base = report.reindex(columns=REVIEW_BASE_COLUMNS)

    extra_cols = [c for c in original.columns if c not in base.columns]
    if extra_cols:
        base = pd.concat(
            [base.reset_index(drop=True), original[extra_cols].reset_index(drop=True)],
            axis=1,
        )

    base = base.drop_duplicates(
        subset=[
            "underlying",
            "underlying_ccy",
            "isin",
            "chosen_ticker",
            "resolution_status",
            "review_tags_json",
        ],
        keep="first",
    ).reset_index(drop=True)

    base["_review_reason_rank"] = _review_reason_rank(base["review_reason"])
    sort_cols = [c for c in ["_review_reason_rank", "weight", "underlying", "chosen_ticker"] if c in base.columns]
    ascending = [True, False, True, True][: len(sort_cols)]
    base = base.sort_values(sort_cols, ascending=ascending, kind="stable").reset_index(drop=True)
    base = base.drop(columns=["_review_reason_rank"], errors="ignore")

    return base