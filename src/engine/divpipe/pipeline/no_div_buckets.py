# src/engine/divpipe/pipeline/no_div_buckets.py

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd
from pandas.errors import EmptyDataError

from engine.divpipe.schema.columns import STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS

NO_DIV_BUCKET_FILES = {
    "unsupported": "seed_yfinance_no_dividends_all__unsupported.csv",
    "kr": "seed_yfinance_no_dividends_all__kr.csv",
    "rest": "seed_yfinance_no_dividends_all__rest.csv",
    "rest_suspect": "seed_yfinance_no_dividends_all__rest__suspect_mapping.csv",
}


def empty_frame(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def read_csv_or_empty(path: Path, *, columns: Sequence[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return empty_frame(columns or [])

    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return empty_frame(columns or [])


def classify_yf_no_div_rows(df: pd.DataFrame) -> pd.Series:
    exists_ticker = df.get(
        "exists_ticker",
        pd.Series("", index=df.index, dtype="string"),
    ).astype("string").fillna("")

    underlying = df.get(
        "underlying",
        pd.Series("", index=df.index, dtype="string"),
    ).astype("string").fillna("")

    candidate_count = pd.to_numeric(
        df.get("candidate_count", pd.Series(0, index=df.index)),
        errors="coerce",
    ).fillna(0)

    bucket = pd.Series("rest", index=df.index, dtype="string")

    mask_unsupported = exists_ticker.eq("UNSUPPORTED_YF")
    mask_kr = exists_ticker.str.contains(r"\.(?:KS|KQ)\b", regex=True, na=False)

    cand_ge2 = candidate_count.ge(2)
    suffix_mismatch = exists_ticker.str.contains(r"\.", regex=True, na=False) & ~underlying.str.contains(
        r"\.", regex=True, na=False
    )
    mask_rest_suspect = ~(mask_unsupported | mask_kr) & (cand_ge2 | suffix_mismatch)

    bucket.loc[mask_unsupported] = "unsupported"
    bucket.loc[mask_kr] = "kr"
    bucket.loc[mask_rest_suspect] = "rest_suspect"

    return bucket


def split_no_div_buckets(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    classified = df.copy()
    classified["bucket"] = classify_yf_no_div_rows(classified)
    classified["suspect_mapping"] = classified["bucket"].eq("rest_suspect")

    return {
        "unsupported": classified.loc[classified["bucket"].eq("unsupported")].copy(),
        "kr": classified.loc[classified["bucket"].eq("kr")].copy(),
        "rest": classified.loc[classified["bucket"].isin(["rest", "rest_suspect"])].copy(),
        "rest_suspect": classified.loc[classified["bucket"].eq("rest_suspect")].copy(),
    }


def write_no_div_bucket_files(
    *,
    no_div_all_path: Path,
    stage1_dir: Path,
    default_columns: Sequence[str] | None = None,
) -> dict[str, int]:
    cols = list(default_columns or STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)
    df = read_csv_or_empty(no_div_all_path, columns=cols)

    if df.empty:
        empty_cols = list(df.columns) if len(df.columns) else cols
        for file_name in NO_DIV_BUCKET_FILES.values():
            empty_frame(empty_cols).to_csv(stage1_dir / file_name, index=False, encoding="utf-8-sig")
        return {
            "unsupported": 0,
            "kr": 0,
            "rest": 0,
            "rest_suspect": 0,
        }

    buckets = split_no_div_buckets(df)

    for bucket_name, file_name in NO_DIV_BUCKET_FILES.items():
        buckets[bucket_name].to_csv(stage1_dir / file_name, index=False, encoding="utf-8-sig")

    return {name: len(frame) for name, frame in buckets.items()}