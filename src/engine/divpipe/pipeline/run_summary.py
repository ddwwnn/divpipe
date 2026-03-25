# src/engine/divpipe/pipeline/run_summary.py

from __future__ import annotations

from typing import Any, Protocol, Sequence

import pandas as pd

from .ticker_qa import summarise_ticker_qa


class Stage1SummaryResultProtocol(Protocol):
    tag: str
    holdings_path: Any
    universe_region: str
    stage_dir: Any
    universe_rows: int
    valid_universe_rows: int
    seed_df: pd.DataFrame | None
    err_df: pd.DataFrame | None
    no_div_df: pd.DataFrame | None
    discovered_candidate_df: pd.DataFrame | None
    input_rejection_df: pd.DataFrame | None
    ticker_qa_summary: dict[str, Any] | None
    failed: bool
    abort_run: bool
    started_at: str
    finished_at: str
    elapsed_seconds: float
    error: str | None
    error_kind: str | None


def summarise_error_rows_by_type(
    results: Sequence[Stage1SummaryResultProtocol],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for result in results:
        err_df = result.err_df
        if err_df is None or err_df.empty or "error" not in err_df.columns:
            continue

        series = err_df["error"].astype("string").fillna("").str.strip()
        value_counts = series[series != ""].value_counts(dropna=False)

        for key, value in value_counts.items():
            counts[str(key)] = counts.get(str(key), 0) + int(value)

    return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def summarise_input_rejections_by_reason(
    results: Sequence[Stage1SummaryResultProtocol],
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for result in results:
        input_rejection_df = result.input_rejection_df
        if input_rejection_df is None or input_rejection_df.empty:
            continue
        if "reason" not in input_rejection_df.columns:
            continue

        series = input_rejection_df["reason"].astype("string").fillna("").str.strip()
        value_counts = series[series != ""].value_counts(dropna=False)

        for key, value in value_counts.items():
            counts[str(key)] = counts.get(str(key), 0) + int(value)

    return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def derive_run_status(summary: dict[str, Any]) -> str:
    failed_tag_count = int(summary.get("failed_tag_count", 0) or 0)
    error_rows = int(summary.get("error_rows", 0) or 0)

    if failed_tag_count > 0:
        return "partial_failure"

    if error_rows > 0:
        return "complete_with_review"

    return "complete"


def build_stage1_summary(
    results: Sequence[Stage1SummaryResultProtocol],
) -> dict[str, Any]:
    failed_results = [result for result in results if result.failed]
    elapsed_values = [float(result.elapsed_seconds or 0.0) for result in results]
    error_rows_by_type = summarise_error_rows_by_type(results)
    input_rejections_by_reason = summarise_input_rejections_by_reason(results)

    return {
        "tags": [result.tag for result in results],
        "regions": [result.universe_region for result in results],
        "tag_count": len(results),
        "seed_rows": int(
            sum(0 if result.seed_df is None else len(result.seed_df) for result in results)
        ),
        "error_rows": int(
            sum(0 if result.err_df is None else len(result.err_df) for result in results)
        ),
        "error_rows_by_type": error_rows_by_type,
        "no_div_rows": int(
            sum(0 if result.no_div_df is None else len(result.no_div_df) for result in results)
        ),
        "discovered_candidate_rows": int(
            sum(
                0
                if result.discovered_candidate_df is None
                else len(result.discovered_candidate_df)
                for result in results
            )
        ),
        "input_rejection_rows": int(
            sum(
                0
                if result.input_rejection_df is None
                else len(result.input_rejection_df)
                for result in results
            )
        ),
        "input_rejections_by_reason": input_rejections_by_reason,
        "failed_tags": [
            {
                "tag": result.tag,
                "region": result.universe_region,
                "stage_dir": str(result.stage_dir),
                "holdings_file": str(result.holdings_path),
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "elapsed_seconds": result.elapsed_seconds,
                "error_kind": result.error_kind or "",
                "error": result.error or "",
                "abort_run": bool(result.abort_run),
            }
            for result in failed_results
        ],
        "tag_metrics": [
            {
                "tag": result.tag,
                "region": result.universe_region,
                "universe_rows": result.universe_rows,
                "valid_universe_rows": result.valid_universe_rows,
                "input_rejection_rows": 0 if result.input_rejection_df is None else len(result.input_rejection_df),
                "seed_rows": 0 if result.seed_df is None else len(result.seed_df),
                "error_rows": 0 if result.err_df is None else len(result.err_df),
                "no_div_rows": 0 if result.no_div_df is None else len(result.no_div_df),
                "discovered_candidate_rows": (
                    0 if result.discovered_candidate_df is None else len(result.discovered_candidate_df)
                ),
                "ticker_failed_rows": (
                    0
                    if result.ticker_qa_summary is None
                    else int(result.ticker_qa_summary.get("failed_rows", 0))
                ),
                "ticker_anomaly_rows": (
                    0
                    if result.ticker_qa_summary is None
                    else int(result.ticker_qa_summary.get("anomaly_rows", 0))
                ),
                "ticker_review_queue_rows": (
                    0
                    if result.ticker_qa_summary is None
                    else int(result.ticker_qa_summary.get("review_queue_rows", 0))
                ),
                "ticker_failed_weight_sum": (
                    0.0
                    if result.ticker_qa_summary is None
                    else float(result.ticker_qa_summary.get("failed_weight_sum", 0.0))
                ),
                "ticker_anomaly_weight_sum": (
                    0.0
                    if result.ticker_qa_summary is None
                    else float(result.ticker_qa_summary.get("anomaly_weight_sum", 0.0))
                ),
                "failed": result.failed,
                "abort_run": result.abort_run,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "elapsed_seconds": result.elapsed_seconds,
                "error_kind": result.error_kind or "",
            }
            for result in results
        ],
        "failed_tag_count": len(failed_results),
        "successful_tag_count": len(results) - len(failed_results),
        "timing": {
            "total_elapsed_seconds": round(sum(elapsed_values), 6),
            "max_tag_elapsed_seconds": round(max(elapsed_values), 6) if elapsed_values else 0.0,
            "mean_tag_elapsed_seconds": (
                round(sum(elapsed_values) / len(elapsed_values), 6)
                if elapsed_values
                else 0.0
            ),
        },
    }


def augment_stage1_summary_with_ticker_qa(
    summary: dict[str, Any],
    *,
    report_df: pd.DataFrame,
    failed_df: pd.DataFrame,
    anomaly_df: pd.DataFrame,
    review_df: pd.DataFrame,
    latest_symlink_updated: bool,
    latest_txt_written: bool,
    ticker_map_report_path: str,
    ticker_failed_queue_path: str,
    ticker_anomaly_queue_path: str,
    ticker_review_queue_path: str,
) -> dict[str, Any]:
    summary = dict(summary)
    qa_summary = summarise_ticker_qa(report_df)

    summary["ticker_qa"] = {
        "report_rows": int(len(report_df)),
        "failed_rows": int(len(failed_df)),
        "anomaly_rows": int(len(anomaly_df)),
        "review_queue_rows": int(len(review_df)),
        "failed_weight_sum": round(float(qa_summary.get("failed_weight_sum", 0.0)), 12),
        "anomaly_weight_sum": round(float(qa_summary.get("anomaly_weight_sum", 0.0)), 12),
        "max_failed_weight": round(float(qa_summary.get("max_failed_weight", 0.0)), 12),
        "unmatched_failed_count": int(qa_summary.get("unmatched_failed_count", 0)),
        "unmatched_failed_weight_sum": round(float(qa_summary.get("unmatched_failed_weight_sum", 0.0)), 12),
        "artefacts": {
            "ticker_map_report": ticker_map_report_path,
            "ticker_failed_queue": ticker_failed_queue_path,
            "ticker_anomaly_queue": ticker_anomaly_queue_path,
            "ticker_review_queue": ticker_review_queue_path,
        },
    }
    summary["latest_pointer"] = {
        "latest_symlink_updated": bool(latest_symlink_updated),
        "latest_txt_written": bool(latest_txt_written),
        "fallback_used": bool(latest_txt_written and not latest_symlink_updated),
    }

    return summary