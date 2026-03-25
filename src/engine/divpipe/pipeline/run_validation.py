# src/engine/divpipe/pipeline/run_validation.py

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any


def validate_yyyymmdd(value: str, *, field_name: str, allow_blank: bool = False) -> None:
    text = str(value).strip()
    if allow_blank and text == "":
        return

    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"{field_name} must be in YYYYMMDD format: got {value!r}")

    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid YYYYMMDD date: got {value!r}") from exc


def validate_positive_int(value: Any, *, field_name: str, minimum: int = 1) -> None:
    try:
        n = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an integer: got {value!r}") from exc

    if n < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}: got {value!r}")


def validate_positive_float(value: Any, *, field_name: str, strictly_positive: bool = False) -> None:
    try:
        x = float(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a number: got {value!r}") from exc

    if strictly_positive:
        if x <= 0:
            raise ValueError(f"{field_name} must be > 0: got {value!r}")
    else:
        if x < 0:
            raise ValueError(f"{field_name} must be >= 0: got {value!r}")


def validate_input_paths(args: argparse.Namespace) -> None:
    holdings_values = getattr(args, "holdings", None) or []
    if not holdings_values:
        raise ValueError("--holdings must contain at least one file")

    missing_holdings: list[str] = []
    bad_holdings: list[str] = []

    for raw in holdings_values:
        p = Path(str(raw)).expanduser()
        if not p.exists():
            missing_holdings.append(str(p))
            continue
        if not p.is_file():
            bad_holdings.append(str(p))

    if missing_holdings:
        raise ValueError(f"--holdings contains missing files: {missing_holdings}")
    if bad_holdings:
        raise ValueError(f"--holdings must point to files, not directories: {bad_holdings}")

    chosen_map = str(getattr(args, "chosen_map", "") or "").strip()
    if chosen_map:
        chosen_map_path = Path(chosen_map).expanduser().resolve()
        if not chosen_map_path.exists():
            raise ValueError(f"--chosen-map does not exist: {chosen_map_path}")
        if not chosen_map_path.is_file():
            raise ValueError(f"--chosen-map must point to a file: {chosen_map_path}")


def validate_runtime_args(args: argparse.Namespace) -> None:
    validate_positive_int(getattr(args, "max_workers", 1), field_name="--max-workers", minimum=1)
    validate_positive_int(getattr(args, "progress_every", 1), field_name="--progress-every", minimum=1)
    validate_positive_int(getattr(args, "isin_quotes_count", 1), field_name="--isin-quotes-count", minimum=1)
    validate_positive_float(
        getattr(args, "isin_search_timeout_sec", 0.0),
        field_name="--isin-search-timeout-sec",
        strictly_positive=True,
    )

    if getattr(args, "tag_single_fail_weight_threshold", None) is not None:
        validate_positive_float(
            getattr(args, "tag_single_fail_weight_threshold"),
            field_name="--tag-single-fail-weight-threshold",
            strictly_positive=False,
        )

    if getattr(args, "tag_total_fail_weight_threshold", None) is not None:
        validate_positive_float(
            getattr(args, "tag_total_fail_weight_threshold"),
            field_name="--tag-total-fail-weight-threshold",
            strictly_positive=False,
        )


def validate_args(args: argparse.Namespace) -> None:
    validate_yyyymmdd(args.bgn, field_name="--bgn")
    validate_yyyymmdd(args.end, field_name="--end", allow_blank=True)
    validate_input_paths(args)
    validate_runtime_args(args)