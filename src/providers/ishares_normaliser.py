# src/providers/ishares_normaliser.py

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from providers.ishares_registry import get_fund_spec

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/ishares")
WEIGHT_SUM_TOL = 0.02
MAX_PARSE_FAIL_RATIO = 0.02
MAX_NONPOS_RATIO = 0.20

FULL_OUTPUT_COLUMNS = [
    "asof_date",
    "etf_symbol",
    "underlying",
    "name",
    "sector",
    "asset_class",
    "exchange",
    "country",
    "currency",
    "underlying_ccy",
    "isin",
    "sedol",
    "cusip",
    "weight_pct",
    "weight",
    "market_value",
    "notional_value",
    "quantity",
    "price",
    "fx_rate",
    "accrual_date",
]


@dataclass(frozen=True)
class IShareMeta:
    asof_date: str


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--etf", required=True, nargs="+", help="One or more ETF symbols, e.g. EEM EFA")
    p.add_argument("--raw", default="", help="Optional explicit raw JSON path. Only valid for a single ETF.")
    p.add_argument(
        "--out-full",
        default="",
        help="Optional explicit holdings output path. Only valid for a single ETF. Default: data/holdings_<ETF>.csv",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="divpipe ishares normalise")
    add_arguments(p)
    return p


def register_parser(subparsers) -> None:
    p = subparsers.add_parser("normalise", help="Normalise iShares raw JSON into divpipe holdings CSVs")
    add_arguments(p)
    p.set_defaults(func=main_logic)
    return p


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = build_parser()
    return p.parse_args(list(argv) if argv is not None else None)


def _parse_filename_date(prefix: str) -> datetime | None:
    try:
        return datetime.strptime(prefix, "%Y%m%d")
    except ValueError:
        return None


def latest_raw_file(etf_symbol: str, raw_dir: Path = RAW_DIR) -> Path:
    files = list(raw_dir.glob(f"*_{etf_symbol}.json"))
    if not files:
        raise FileNotFoundError(f"No raw JSON files found for {etf_symbol} under {raw_dir.resolve()}")

    def key(path: Path) -> datetime:
        prefix = path.stem.split("_")[0]
        dt = _parse_filename_date(prefix)
        if dt is not None:
            return dt
        return datetime.fromtimestamp(path.stat().st_mtime)

    files.sort(key=key, reverse=True)
    return files[0]


def _parse_asof_date(raw_date: str) -> str:
    text = str(raw_date).strip()
    if not text:
        raise ValueError("Missing iShares as-of date")
    try:
        return datetime.strptime(text, "%b %d, %Y").strftime("%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Unexpected iShares as-of date format: {raw_date!r}") from exc


def _extract_asof_date(payload: dict[str, Any], raw_path: Path) -> str:
    raw_date = str(payload.get("asOfDate", "")).strip()
    if raw_date:
        return _parse_asof_date(raw_date)

    m = re.match(r"^(\d{8})_", raw_path.stem)
    if m:
        return m.group(1)

    raise ValueError(f"Could not determine as-of date from payload or filename: {raw_path}")


def _load_raw_payload(raw_path: Path) -> dict[str, Any]:
    text = raw_path.read_text(encoding="utf-8-sig")
    data = json.loads(text)

    if isinstance(data, dict):
        return data

    if isinstance(data, list):
        return {"aaData": data}

    raise ValueError(f"Unexpected JSON root type in {raw_path}: {type(data).__name__}")


def _extract_raw_value(x: Any) -> Any:
    if isinstance(x, dict):
        if "raw" in x:
            return x["raw"]
        if "display" in x:
            return x["display"]
        return ""
    return x


def _clean_text(x: Any) -> str:
    v = _extract_raw_value(x)
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in {"", "nan", "none", "<na>", "-"}:
        return ""
    return s


def _clean_id(x: Any) -> str:
    return _clean_text(x).replace(" ", "").upper()


def _clean_float(x: Any) -> float | None:
    v = _extract_raw_value(x)
    if v is None:
        return None

    if isinstance(v, (int, float)):
        return float(v)

    s = str(v).strip().replace(",", "").replace("$", "")
    if s.lower() in {"", "nan", "none", "<na>", "-"}:
        return None

    try:
        return float(s)
    except ValueError:
        return None


def _pad_row(row: list[Any], min_len: int = 17) -> list[Any]:
    if len(row) >= min_len:
        return row
    return row + [""] * (min_len - len(row))


def _validate_weights(df: pd.DataFrame, *, context: str) -> None:
    total = float(df["weight"].sum())
    parse_fail_ratio = float(df["weight_pct"].isna().mean())
    non_positive_ratio = float(df["weight_pct"].fillna(0).le(0).mean())

    if abs(total - 1.0) > WEIGHT_SUM_TOL:
        raise ValueError(
            f"[QC FAIL] {context}: sum(weight)={total:.6f} "
            f"(expected ~1.0 within ±{WEIGHT_SUM_TOL:.2%})"
        )

    if parse_fail_ratio > MAX_PARSE_FAIL_RATIO:
        raise ValueError(
            f"[QC FAIL] {context}: weight parse-fail ratio={parse_fail_ratio:.2%} "
            f"(limit {MAX_PARSE_FAIL_RATIO:.2%})"
        )

    if non_positive_ratio > MAX_NONPOS_RATIO:
        raise ValueError(
            f"[QC FAIL] {context}: non-positive weight ratio={non_positive_ratio:.2%} "
            f"(limit {MAX_NONPOS_RATIO:.2%})"
        )


def _build_base_holdings_frame(
    *,
    payload: dict[str, Any],
    raw_path: Path,
    etf_symbol: str,
) -> tuple[IShareMeta, pd.DataFrame]:
    aa_data = payload.get("aaData", [])
    if not isinstance(aa_data, list):
        raise ValueError(f"aaData is missing or not a list: {raw_path}")

    asof_date = _extract_asof_date(payload, raw_path)
    meta = IShareMeta(asof_date=asof_date)

    rows: list[dict[str, Any]] = []

    for raw_row in aa_data:
        if not isinstance(raw_row, list):
            continue

        padded = _pad_row(raw_row, 17)

        asset_class = _clean_text(padded[3])
        if asset_class.lower() != "equity":
            continue

        raw_w = _clean_float(padded[5])

        rows.append(
            {
                "asof_date": meta.asof_date,
                "etf_symbol": etf_symbol.upper(),
                "underlying": _clean_text(padded[0]),
                "name": _clean_text(padded[1]),
                "sector": _clean_text(padded[2]),
                "asset_class": asset_class,
                "exchange": _clean_text(padded[13]),
                "country": _clean_text(padded[12]),
                "currency": _clean_text(padded[14]),
                "underlying_ccy": _clean_text(padded[14]) or "USD",
                "isin": _clean_id(padded[9]),
                "sedol": _clean_id(padded[10]),
                "cusip": _clean_id(padded[8]),
                "weight_pct": raw_w,
                "weight": (float(raw_w) / 100.0) if raw_w is not None else 0.0,
                "market_value": _clean_float(padded[4]),
                "notional_value": _clean_float(padded[6]),
                "quantity": _clean_float(padded[7]),
                "price": _clean_float(padded[11]),
                "fx_rate": _clean_float(padded[15]),
                "accrual_date": _clean_text(padded[16]),
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError(f"No equity holdings found in {raw_path}")

    df = df.loc[df["underlying"].astype(str).str.len().gt(0)].copy()
    df = df.drop_duplicates(subset=["underlying", "isin", "weight_pct"], keep="first").reset_index(drop=True)

    _validate_weights(df, context=f"{etf_symbol} equity-only")

    for col in FULL_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[FULL_OUTPUT_COLUMNS].copy()
    return meta, df


def _write_outputs(df: pd.DataFrame, out_full_path: Path) -> None:
    out_full_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_full_path, index=False, encoding="utf-8-sig")


def normalise_ishares_json(
    *,
    raw_path: Path,
    etf_symbol: str,
    out_full_path: Path,
) -> None:
    fund_spec = get_fund_spec(etf_symbol)
    payload = _load_raw_payload(raw_path)
    meta, full_df = _build_base_holdings_frame(
        payload=payload,
        raw_path=raw_path,
        etf_symbol=fund_spec.symbol,
    )

    _write_outputs(full_df, out_full_path)

    isin_blank_ratio = float(full_df["isin"].astype("string").fillna("").str.len().eq(0).mean())

    logger.info(
        "%s asof=%s rows=%s equity_weight_sum=%.6f region=%s out=%s isin_blank_ratio=%.2f%%",
        fund_spec.symbol,
        meta.asof_date,
        len(full_df),
        float(full_df["weight"].sum()),
        fund_spec.default_coverage,
        out_full_path,
        isin_blank_ratio * 100.0,
    )


def _validate_multi_etf_args(etfs: list[str], args: argparse.Namespace) -> None:
    if len(etfs) <= 1:
        return

    if str(args.raw).strip():
        raise ValueError("--raw is only supported with a single ETF")
    if str(args.out_full).strip():
        raise ValueError("--out-full is only supported with a single ETF")


def main_logic(args: argparse.Namespace) -> None:
    etfs = [str(x).strip().upper() for x in args.etf]
    if not etfs:
        raise ValueError("At least one ETF must be provided via --etf")

    _validate_multi_etf_args(etfs, args)

    for etf in etfs:
        raw_path = Path(args.raw) if str(args.raw).strip() else latest_raw_file(etf)

        out_full = (
            Path(args.out_full)
            if str(args.out_full).strip()
            else Path(f"data/holdings_{etf}.csv")
        )

        normalise_ishares_json(
            raw_path=raw_path,
            etf_symbol=etf,
            out_full_path=out_full,
        )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    main_logic(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()