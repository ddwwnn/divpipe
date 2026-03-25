# src/engine/divpipe/run_pipeline.py

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, Sequence

import pandas as pd

from .artefacts import Artefacts
from .paths import RunPaths
from .pipeline.input_validation import split_valid_and_rejected_universe
from .pipeline.no_div_buckets import write_no_div_bucket_files
from .pipeline.run_latest import should_publish_latest, update_latest_symlink
from .pipeline.run_outputs import (
    concat_or_empty,
    drop_heavy_stage1_frames,
    empty_frame,
    ensure_required_columns,
    write_csv,
    write_csv_or_empty,
    write_err_csv,
    write_stage1_aggregate_outputs,
)
from .pipeline.run_summary import (
    augment_stage1_summary_with_ticker_qa,
    build_stage1_summary,
    derive_run_status,
)
from .pipeline.run_validation import validate_args
from .pipeline.seed_universe import build_universe, load_holdings
from .pipeline.ticker_qa import (
    anomaly_tickers,
    build_ticker_map_report,
    failed_tickers,
    prepare_universe_weight_maps,
    summarise_ticker_qa,
)
from .pipeline.ticker_resolution_cache import (
    upsert_resolution_cache,
    write_effective_chosen_map,
)
from .pipeline.ticker_resolution_review import build_ticker_resolution_review_queue
from .schema.columns import (
    DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
    STAGE1_DIVIDENDS_REQUIRED_COLUMNS,
    STAGE1_ERRORS_REQUIRED_COLUMNS,
    STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
)
from .utils.path_display import format_display_path
from .utils.repo import get_repo_root

logger = logging.getLogger(__name__)

_STAGE1_NUMERIC_COLS = ["amount", "weight"]
_STAGE1_CRITICAL_NUMERIC_COLS = ["amount", "weight"]
_DEFAULT_SEED_COLS = list(STAGE1_DIVIDENDS_REQUIRED_COLUMNS)
_VALID_REGIONS = {"EM", "DM"}

_INPUT_REJECTION_COLUMNS = [
    "source",
    "underlying_raw",
    "underlying_normalised",
    "underlying_ccy",
    "isin",
    "reason",
    "holdings_tag",
    "holdings_file",
]

_STAGE1_TICKER_QA_REPORT_PATH = "ticker_map_report.csv"
_STAGE1_TICKER_FAILED_QUEUE_PATH = "ticker_failed_queue.csv"
_STAGE1_TICKER_ANOMALY_QUEUE_PATH = "ticker_anomaly_queue.csv"
_STAGE1_TICKER_REVIEW_QUEUE_PATH = "ticker_resolution_review_queue.csv"

_TAG_TICKER_QA_REPORT_FILENAME = "ticker_map_report.csv"
_TAG_TICKER_FAILED_QUEUE_FILENAME = "ticker_failed_queue.csv"
_TAG_TICKER_ANOMALY_QUEUE_FILENAME = "ticker_anomaly_queue.csv"
_TAG_TICKER_REVIEW_QUEUE_FILENAME = "ticker_resolution_review_queue.csv"
_TAG_TICKER_QA_SUMMARY_FILENAME = "ticker_qa_summary.json"


class _TagTickerQAGateError(RuntimeError):
    pass


@dataclass(slots=True)
class Stage1TagResult:
    tag: str
    holdings_path: Path
    universe_region: str
    stage_dir: Path
    universe_rows: int
    valid_universe_rows: int = 0
    universe_df: pd.DataFrame | None = None
    seed_df: pd.DataFrame | None = None
    err_df: pd.DataFrame | None = None
    no_div_df: pd.DataFrame | None = None
    discovered_candidate_df: pd.DataFrame | None = None
    input_rejection_df: pd.DataFrame | None = None
    ticker_qa_summary: dict[str, Any] | None = None
    failed: bool = False
    abort_run: bool = False
    started_at: str = ""
    finished_at: str = ""
    elapsed_seconds: float = 0.0
    error: str | None = None
    error_kind: str | None = None


class Stage1AdaptorProtocol(Protocol):
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
        ...


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--holdings", required=True, nargs="+", type=str)
    ap.add_argument("--tags", nargs="*", default=None, help="Optional explicit tags aligned 1:1 with --holdings")
    ap.add_argument(
        "--allow-tag-inference",
        action="store_true",
        help="Allow tag inference from holdings filenames when --tags is omitted",
    )
    ap.add_argument(
        "--regions",
        nargs="*",
        default=None,
        help=(
            "Optional explicit regions aligned 1:1 with --holdings/tags "
            "(allowed: EM, DM). Recommended for custom holdings not backed by registry metadata."
        ),
    )
    ap.add_argument(
        "--publish-latest-on-partial-failure",
        action="store_true",
        help="Publish output/runs/latest even when one or more tags fail",
    )
    ap.add_argument("--out", default="output", type=str, help="Base output dir (default: output)")
    ap.add_argument("--run-id", default=None, type=str, help="Override auto-generated run_id")
    ap.add_argument("--cache", default="data/_cache", type=str)
    ap.add_argument("--enable-kr-dart", default=0, type=int, help="Kept for compatibility")
    ap.add_argument("--bgn", default="20220101", type=str)
    ap.add_argument("--end", default="", type=str)
    ap.add_argument("--chosen-map", default="data/chosen_ticker_map.csv", type=str)
    ap.add_argument("--progress-every", default=100, type=int)
    ap.add_argument("--max-workers", default=8, type=int)
    ap.add_argument("--isin-search-timeout-sec", default=10.0, type=float)
    ap.add_argument("--isin-quotes-count", default=10, type=int)
    ap.add_argument("--exists-lookback-period", default="5d", type=str)
    ap.add_argument(
        "--chosen-map-overrides",
        default="data/chosen_ticker_overrides.csv",
        type=str,
        help="Manual override file for ticker resolution",
    )
    ap.add_argument(
        "--ticker-resolution-cache",
        default="data/ticker_resolution_cache.csv",
        type=str,
        help="Auto-maintained ticker resolution cache file",
    )
    ap.add_argument(
        "--tag-fail-on-unmatched-failed",
        action="store_true",
        help="Abort the run when a tag-level ticker QA report contains unmatched failed rows",
    )
    ap.add_argument(
        "--tag-single-fail-weight-threshold",
        default=None,
        type=float,
        help="Abort the run when a tag-level max failed weight exceeds this threshold",
    )
    ap.add_argument(
        "--tag-total-fail-weight-threshold",
        default=None,
        type=float,
        help="Abort the run when a tag-level failed weight sum exceeds this threshold",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    add_arguments(ap)
    return ap


def register_parser(subparsers) -> None:
    p = subparsers.add_parser("ingest", help="Stage 1: ingest -> seed artefacts")
    add_arguments(p)
    p.set_defaults(func=main_logic)


def _known_etf_tags() -> set[str]:
    try:
        from providers.ishares_registry import get_registered_etfs

        return {str(x).strip().upper() for x in get_registered_etfs()}
    except Exception:
        return set()


def _tokenise_tag_candidates(path: Path) -> list[str]:
    stem = path.stem.upper()
    tokens: list[str] = []
    current: list[str] = []

    for ch in stem:
        if ch.isalnum():
            current.append(ch)
            continue
        if current:
            tokens.append("".join(current))
            current = []

    if current:
        tokens.append("".join(current))

    return tokens


def _infer_tag(path: Path) -> str:
    tokens = _tokenise_tag_candidates(path)
    known = _known_etf_tags()

    if known:
        hits = [token for token in tokens if token in known]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"Ambiguous tag inference for {path}: hits={hits}")

    generic_noise = {"HOLDINGS", "FULL", "MIN", "CSV", "DATA", "OUTPUT", "INPUT"}
    for token in tokens:
        if token not in generic_noise and not (len(token) == 8 and token.isdigit()):
            return token

    raise ValueError(f"Could not infer tag from holdings path: {path}. Pass --tags explicitly.")


def _resolve_tags(
    holdings_paths: list[Path],
    explicit_tags: Sequence[str] | None,
    *,
    allow_inference: bool = True,
) -> list[str]:
    if explicit_tags is not None:
        tags = [str(tag).strip().upper() for tag in explicit_tags]
        if len(tags) != len(holdings_paths):
            raise ValueError(
                f"--tags length must match --holdings length: tags={len(tags)} holdings={len(holdings_paths)}"
            )
        if len(set(tags)) != len(tags):
            raise ValueError(f"--tags must be unique: {tags}")
        return tags

    if not allow_inference:
        raise ValueError("--tags is required unless --allow-tag-inference is explicitly set.")

    tags = [_infer_tag(path) for path in holdings_paths]
    if len(set(tags)) != len(tags):
        raise ValueError(f"Inferred tags must be unique; pass --tags explicitly. inferred={tags}")
    return tags


def _infer_universe_region(tag: str) -> str | None:
    tag_u = str(tag).strip().upper()

    try:
        from providers.ishares_registry import get_fund_spec

        fund_spec = get_fund_spec(tag_u)
        default_coverage = str(fund_spec.default_coverage).strip().upper()
        if default_coverage in _VALID_REGIONS:
            return default_coverage
    except Exception:
        pass

    return None


def _resolve_regions(tags: Sequence[str], explicit_regions: Sequence[str] | None) -> list[str]:
    if explicit_regions is not None:
        regions = [str(region).strip().upper() for region in explicit_regions]
        if len(regions) != len(tags):
            raise ValueError(
                f"--regions length must match resolved tags length: regions={len(regions)} tags={len(tags)}"
            )

        bad = [region for region in regions if region not in _VALID_REGIONS]
        if bad:
            raise ValueError(f"--regions contains invalid values: {bad}. allowed={sorted(_VALID_REGIONS)}")

        return regions

    inferred_regions: list[str] = []
    missing_tags: list[str] = []

    for tag in tags:
        region = _infer_universe_region(tag)
        if region is None:
            missing_tags.append(tag)
            continue
        inferred_regions.append(region)

    if missing_tags:
        raise ValueError(
            "Could not infer regions for tags "
            f"{missing_tags}. Pass --regions explicitly or register default_coverage for those tags."
        )

    return inferred_regions


def _validate_args(args: argparse.Namespace) -> None:
    validate_args(args)


def _should_publish_latest(
    results: Sequence[Stage1TagResult],
    *,
    publish_on_partial_failure: bool,
) -> bool:
    return should_publish_latest(
        results,
        publish_on_partial_failure=publish_on_partial_failure,
    )


def _build_stage1_summary(results: Sequence[Stage1TagResult]) -> dict[str, Any]:
    return build_stage1_summary(results)


def _write_stage1_aggregate_outputs(
    *,
    artefacts: Artefacts,
    results: Sequence[Stage1TagResult],
    err_cols: Sequence[str] | None = None,
) -> dict[str, pd.DataFrame]:
    return write_stage1_aggregate_outputs(
        artefacts=artefacts,
        results=results,
        default_seed_cols=_DEFAULT_SEED_COLS,
        stage1_errors_required_columns=STAGE1_ERRORS_REQUIRED_COLUMNS,
        stage1_no_dividends_required_columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
        discovered_candidate_required_columns=DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
        input_rejection_columns=_INPUT_REJECTION_COLUMNS,
    )


def _repo_root() -> Path:
    return get_repo_root(start=Path(__file__), fallback_to_cwd=False)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _get_error_columns() -> list[str]:
    return list(STAGE1_ERRORS_REQUIRED_COLUMNS)


def _classify_error_kind(exc: Exception) -> str:
    if isinstance(exc, _TagTickerQAGateError):
        return "materiality_gate"
    if isinstance(exc, ValueError):
        return "validation_error"
    if isinstance(exc, OSError):
        return "filesystem_error"
    return "unexpected_error"


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _write_run_status(
    artefacts: Artefacts,
    *,
    status: str,
    summary: dict[str, Any] | None = None,
    error_kind: str | None = None,
    error_message: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "updated_at": _utc_iso_z(_utc_now()),
    }

    if summary is not None:
        payload["summary"] = summary
    if error_kind:
        payload["error_kind"] = error_kind
    if error_message:
        payload["error_message"] = error_message

    _safe_write_json(artefacts.run_status, payload)


def _relpath_str(path: Path, *, start: Path) -> str:
    return str(path.relative_to(start))


def _build_run_args_payload(
    *,
    holdings_paths: list[Path],
    tags: list[str],
    regions: list[str],
    artefacts: Artefacts,
    cache_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "holdings": [str(p) for p in holdings_paths],
        "tags": tags,
        "regions": regions,
        "out_root": str(artefacts.run_root),
        "cache": str(cache_dir),
        "bgn": args.bgn,
        "end": args.end,
        "chosen_map": args.chosen_map,
        "progress_every": args.progress_every,
        "max_workers": args.max_workers,
        "isin_search_timeout_sec": args.isin_search_timeout_sec,
        "isin_quotes_count": args.isin_quotes_count,
        "exists_lookback_period": args.exists_lookback_period,
        "publish_latest_on_partial_failure": bool(args.publish_latest_on_partial_failure),
        "allow_tag_inference": bool(getattr(args, "allow_tag_inference", False)),
        "tag_fail_on_unmatched_failed": bool(getattr(args, "tag_fail_on_unmatched_failed", False)),
        "tag_single_fail_weight_threshold": getattr(args, "tag_single_fail_weight_threshold", None),
        "tag_total_fail_weight_threshold": getattr(args, "tag_total_fail_weight_threshold", None),
        "layout": {
            "meta_dir": _relpath_str(artefacts.meta_dir, start=artefacts.run_root),
            "stage1_dir": _relpath_str(artefacts.stage1_dir, start=artefacts.run_root),
            "stage2_dir": _relpath_str(artefacts.stage2_dir, start=artefacts.run_root),
            "tag_dirs": f"{_relpath_str(artefacts.stage1_dir, start=artefacts.run_root)}/<TAG>/",
            "run_args": _relpath_str(artefacts.run_args, start=artefacts.run_root),
            "stage1_summary": _relpath_str(artefacts.stage1_summary, start=artefacts.run_root),
            "seed_discovered_candidates_all": str(
                artefacts.seed_discovered_candidates_all.relative_to(artefacts.run_root)
            ),
            "seed_discovered_candidates_tag": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/"
                "seed_yfinance_discovered_candidates_<TAG>.csv"
            ),
            "seed_input_rejections_all": str(
                artefacts.seed_input_rejections_all.relative_to(artefacts.run_root)
            ),
            "seed_input_rejections_tag": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/"
                "seed_input_rejections_<TAG>.csv"
            ),
            "ticker_map_report": f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/{_STAGE1_TICKER_QA_REPORT_PATH}",
            "ticker_failed_queue": f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/{_STAGE1_TICKER_FAILED_QUEUE_PATH}",
            "ticker_anomaly_queue": f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/{_STAGE1_TICKER_ANOMALY_QUEUE_PATH}",
            "ticker_review_queue": f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/{_STAGE1_TICKER_REVIEW_QUEUE_PATH}",
            "tag_ticker_map_report": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/{_TAG_TICKER_QA_REPORT_FILENAME}"
            ),
            "tag_ticker_failed_queue": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/{_TAG_TICKER_FAILED_QUEUE_FILENAME}"
            ),
            "tag_ticker_anomaly_queue": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/{_TAG_TICKER_ANOMALY_QUEUE_FILENAME}"
            ),
            "tag_ticker_review_queue": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/{_TAG_TICKER_REVIEW_QUEUE_FILENAME}"
            ),
            "tag_ticker_qa_summary": (
                f"{artefacts.stage1_dir.relative_to(artefacts.run_root)}/<TAG>/{_TAG_TICKER_QA_SUMMARY_FILENAME}"
            ),
        },
    }


def _resolve_out_root(*, root: Path, out: str, run_id: str | None, tags: list[str], end: str) -> Path:
    runs_dir = (root / out / "runs").resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)

    if run_id:
        rid = run_id
    else:
        tag_blob = "-".join(t.upper() for t in tags) if tags else "UNTAGGED"
        asof = f"asof{end}" if end else "asofNA"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rid = f"divpipe__{tag_blob}__{asof}__{ts}"

    return runs_dir / rid


def _coerce_stage1_numeric_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in _STAGE1_NUMERIC_COLS:
        if col not in out.columns:
            continue

        before_na = int(out[col].isna().sum())
        out[col] = pd.to_numeric(out[col], errors="coerce")
        after_na = int(out[col].isna().sum())

        if after_na > before_na:
            logger.warning(
                "[stage1] numeric coercion introduced NaN: column=%s new_nan=%s rows=%s",
                col,
                after_na - before_na,
                len(out),
            )

    return out


def _split_bad_critical_numeric_rows(
    df_raw: pd.DataFrame,
    df_coerced: pd.DataFrame,
    *,
    context: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_coerced.empty:
        return df_coerced, empty_frame(STAGE1_ERRORS_REQUIRED_COLUMNS)

    bad_mask = pd.Series(False, index=df_coerced.index)

    for col in _STAGE1_CRITICAL_NUMERIC_COLS:
        if col in df_coerced.columns:
            bad_mask = bad_mask | df_coerced[col].isna()

    if not bool(bad_mask.any()):
        return df_coerced, empty_frame(STAGE1_ERRORS_REQUIRED_COLUMNS)

    err_rows: list[dict[str, Any]] = []

    for idx in df_coerced.index[bad_mask]:
        raw_row = df_raw.loc[idx]
        coerced_row = df_coerced.loc[idx]

        bad_cols = [
            col
            for col in _STAGE1_CRITICAL_NUMERIC_COLS
            if col in df_coerced.columns and pd.isna(coerced_row[col])
        ]

        raw_values = {
            col: (None if pd.isna(raw_row[col]) else raw_row[col])
            for col in bad_cols
            if col in df_raw.columns
        }

        err_rows.append(
            {
                "source": raw_row.get("source", ""),
                "underlying": raw_row.get("underlying", ""),
                "underlying_ccy": raw_row.get(
                    "underlying_ccy",
                    raw_row.get("currency", raw_row.get("amount_ccy", "")),
                ),
                "isin": raw_row.get("isin", ""),
                "error": "critical_numeric_contract_violation",
                "candidates": [],
                "candidates_json": "[]",
                "candidate_count": 0,
                "start": "",
                "end": "",
                "source_event_key": raw_row.get("source_event_key", ""),
                "vendor_event_id": raw_row.get("vendor_event_id", ""),
                "yfinance_ticker": raw_row.get("yfinance_ticker", ""),
                "bad_numeric_columns": ",".join(bad_cols),
                "bad_numeric_values_json": json.dumps(raw_values, ensure_ascii=False),
                "context": context,
            }
        )

    good_df = df_coerced.loc[~bad_mask].copy()
    err_df = pd.DataFrame(err_rows)
    err_df = ensure_required_columns(err_df, STAGE1_ERRORS_REQUIRED_COLUMNS)
    err_df = err_df.reindex(
        columns=list(STAGE1_ERRORS_REQUIRED_COLUMNS)
        + [c for c in err_df.columns if c not in STAGE1_ERRORS_REQUIRED_COLUMNS]
    )

    logger.warning(
        "[stage1] dropped bad critical numeric rows: context=%s dropped_rows=%s kept_rows=%s",
        context,
        len(err_df),
        len(good_df),
    )

    return good_df, err_df


def _build_stage1_adaptor() -> Stage1AdaptorProtocol:
    from .adaptors.yfinance_adaptor import YFinanceAdaptor

    return YFinanceAdaptor()


def _enforce_tag_ticker_qa_gate(
    *,
    tag: str,
    qa_summary: dict[str, Any],
    fail_on_unmatched_failed: bool,
    single_fail_weight_threshold: float | None,
    total_fail_weight_threshold: float | None,
) -> None:
    violations: list[str] = []

    unmatched_failed_count = int(qa_summary.get("unmatched_failed_count", 0) or 0)
    max_failed_weight = float(qa_summary.get("max_failed_weight", 0.0) or 0.0)
    failed_weight_sum = float(qa_summary.get("failed_weight_sum", 0.0) or 0.0)

    if fail_on_unmatched_failed and unmatched_failed_count > 0:
        violations.append(f"unmatched_failed_count={unmatched_failed_count}")

    if single_fail_weight_threshold is not None and max_failed_weight > float(single_fail_weight_threshold):
        violations.append(
            "max_failed_weight="
            f"{max_failed_weight:.12f}>threshold={float(single_fail_weight_threshold):.12f}"
        )

    if total_fail_weight_threshold is not None and failed_weight_sum > float(total_fail_weight_threshold):
        violations.append(
            "failed_weight_sum="
            f"{failed_weight_sum:.12f}>threshold={float(total_fail_weight_threshold):.12f}"
        )

    if not violations:
        return

    raise _TagTickerQAGateError(
        f"tag-level ticker QA gate breached for tag={tag}: " + "; ".join(violations)
    )


def _build_tag_ticker_qa_outputs(
    *,
    tag: str,
    stage_dir: Path,
    discovered_candidate_df: pd.DataFrame | None,
    universe_df: pd.DataFrame | None,
) -> dict[str, Any]:
    discovered = discovered_candidate_df if discovered_candidate_df is not None else pd.DataFrame()
    universe = universe_df if universe_df is not None else pd.DataFrame()

    universe_maps = prepare_universe_weight_maps(universe)

    report_df = build_ticker_map_report(
        discovered,
        universe_maps=universe_maps,
        run_materiality_gate=False,
    )
    failed_df = failed_tickers(
        discovered,
        universe_maps=universe_maps,
    )
    anomaly_df = anomaly_tickers(
        discovered,
        universe_maps=universe_maps,
    )
    review_df = build_ticker_resolution_review_queue(
        discovered,
        universe_maps=universe_maps,
    )

    report_path = stage_dir / _TAG_TICKER_QA_REPORT_FILENAME
    failed_path = stage_dir / _TAG_TICKER_FAILED_QUEUE_FILENAME
    anomaly_path = stage_dir / _TAG_TICKER_ANOMALY_QUEUE_FILENAME
    review_path = stage_dir / _TAG_TICKER_REVIEW_QUEUE_FILENAME
    summary_path = stage_dir / _TAG_TICKER_QA_SUMMARY_FILENAME

    write_csv(report_df, report_path)
    write_csv(failed_df, failed_path)
    write_csv(anomaly_df, anomaly_path)
    write_csv(review_df, review_path)

    qa_summary = summarise_ticker_qa(report_df)
    payload = {
        "tag": tag,
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
            "ticker_map_report": report_path.name,
            "ticker_failed_queue": failed_path.name,
            "ticker_anomaly_queue": anomaly_path.name,
            "ticker_review_queue": review_path.name,
        },
    }
    _safe_write_json(summary_path, payload)

    logger.info(
        "[stage1][qa] tag=%s report_rows=%s failed_rows=%s anomaly_rows=%s review_rows=%s failed_weight_sum=%s anomaly_weight_sum=%s unmatched_failed_count=%s",
        tag,
        payload["report_rows"],
        payload["failed_rows"],
        payload["anomaly_rows"],
        payload["review_queue_rows"],
        payload["failed_weight_sum"],
        payload["anomaly_weight_sum"],
        payload["unmatched_failed_count"],
    )

    return payload


def _process_single_tag(
    *,
    holdings_path: Path,
    tag: str,
    universe_region: str,
    artefacts: Artefacts,
    args: argparse.Namespace,
    yfa: Stage1AdaptorProtocol,
    err_cols: Sequence[str],
    repo_root: Path | None = None,
) -> Stage1TagResult:
    started_dt = _utc_now()
    started_perf = perf_counter()
    stage_dir = artefacts.tag_dir(tag)
    stage_dir.mkdir(parents=True, exist_ok=True)

    if repo_root is None:
        repo_root = _repo_root()

    logger.warning(
        "[stage1] start tag=%s region=%s holdings=%s",
        tag,
        universe_region,
        format_display_path(holdings_path, repo_root=repo_root),
    )

    universe_rows = 0
    valid_universe_rows = 0
    valid_universe: pd.DataFrame | None = None
    rejected_input_df: pd.DataFrame | None = None
    seed_df: pd.DataFrame | None = None
    err_df: pd.DataFrame | None = None
    no_div_df: pd.DataFrame | None = None
    discovered_candidate_df: pd.DataFrame | None = None
    tag_ticker_qa_summary: dict[str, Any] | None = None

    try:
        holdings = load_holdings(holdings_path)
        universe = build_universe(holdings)
        universe_rows = len(universe)

        valid_universe, rejected_input_df = split_valid_and_rejected_universe(universe)
        valid_universe_rows = len(valid_universe)

        if len(rejected_input_df):
            rejected_input_df = rejected_input_df.copy()
            rejected_input_df["holdings_tag"] = tag
            rejected_input_df["holdings_file"] = str(holdings_path.name)
        else:
            rejected_input_df = pd.DataFrame(columns=_INPUT_REJECTION_COLUMNS)

        logger.warning(
            "[stage1] universe tag=%s total_rows=%s valid_rows=%s rejected_rows=%s",
            tag,
            universe_rows,
            valid_universe_rows,
            len(rejected_input_df),
        )

        write_csv(valid_universe, artefacts.universe_tag(tag))

        seed_df, err_df, no_div_df, discovered_candidate_df = yfa.fetch_dividends(
            valid_universe,
            start=args.bgn,
            end=args.end,
            sleep_sec=getattr(args, "sleep_sec", 0.0),
            progress_every=getattr(args, "progress_every", 50),
            exists_lookback_period=getattr(args, "exists_lookback_period", "5d"),
            chosen_map_path=str(artefacts.meta_dir / "chosen_ticker_map_effective.csv"),
            return_details=False,
            isin_search_timeout_sec=getattr(args, "isin_search_timeout_sec", 10.0),
            isin_quotes_count=getattr(args, "isin_quotes_count", 10),
            universe_region=universe_region,
            asof_date=getattr(args, "asof_date", None),
            max_workers=getattr(args, "max_workers", 8),
        )

        logger.warning(
            "[stage1] fetched tag=%s seed_rows=%s err_rows=%s no_div_rows=%s discovered_rows=%s",
            tag,
            0 if seed_df is None else len(seed_df),
            0 if err_df is None else len(err_df),
            0 if no_div_df is None else len(no_div_df),
            0 if discovered_candidate_df is None else len(discovered_candidate_df),
        )

        seed_df_raw = seed_df.copy()
        seed_df = _coerce_stage1_numeric_cols(seed_df_raw)
        seed_df, numeric_contract_err_df = _split_bad_critical_numeric_rows(
            seed_df_raw,
            seed_df,
            context=f"tag={tag}",
        )

        if err_df is None or err_df.empty:
            err_df = numeric_contract_err_df
        elif numeric_contract_err_df is not None and not numeric_contract_err_df.empty:
            err_df = pd.concat([err_df, numeric_contract_err_df], ignore_index=True)
        else:
            err_df = err_df.copy()

        err_df = err_df.reindex(
            columns=list(STAGE1_ERRORS_REQUIRED_COLUMNS)
            + [c for c in err_df.columns if c not in STAGE1_ERRORS_REQUIRED_COLUMNS]
        )
        no_div_df = no_div_df.reindex(
            columns=list(STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)
            + [c for c in no_div_df.columns if c not in STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS]
        )
        discovered_candidate_df = discovered_candidate_df.reindex(
            columns=list(DISCOVERED_CANDIDATE_REQUIRED_COLUMNS)
            + [c for c in discovered_candidate_df.columns if c not in DISCOVERED_CANDIDATE_REQUIRED_COLUMNS]
        )

        if not seed_df.empty:
            seed_df["holdings_tag"] = tag
            seed_df["holdings_file"] = str(holdings_path.name)

        if not err_df.empty:
            err_df["holdings_tag"] = tag
            err_df["holdings_file"] = str(holdings_path.name)

        if not no_div_df.empty:
            no_div_df["holdings_tag"] = tag
            no_div_df["holdings_file"] = str(holdings_path.name)

        if not discovered_candidate_df.empty:
            discovered_candidate_df["holdings_tag"] = tag
            discovered_candidate_df["holdings_file"] = str(holdings_path.name)

        write_csv_or_empty(seed_df, artefacts.seed_dividends_tag(tag), columns=_DEFAULT_SEED_COLS)
        write_err_csv(err_df, artefacts.seed_errors_tag(tag), err_cols=err_cols)
        write_csv_or_empty(
            no_div_df,
            artefacts.seed_no_dividends_tag(tag),
            columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
        )
        write_csv_or_empty(
            discovered_candidate_df,
            artefacts.seed_discovered_candidates_tag(tag),
            columns=DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
        )
        write_csv_or_empty(
            rejected_input_df,
            artefacts.seed_input_rejections_tag(tag),
            columns=_INPUT_REJECTION_COLUMNS,
        )

        tag_ticker_qa_summary = _build_tag_ticker_qa_outputs(
            tag=tag,
            stage_dir=stage_dir,
            discovered_candidate_df=discovered_candidate_df,
            universe_df=valid_universe,
        )

        _enforce_tag_ticker_qa_gate(
            tag=tag,
            qa_summary=tag_ticker_qa_summary,
            fail_on_unmatched_failed=bool(getattr(args, "tag_fail_on_unmatched_failed", False)),
            single_fail_weight_threshold=getattr(args, "tag_single_fail_weight_threshold", None),
            total_fail_weight_threshold=getattr(args, "tag_total_fail_weight_threshold", None),
        )

        finished_dt = _utc_now()
        elapsed = round(perf_counter() - started_perf, 6)

        logger.warning(
            "[stage1] done tag=%s elapsed_seconds=%s seed_rows=%s err_rows=%s no_div_rows=%s discovered_rows=%s rejected_rows=%s",
            tag,
            elapsed,
            len(seed_df),
            len(err_df),
            len(no_div_df),
            len(discovered_candidate_df),
            len(rejected_input_df),
        )

        return Stage1TagResult(
            tag=tag,
            holdings_path=holdings_path,
            universe_region=universe_region,
            stage_dir=stage_dir,
            universe_rows=universe_rows,
            valid_universe_rows=valid_universe_rows,
            universe_df=valid_universe.copy(),
            input_rejection_df=rejected_input_df,
            seed_df=seed_df,
            err_df=err_df,
            no_div_df=no_div_df,
            discovered_candidate_df=discovered_candidate_df,
            ticker_qa_summary=tag_ticker_qa_summary,
            failed=False,
            abort_run=False,
            started_at=_utc_iso_z(started_dt),
            finished_at=_utc_iso_z(finished_dt),
            elapsed_seconds=elapsed,
            error=None,
            error_kind=None,
        )

    except _TagTickerQAGateError as exc:
        finished_dt = _utc_now()
        elapsed = round(perf_counter() - started_perf, 6)

        logger.error(
            "[stage1][qa-gate] tag=%s elapsed_seconds=%s error=%s",
            tag,
            elapsed,
            exc,
        )

        return Stage1TagResult(
            tag=tag,
            holdings_path=holdings_path,
            universe_region=universe_region,
            stage_dir=stage_dir,
            universe_rows=universe_rows,
            valid_universe_rows=valid_universe_rows,
            universe_df=None if valid_universe is None else valid_universe.copy(),
            input_rejection_df=rejected_input_df,
            seed_df=seed_df,
            err_df=err_df,
            no_div_df=no_div_df,
            discovered_candidate_df=discovered_candidate_df,
            ticker_qa_summary=tag_ticker_qa_summary,
            failed=True,
            abort_run=True,
            started_at=_utc_iso_z(started_dt),
            finished_at=_utc_iso_z(finished_dt),
            elapsed_seconds=elapsed,
            error=str(exc),
            error_kind=_classify_error_kind(exc),
        )

    except Exception as exc:
        logger.exception("[stage1] failed tag=%s error=%s", tag, exc)

        write_csv_or_empty(None, artefacts.seed_dividends_tag(tag), columns=_DEFAULT_SEED_COLS)
        write_err_csv(None, artefacts.seed_errors_tag(tag), err_cols=err_cols)
        write_csv_or_empty(
            None,
            artefacts.seed_no_dividends_tag(tag),
            columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
        )
        write_csv_or_empty(
            None,
            artefacts.seed_discovered_candidates_tag(tag),
            columns=DISCOVERED_CANDIDATE_REQUIRED_COLUMNS,
        )
        write_csv_or_empty(
            None,
            artefacts.seed_input_rejections_tag(tag),
            columns=_INPUT_REJECTION_COLUMNS,
        )

        finished_dt = _utc_now()
        elapsed = round(perf_counter() - started_perf, 6)

        logger.warning(
            "[stage1] failed-summary tag=%s elapsed_seconds=%s error_kind=%s",
            tag,
            elapsed,
            _classify_error_kind(exc),
        )

        return Stage1TagResult(
            tag=tag,
            holdings_path=holdings_path,
            universe_region=universe_region,
            stage_dir=stage_dir,
            universe_rows=0,
            valid_universe_rows=0,
            universe_df=None,
            input_rejection_df=None,
            seed_df=None,
            err_df=None,
            no_div_df=None,
            discovered_candidate_df=None,
            ticker_qa_summary=None,
            failed=True,
            abort_run=False,
            started_at=_utc_iso_z(started_dt),
            finished_at=_utc_iso_z(finished_dt),
            elapsed_seconds=elapsed,
            error=str(exc),
            error_kind=_classify_error_kind(exc),
        )


def main_logic(args: argparse.Namespace) -> None:
    _validate_args(args)

    holdings_paths = [Path(hp).expanduser().resolve() for hp in args.holdings]
    tags = _resolve_tags(
        holdings_paths,
        args.tags,
        allow_inference=bool(getattr(args, "allow_tag_inference", False)),
    )
    regions = _resolve_regions(tags, args.regions)

    root = _repo_root()
    out_root = _resolve_out_root(root=root, out=args.out, run_id=args.run_id, tags=tags, end=args.end)

    run_paths = RunPaths(out_root)
    run_paths.ensure()
    artefacts = Artefacts(run_paths)

    cache_dir = Path(args.cache).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    err_cols = _get_error_columns()
    yfa = _build_stage1_adaptor()
    results: list[Stage1TagResult] = []

    _safe_write_json(
        artefacts.run_args,
        _build_run_args_payload(
            holdings_paths=holdings_paths,
            tags=tags,
            regions=regions,
            artefacts=artefacts,
            cache_dir=cache_dir,
            args=args,
        ),
    )
    _write_run_status(artefacts, status="running")

    effective_chosen_map_path = artefacts.meta_dir / "chosen_ticker_map_effective.csv"

    write_effective_chosen_map(
        override_path=Path(args.chosen_map_overrides).expanduser().resolve(),
        cache_path=Path(args.ticker_resolution_cache).expanduser().resolve(),
        out_path=effective_chosen_map_path,
    )

    logger.info("[divpipe] out_root=%s", format_display_path(out_root, repo_root=root))

    try:
        for holdings_path, tag, universe_region in zip(holdings_paths, tags, regions):
            result = _process_single_tag(
                holdings_path=holdings_path,
                tag=tag,
                universe_region=universe_region,
                artefacts=artefacts,
                args=args,
                yfa=yfa,
                err_cols=err_cols,
                repo_root=root,
            )
            results.append(result)

            if result.abort_run:
                raise _TagTickerQAGateError(result.error or f"tag-level ticker QA gate breached for tag={tag}")

        aggregate_outputs = _write_stage1_aggregate_outputs(
            artefacts=artefacts,
            results=results,
        )

        universe_all = concat_or_empty(
            [result.universe_df for result in results],
            default_columns=["underlying", "underlying_ccy", "isin", "weight"],
            numeric_cols=["weight"],
        )

        stage1_summary = _build_stage1_summary(results)

        # Real lazy drop: per-tag heavy frames are no longer needed once aggregate outputs exist.
        drop_heavy_stage1_frames(results)

        bucket_counts = write_no_div_bucket_files(
            no_div_all_path=artefacts.seed_no_dividends_all,
            stage1_dir=artefacts.stage1_dir,
            default_columns=STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS,
        )

        # Keep only the aggregate discovered-candidate frame needed downstream.
        discovered_candidate_all = aggregate_outputs["discovered_candidate_all"]
        aggregate_outputs.clear()

        upsert_resolution_cache(
            cache_path=Path(args.ticker_resolution_cache).expanduser().resolve(),
            discovered_candidate_df=discovered_candidate_all,
            asof_date=args.end or _utc_now().strftime("%Y%m%d"),
            run_id=out_root.name,
            accepted_statuses=("div_found",),
        )

        universe_maps = prepare_universe_weight_maps(universe_all)

        # Real lazy drop: universe_all has now been reduced into the smaller weight map surface.
        del universe_all

        ticker_map_report_df = build_ticker_map_report(
            discovered_candidate_all,
            universe_maps=universe_maps,
            run_materiality_gate=False,
        )
        ticker_failed_df = failed_tickers(
            discovered_candidate_all,
            universe_maps=universe_maps,
        )
        ticker_anomaly_df = anomaly_tickers(
            discovered_candidate_all,
            universe_maps=universe_maps,
        )
        review_df = build_ticker_resolution_review_queue(
            discovered_candidate_all,
            universe_maps=universe_maps,
        )

        # Real lazy drop: downstream now works off derived QA surfaces, not the heavy inputs.
        del discovered_candidate_all
        del universe_maps

        write_csv(ticker_map_report_df, artefacts.stage1_dir / _STAGE1_TICKER_QA_REPORT_PATH)
        write_csv(ticker_failed_df, artefacts.stage1_dir / _STAGE1_TICKER_FAILED_QUEUE_PATH)
        write_csv(ticker_anomaly_df, artefacts.stage1_dir / _STAGE1_TICKER_ANOMALY_QUEUE_PATH)
        write_csv(review_df, artefacts.stage1_dir / _STAGE1_TICKER_REVIEW_QUEUE_PATH)

        publish_latest = _should_publish_latest(
            results,
            publish_on_partial_failure=bool(args.publish_latest_on_partial_failure),
        )

        latest_symlink_updated = False
        latest_txt_written = False

        if publish_latest:
            latest_result = update_latest_symlink(out_root)

            if isinstance(latest_result, tuple) and len(latest_result) == 2:
                latest_symlink_updated = bool(latest_result[0])
                latest_txt_written = bool(latest_result[1])
            else:
                latest_symlink_updated = bool(latest_result) if latest_result is not None else False
                latest_txt_written = False
        else:
            logger.warning(
                "[divpipe] latest pointer not updated because run had partial failures; "
                "default policy is to publish latest only for fully successful runs. "
                "Use --publish-latest-on-partial-failure to override."
            )

        final_summary = augment_stage1_summary_with_ticker_qa(
            stage1_summary,
            report_df=ticker_map_report_df,
            failed_df=ticker_failed_df,
            anomaly_df=ticker_anomaly_df,
            review_df=review_df,
            latest_symlink_updated=latest_symlink_updated,
            latest_txt_written=latest_txt_written,
            ticker_map_report_path=_STAGE1_TICKER_QA_REPORT_PATH,
            ticker_failed_queue_path=_STAGE1_TICKER_FAILED_QUEUE_PATH,
            ticker_anomaly_queue_path=_STAGE1_TICKER_ANOMALY_QUEUE_PATH,
            ticker_review_queue_path=_STAGE1_TICKER_REVIEW_QUEUE_PATH,
        )

        _safe_write_json(artefacts.stage1_summary, final_summary)

        _write_run_status(
            artefacts,
            status=derive_run_status(final_summary),
            summary=final_summary,
        )

        latest = out_root.resolve().parent / "latest"
        logger.info("[divpipe] done")
        logger.info("[divpipe] run_root=%s", format_display_path(out_root, repo_root=root))
        logger.info("[divpipe] latest=%s", format_display_path(latest, repo_root=root))
        logger.info(
            "[divpipe] summary: tags=%s seed_rows=%s error_rows=%s no_div_rows=%s input_rejection_rows=%s failed_tags=%s total_elapsed_seconds=%s",
            final_summary["tag_count"],
            final_summary["seed_rows"],
            final_summary["error_rows"],
            final_summary["no_div_rows"],
            final_summary["input_rejection_rows"],
            final_summary["failed_tag_count"],
            final_summary["timing"]["total_elapsed_seconds"],
        )
        logger.info(
            "[divpipe] ticker_qa: report_rows=%s failed_rows=%s anomaly_rows=%s review_rows=%s failed_weight_sum=%s anomaly_weight_sum=%s unmatched_failed_count=%s",
            final_summary["ticker_qa"]["report_rows"],
            final_summary["ticker_qa"]["failed_rows"],
            final_summary["ticker_qa"]["anomaly_rows"],
            final_summary["ticker_qa"]["review_queue_rows"],
            final_summary["ticker_qa"]["failed_weight_sum"],
            final_summary["ticker_qa"]["anomaly_weight_sum"],
            final_summary["ticker_qa"]["unmatched_failed_count"],
        )
        logger.info(
            "[divpipe] latest_pointer: symlink_updated=%s latest_txt_written=%s fallback_used=%s",
            final_summary["latest_pointer"]["latest_symlink_updated"],
            final_summary["latest_pointer"]["latest_txt_written"],
            final_summary["latest_pointer"]["fallback_used"],
        )
        logger.info(
            "[divpipe] no_div buckets: unsupported=%s kr=%s rest=%s suspect=%s",
            bucket_counts["unsupported"],
            bucket_counts["kr"],
            bucket_counts["rest"],
            bucket_counts["rest_suspect"],
        )

    except Exception as exc:
        _write_run_status(
            artefacts,
            status="failed",
            error_kind=_classify_error_kind(exc),
            error_message=str(exc),
        )
        raise


def main(argv: Sequence[str] | None = None) -> None:
    ap = build_parser()
    args = ap.parse_args(list(argv) if argv is not None else None)
    main_logic(args)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    logging.getLogger("curl_cffi").setLevel(logging.CRITICAL)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)
    main()