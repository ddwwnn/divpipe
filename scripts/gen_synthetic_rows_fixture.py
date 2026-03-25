# scripts/gen_synthetic_rows_fixture.py
from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
from typing import Sequence

import pandas as pd

logger = logging.getLogger(__name__)

NO_DIV_COLUMNS = [
    "source",
    "underlying",
    "underlying_ccy",
    "isin",
    "error",
    "candidates",
    "start",
    "end",
]

VALID_CASE_TAGS = {
    "O1A",
    "O1B",
    "O2",
    "O3A",
    "O3B",
    "O3C",
    "O3D",
    "O4",
    "O5",
    "O6",
    "OK",
}


def _econ_id(underlying: str, ex_date: str, *, salt: str = "demo_v1") -> str:
    """
    Deterministic economic_event_id for demo/replay.
    """
    key = f"{salt}|{underlying}|{ex_date}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"eco_demo_{h}"


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--run-root", default="output/runs/demo__override_fixture", type=str)
    ap.add_argument("--out-name", default="seed_yfinance_dividends_all.csv", type=str)
    ap.add_argument("--write-root-copy", action="store_true")
    ap.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for standalone execution.",
    )
    ap.add_argument(
        "--case-tags",
        nargs="+",
        default=[],
        help="Optional subset of case tags to emit, e.g. --case-tags O1A O3B O5",
    )

    o4_group = ap.add_mutually_exclusive_group()
    o4_group.add_argument(
        "--include-o4",
        action="store_true",
        help="Include the O4 integrity-violation case.",
    )
    o4_group.add_argument(
        "--exclude-o4",
        action="store_true",
        help="Explicitly exclude O4, even if O4 is requested via --case-tags.",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python scripts/gen_synthetic_rows_fixture.py")
    add_arguments(ap)
    return ap


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = build_parser()
    return ap.parse_args(list(argv) if argv is not None else None)


def _configure_logging(log_level: str) -> None:
    level = getattr(logging, str(log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

def _resolve_include_o4(
    *,
    include_o4_flag: bool,
    exclude_o4_flag: bool,
    case_tags: Sequence[str],
) -> bool:
    tags = {str(x).strip().upper() for x in case_tags if str(x).strip()}

    if exclude_o4_flag:
        if "O4" in tags:
            logger.warning("O4 requested via --case-tags but --exclude-o4 was set; O4 will be excluded.")
        return False

    if include_o4_flag:
        return True

    if "O4" in tags:
        logger.info("O4 requested via --case-tags; auto-enabling include_o4.")
        return True

    return False

def _normalise_case_tags(case_tags: Sequence[str]) -> list[str]:
    tags = [str(x).strip().upper() for x in case_tags if str(x).strip()]
    bad = [x for x in tags if x not in VALID_CASE_TAGS]
    if bad:
        raise ValueError(
            f"Unknown case_tags={bad}. Valid tags={sorted(VALID_CASE_TAGS)}"
        )
    return tags


def _filter_rows_by_case_tags(df: pd.DataFrame, case_tags: Sequence[str]) -> pd.DataFrame:
    if not case_tags:
        return df

    out = df[df["case_tag"].astype("string").str.upper().isin(case_tags)].copy()
    logger.info("Applied case_tag filter: tags=%s rows=%s", list(case_tags), len(out))
    return out


def _build_o1_rows() -> list[dict]:
    return [
        {
            "case_tag": "O1A",
            "source": "yfinance",
            "vendor_event_id": "O1A_VEND_001",
            "underlying": "ABC",
            "ex_date": "2025-06-10",
            "pay_date": "2025-06-20",
            "amount": 0.10,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O1A",
            "source": "yfinance",
            "vendor_event_id": "O1A_VEND_002",
            "underlying": "ABC",
            "ex_date": "2025-06-10",
            "pay_date": "2025-07-20",
            "amount": 0.10,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O1B",
            "source": "yfinance",
            "vendor_event_id": "O1B_VEND_001",
            "underlying": "ABD",
            "ex_date": "2025-06-10",
            "pay_date": "2025-06-20",
            "amount": 0.06,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O1B",
            "source": "yfinance",
            "vendor_event_id": "O1B_VEND_002",
            "underlying": "ABD",
            "ex_date": "2025-06-10",
            "pay_date": "2025-07-20",
            "amount": 0.04,
            "div_ccy": "USD",
        },
    ]


def _build_o2_rows() -> list[dict]:
    return [
        {
            "case_tag": "O2",
            "source": "yfinance",
            "vendor_event_id": "O2_VEND_001",
            "underlying": "DEF",
            "ex_date": "2025-08-01",
            "pay_date": "2025-08-10",
            "amount": 0.10,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O2",
            "source": "yfinance",
            "vendor_event_id": "O2_VEND_002",
            "underlying": "DEF",
            "ex_date": "2025-08-01",
            "pay_date": "2025-08-10",
            "amount": 0.12,
            "div_ccy": "USD",
        },
    ]


def _build_o3_rows() -> list[dict]:
    return [
        {
            "case_tag": "O3A",
            "source": "yfinance",
            "vendor_event_id": "O3A_VEND_001",
            "underlying": "GHI",
            "ex_date": "2025-09-01",
            "pay_date": "2025-09-15",
            "amount": 0.50,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O3A",
            "source": "yfinance",
            "vendor_event_id": "O3A_VEND_002",
            "underlying": "GHI",
            "ex_date": "2025-09-03",
            "pay_date": "2025-09-15",
            "amount": 0.50,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O3B",
            "source": "yfinance",
            "vendor_event_id": "O3B_VEND_001",
            "underlying": "GHJ",
            "ex_date": "2025-09-01",
            "pay_date": "2025-09-15",
            "amount": 0.50,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O3B",
            "source": "yfinance",
            "vendor_event_id": "O3B_VEND_002",
            "underlying": "GHJ",
            "ex_date": "2025-09-02",
            "pay_date": "2025-09-16",
            "amount": 0.50,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O3C",
            "source": "yfinance",
            "vendor_event_id": "O3C_VEND_001",
            "underlying": "GHK",
            "ex_date": "2025-09-01",
            "pay_date": "2025-09-15",
            "amount": 0.10,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O3C",
            "source": "yfinance",
            "vendor_event_id": "O3C_VEND_002",
            "underlying": "GHK",
            "ex_date": "2025-09-03",
            "pay_date": "2025-09-15",
            "amount": 0.11,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O3D",
            "source": "yfinance",
            "vendor_event_id": "O3D_VEND_001",
            "underlying": "GHL",
            "ex_date": "2025-09-01",
            "pay_date": "2025-09-15",
            "amount": 0.10,
            "div_ccy": "USD",
            "status": "expected",
        },
        {
            "case_tag": "O3D",
            "source": "yfinance",
            "vendor_event_id": "O3D_VEND_002",
            "underlying": "GHL",
            "ex_date": "2025-09-04",
            "pay_date": "2025-09-15",
            "amount": 0.10,
            "div_ccy": "USD",
            "status": "declared",
        },
    ]


def _build_o4_rows() -> list[dict]:
    return [
        {
            "case_tag": "O4",
            "source": "yfinance",
            "vendor_event_id": "O4_BAD_VID_001",
            "underlying": "AAA",
            "ex_date": "2025-10-01",
            "pay_date": "2025-10-10",
            "amount": 0.30,
            "div_ccy": "USD",
            "isin": "US000000AAA1",
        },
        {
            "case_tag": "O4",
            "source": "yfinance",
            "vendor_event_id": "O4_BAD_VID_001",
            "underlying": "BBB",
            "ex_date": "2025-10-01",
            "pay_date": "2025-10-10",
            "amount": 0.30,
            "div_ccy": "USD",
            "isin": "US000000BBB2",
        },
    ]


def _build_o5_rows() -> list[dict]:
    return [
        {
            "case_tag": "O5",
            "source": "yfinance",
            "vendor_event_id": "O5_VEND_001",
            "underlying": "JKL",
            "ex_date": "2025-11-01",
            "pay_date": "2025-11-20",
            "amount": 1.00,
            "div_ccy": "USD",
        },
        {
            "case_tag": "O5",
            "source": "yfinance",
            "vendor_event_id": "O5_VEND_002",
            "underlying": "JKL",
            "ex_date": "2025-11-01",
            "pay_date": "2025-11-20",
            "amount": 5.00,
            "div_ccy": "BRL",
        },
    ]


def _build_o6_rows() -> list[dict]:
    return [
        {
            "case_tag": "O6",
            "source": "yfinance",
            "vendor_event_id": "O6_VEND_001",
            "underlying": "MNO",
            "ex_date": "2025-12-01",
            "pay_date": "2025-12-15",
            "amount": 0.25,
            "div_ccy": "USD",
            "action_type": "DIV",
            "share_class": "COMMON",
        },
        {
            "case_tag": "O6",
            "source": "yfinance",
            "vendor_event_id": "O6_VEND_002",
            "underlying": "MNO",
            "ex_date": "2025-12-01",
            "pay_date": "2025-12-15",
            "amount": 0.25,
            "div_ccy": "USD",
            "action_type": "JCP",
            "share_class": "COMMON",
        },
        {
            "case_tag": "O6",
            "source": "yfinance",
            "vendor_event_id": "O6_VEND_003",
            "underlying": "MNO",
            "ex_date": "2025-12-01",
            "pay_date": "2025-12-15",
            "amount": 0.25,
            "div_ccy": "USD",
            "action_type": "DIV",
            "share_class": "PREF",
        },
    ]


def _build_ok_rows() -> list[dict]:
    return [
        {
            "case_tag": "OK",
            "source": "yfinance",
            "vendor_event_id": "OK_VEND_001",
            "underlying": "XYZ",
            "ex_date": "2025-07-01",
            "pay_date": "2025-07-10",
            "amount": 0.50,
            "div_ccy": "USD",
        },
    ]


def _ensure_optional_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in [
        "isin",
        "underlying_ccy",
        "status",
        "anchor_date",
        "declared_date",
        "holdings_tag",
        "holdings_file",
        "action_type",
        "share_class",
        "yfinance_ticker",
    ]:
        if col not in out.columns:
            out[col] = ""
    return out


def build_fixture_rows(*, include_o4: bool = False, case_tags: Sequence[str] | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    rows.extend(_build_o1_rows())
    rows.extend(_build_o2_rows())
    rows.extend(_build_o3_rows())
    if include_o4:
        rows.extend(_build_o4_rows())
    rows.extend(_build_o5_rows())
    rows.extend(_build_o6_rows())
    rows.extend(_build_ok_rows())

    df = pd.DataFrame(rows)
    df = _filter_rows_by_case_tags(df, case_tags or [])

    if df.empty:
        raise ValueError("No fixture rows selected. Check --case-tags and O4 options.")

    df["economic_event_id"] = [
        _econ_id(u, d) for u, d in zip(df["underlying"].astype(str), df["ex_date"].astype(str))
    ]
    df["econ_key"] = df["underlying"].astype(str) + "|" + df["ex_date"].astype(str)

    df = _ensure_optional_columns(df)
    return df


def _write_fixture_files(
    *,
    df: pd.DataFrame,
    run_root: Path,
    out_name: str,
    write_root_copy: bool,
) -> tuple[Path, Path, Path | None]:
    stage1 = run_root / "stage1_seed"
    stage1.mkdir(parents=True, exist_ok=True)

    out_stage1 = stage1 / out_name
    df.to_csv(out_stage1, index=False, encoding="utf-8-sig")

    no_div_stage1 = stage1 / "seed_yfinance_no_dividends_all.csv"
    pd.DataFrame(columns=NO_DIV_COLUMNS).to_csv(no_div_stage1, index=False, encoding="utf-8-sig")

    out_root_copy: Path | None = None
    if write_root_copy:
        run_root.mkdir(parents=True, exist_ok=True)
        out_root_copy = run_root / out_name
        df.to_csv(out_root_copy, index=False, encoding="utf-8-sig")

    return out_stage1, no_div_stage1, out_root_copy


def _log_fixture_summary(
    *,
    df: pd.DataFrame,
    include_o4: bool,
    case_tags: Sequence[str],
    out_stage1: Path,
    no_div_stage1: Path,
    out_root_copy: Path | None,
    run_root: Path,
) -> None:
    logger.info("wrote fixture rows: %s", out_stage1)
    logger.info("wrote empty no-div file: %s", no_div_stage1)
    if out_root_copy is not None:
        logger.info("wrote root copy: %s", out_root_copy)

    logger.info("rows=%s", len(df))
    logger.info("econ_id groups=%s", df["economic_event_id"].nunique())
    logger.info("mode=%s", "include_o4" if include_o4 else "exclude_o4")
    if case_tags:
        logger.info("case_tags=%s", list(case_tags))
    logger.info("case_tag counts:\n%s", df["case_tag"].value_counts(dropna=False).to_string())
    logger.info(
        "hint: python -m engine.divpipe.check_severity --run-root %s --respect-existing-econ-id",
        run_root.as_posix(),
    )


def main_logic(args: argparse.Namespace) -> None:
    case_tags = _normalise_case_tags(args.case_tags)
    include_o4 = _resolve_include_o4(
        include_o4_flag=bool(args.include_o4),
        exclude_o4_flag=bool(args.exclude_o4),
        case_tags=case_tags,
    )
    run_root = Path(args.run_root)

    df = build_fixture_rows(
        include_o4=include_o4,
        case_tags=case_tags,
    )

    out_stage1, no_div_stage1, out_root_copy = _write_fixture_files(
        df=df,
        run_root=run_root,
        out_name=args.out_name,
        write_root_copy=bool(args.write_root_copy),
    )

    _log_fixture_summary(
        df=df,
        include_o4=include_o4,
        case_tags=case_tags,
        out_stage1=out_stage1,
        no_div_stage1=no_div_stage1,
        out_root_copy=out_root_copy,
        run_root=run_root,
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.log_level)
    main_logic(args)


if __name__ == "__main__":
    main()