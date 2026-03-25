#scripts/apply_suggested_overrides.py

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _normalise_str(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chosen-map", required=True, help="data/chosen_ticker_map.csv")
    ap.add_argument("--suggested", required=True, help="output/suggested_overrides_from_search.csv")
    ap.add_argument("--out", default="", help="write patched csv (default: overwrite chosen-map with .bak)")
    args = ap.parse_args()

    cm_path = Path(args.chosen_map)
    sug_path = Path(args.suggested)

    df = pd.read_csv(cm_path)
    sug = pd.read_csv(sug_path)

    # normalise
    for c in ["underlying", "underlying_ccy", "isin", "chosen_ticker", "reason", "method"]:
        if c not in df.columns:
            df[c] = ""
    for c in ["underlying", "underlying_ccy", "isin", "suggested_ticker", "method"]:
        if c not in sug.columns:
            sug[c] = ""

    df["isin"] = _normalise_str(df["isin"]).str.upper()
    df["chosen_ticker"] = _normalise_str(df["chosen_ticker"])
    df["reason"] = _normalise_str(df["reason"])
    df["method"] = _normalise_str(df["method"])

    sug["isin"] = _normalise_str(sug["isin"]).str.upper()
    sug["suggested_ticker"] = _normalise_str(sug["suggested_ticker"])
    sug["method"] = _normalise_str(sug["method"])

    # only apply where chosen_ticker is empty AND we have a suggested_ticker
    m_empty = df["chosen_ticker"].eq("")
    sug_ok = sug[sug["suggested_ticker"].ne("")].copy()

    # dedupe suggestions by isin (keep first)
    sug_ok = sug_ok.drop_duplicates(subset=["isin"], keep="first")
    sug_map = dict(zip(sug_ok["isin"], sug_ok["suggested_ticker"]))
    sug_method_map = dict(zip(sug_ok["isin"], sug_ok["method"]))

    hit = m_empty & df["isin"].isin(sug_map.keys())
    df.loc[hit, "chosen_ticker"] = df.loc[hit, "isin"].map(sug_map)
    df.loc[hit, "reason"] = "override_suggested"
    df.loc[hit, "method"] = df.loc[hit, "isin"].map(sug_method_map).replace("", "suggest_overrides_yahoo")

    patched_rows = int(hit.sum())
    print("patched_rows", patched_rows)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print("wrote", str(out_path))
    else:
        bak = cm_path.with_suffix(cm_path.suffix + ".bak")
        bak.write_bytes(cm_path.read_bytes())
        df.to_csv(cm_path, index=False)
        print("backup", str(bak))
        print("overwrote", str(cm_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

