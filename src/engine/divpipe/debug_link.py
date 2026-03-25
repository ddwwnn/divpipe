# src/engine/divpipe/debug_link.py
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

import pandas as pd

from .pipeline.link_events import assign_economic_events

logger = logging.getLogger(__name__)


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--in", dest="in_path", required=True, help="Input CSV path")
    ap.add_argument("--out", dest="out_path", default="", help="Optional output CSV path")
    ap.add_argument("--shuffle-seed", type=int, default=7, help="Random seed for shuffle invariance check")
    ap.add_argument(
        "--respect-existing-econ-id",
        action="store_true",
        help="Respect existing economic_event_id values during linking",
    )
    ap.add_argument(
        "--fail-on-conflict",
        action="store_true",
        help="Exit non-zero if any vendor_event_id maps to multiple economic_event_id values",
    )
    ap.add_argument(
        "--fail-on-shuffle-diff",
        action="store_true",
        help="Exit non-zero if shuffle invariance check fails",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="divpipe debug-link",
        description="Debug assign_economic_events determinism and vendor_event_id consistency",
    )
    add_arguments(ap)
    return ap


def register_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "debug-link",
        help="Debug assign_economic_events determinism and vendor_event_id consistency",
    )
    add_arguments(p)
    p.set_defaults(func=main_logic)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = build_parser()
    return ap.parse_args(list(argv) if argv is not None else None)


def _load_input(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    logger.info("Loaded input: %s rows=%s cols=%s", path, len(df), len(df.columns))

    if "amount" in df.columns:
        logger.info("Input amount dtype=%s", df["amount"].dtype)
    else:
        logger.info("Input missing amount column")

    return df


def _write_output(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("Wrote linked output: %s rows=%s", path, len(df))


def _count_vendor_event_conflicts(df: pd.DataFrame) -> int:
    if "vendor_event_id" not in df.columns or "economic_event_id" not in df.columns:
        return 0

    bad = df.groupby("vendor_event_id")["economic_event_id"].nunique(dropna=True) > 1
    return int(bad.sum())


def _log_vendor_event_conflicts(df: pd.DataFrame, max_rows: int = 50) -> int:
    if "vendor_event_id" not in df.columns or "economic_event_id" not in df.columns:
        logger.info("Conflict check skipped: vendor_event_id/economic_event_id column missing")
        return 0

    bad = df.groupby("vendor_event_id")["economic_event_id"].nunique(dropna=True) > 1
    bad_count = int(bad.sum())

    logger.info("vendor_event_id -> multiple economic_event_id count=%s", bad_count)

    if bad_count > 0:
        vids = list(bad[bad].index[:10])
        cols = [c for c in ["vendor_event_id", "underlying", "div_ccy", "ex_date", "amount", "economic_event_id"] if c in df.columns]
        sample = df[df["vendor_event_id"].isin(vids)][cols].head(max_rows)
        logger.warning("Conflict sample:\n%s", sample.to_string(index=False))

    return bad_count


def _compute_shuffle_diff(
    df: pd.DataFrame,
    *,
    shuffle_seed: int,
    respect_existing: bool,
) -> int:
    a = assign_economic_events(df.copy(), respect_existing=respect_existing)
    b = assign_economic_events(
        df.sample(frac=1.0, random_state=shuffle_seed).reset_index(drop=True),
        respect_existing=respect_existing,
    )

    if "vendor_event_id" not in a.columns or "economic_event_id" not in a.columns:
        return 0
    if "vendor_event_id" not in b.columns or "economic_event_id" not in b.columns:
        return 0

    sa = set(map(tuple, a[["vendor_event_id", "economic_event_id"]].fillna("").values))
    sb = set(map(tuple, b[["vendor_event_id", "economic_event_id"]].fillna("").values))
    return len(sa.symmetric_difference(sb))


def _log_shuffle_diff(
    df: pd.DataFrame,
    *,
    shuffle_seed: int,
    respect_existing: bool,
) -> int:
    set_diff = _compute_shuffle_diff(
        df,
        shuffle_seed=shuffle_seed,
        respect_existing=respect_existing,
    )
    logger.info(
        "shuffle invariance: seed=%s set_diff=%s respect_existing=%s",
        shuffle_seed,
        set_diff,
        respect_existing,
    )
    return set_diff


def _log_summary_views(df: pd.DataFrame) -> None:
    if "economic_event_id" not in df.columns:
        logger.info("Summary views skipped: economic_event_id missing")
        return

    if "amount" in df.columns:
        top_amount = (
            df.groupby("economic_event_id")["amount"]
            .nunique(dropna=True)
            .sort_values(ascending=False)
            .head(20)
        )
        logger.info("Top economic_event_id by amount_nunique:\n%s", top_amount.to_string())

    top_count = df["economic_event_id"].value_counts().head(20)
    logger.info("Top economic_event_id by row_count:\n%s", top_count.to_string())


def main_logic(args: argparse.Namespace) -> None:
    in_path = Path(args.in_path).expanduser().resolve()
    out_path = (
        Path(args.out_path).expanduser().resolve()
        if args.out_path
        else in_path.with_name(in_path.stem + "__linked.csv")
    )

    respect_existing = bool(args.respect_existing_econ_id)

    logger.info(
        "debug-link start: in=%s out=%s respect_existing=%s",
        in_path,
        out_path,
        respect_existing,
    )

    df = _load_input(in_path)
    out = assign_economic_events(df.copy(), respect_existing=respect_existing)
    _write_output(out, out_path)

    bad_count = _log_vendor_event_conflicts(out)
    shuffle_diff = _log_shuffle_diff(
        df,
        shuffle_seed=int(args.shuffle_seed),
        respect_existing=respect_existing,
    )
    _log_summary_views(out)

    if args.fail_on_conflict and bad_count > 0:
        raise SystemExit(2)

    if args.fail_on_shuffle_diff and shuffle_diff > 0:
        raise SystemExit(3)

    logger.info("debug-link done")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    main_logic(args)


if __name__ == "__main__":
    main()