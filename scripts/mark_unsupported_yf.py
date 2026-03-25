# scripts/mark_unsupported_yf.py

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _norm_str(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chosen-map", required=True, type=str)
    ap.add_argument("--in-hard", required=True, type=str, help="output/hard_fail_tickers.csv")
    ap.add_argument("--tag", default="UNSUPPORTED_YF", type=str)
    ap.add_argument("--reason", default="unsupported_vendor:yfinance", type=str)
    ap.add_argument("--method", default="manual_tag", type=str)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    p_map = Path(args.chosen_map)
    p_hard = Path(args.in_hard)

    df = pd.read_csv(p_map)
    hard = pd.read_csv(p_hard)

    if "isin" not in df.columns or "isin" not in hard.columns:
        raise ValueError("isin column required in both chosen-map and hard file")

    df = df.copy()
    isin_df = _norm_str(df["isin"]).str.upper()
    isin_hard = set(_norm_str(hard["isin"]).str.upper().tolist())

    m = isin_df.isin(isin_hard)
    patched = int(m.sum())

    # set fields
    for col in ["chosen_ticker", "reason", "method"]:
        if col not in df.columns:
            df[col] = ""

    df.loc[m, "chosen_ticker"] = args.tag
    df.loc[m, "reason"] = args.reason
    df.loc[m, "method"] = args.method

    print("rows_in_hard", len(hard))
    print("patched_rows", patched)

    if args.dry_run:
        print(df.loc[m, ["underlying", "underlying_ccy", "isin", "chosen_ticker", "reason", "method"]].head(50).to_string(index=False))
        return 0

    bak = p_map.with_suffix(p_map.suffix + ".bak2")
    bak.write_text(p_map.read_text())
    df.to_csv(p_map, index=False)
    print("backup", str(bak))
    print("overwrote", str(p_map))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

