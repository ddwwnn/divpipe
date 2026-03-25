# src/engine/divpipe/pipeline/run_outputs.py

from __future__ import annotations

from typing import Sequence

import pandas as pd


def empty_frame(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def ensure_required_columns(
    df: pd.DataFrame | None,
    required_columns: Sequence[str],
) -> pd.DataFrame | None:
    if df is None:
        return None

    out = df.copy()
    for col in required_columns:
        if col not in out.columns:
            out[col] = ""

    ordered = list(required_columns) + [c for c in out.columns if c not in required_columns]
    return out.reindex(columns=ordered)


def write_csv(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_csv_or_empty(
    df: pd.DataFrame | None,
    path,
    *,
    columns: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if df is None or df.empty:
        empty_frame(columns or []).to_csv(path, index=False, encoding="utf-8-sig")
        return

    out = ensure_required_columns(df, columns or [])
    out.to_csv(path, index=False, encoding="utf-8-sig")


def write_err_csv(err_df: pd.DataFrame | None, path, *, err_cols: Sequence[str]) -> None:
    write_csv_or_empty(err_df, path, columns=err_cols)


def concat_or_empty(
    frames: list[pd.DataFrame | None],
    *,
    default_columns: Sequence[str],
    numeric_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    realised = [f.copy() for f in frames if f is not None]
    if not realised:
        out = empty_frame(default_columns)
    else:
        out = pd.concat(realised, ignore_index=True)
        ordered = list(default_columns) + [c for c in out.columns if c not in default_columns]
        out = out.reindex(columns=ordered)

    if numeric_cols:
        for col in numeric_cols:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def build_input_rejections_df(
    rows: list[pd.DataFrame],
    *,
    input_rejection_columns: Sequence[str],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(input_rejection_columns))

    realised = [df.copy() for df in rows if df is not None and not df.empty]
    if not realised:
        return pd.DataFrame(columns=list(input_rejection_columns))

    out = pd.concat(realised, ignore_index=True)

    for col in input_rejection_columns:
        if col not in out.columns:
            out[col] = ""

    return out[list(input_rejection_columns)].copy()


def write_input_rejections_csv(path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_stage1_aggregate_outputs(
    *,
    artefacts,
    results: Sequence[object],
    default_seed_cols: Sequence[str],
    stage1_errors_required_columns: Sequence[str],
    stage1_no_dividends_required_columns: Sequence[str],
    discovered_candidate_required_columns: Sequence[str],
    input_rejection_columns: Sequence[str],
) -> dict[str, pd.DataFrame]:
    seed_all = concat_or_empty(
        [r.seed_df for r in results],
        default_columns=default_seed_cols,
        numeric_cols=["amount", "weight"],
    )
    err_all = concat_or_empty(
        [r.err_df for r in results],
        default_columns=stage1_errors_required_columns,
    )
    no_div_all = concat_or_empty(
        [r.no_div_df for r in results],
        default_columns=stage1_no_dividends_required_columns,
    )
    discovered_candidate_all = concat_or_empty(
        [r.discovered_candidate_df for r in results],
        default_columns=discovered_candidate_required_columns,
    )
    input_rejections_all = build_input_rejections_df(
        [r.input_rejection_df for r in results],
        input_rejection_columns=input_rejection_columns,
    )

    write_csv(seed_all, artefacts.seed_dividends_all)
    write_csv(err_all, artefacts.seed_errors_all)
    write_csv(no_div_all, artefacts.seed_no_dividends_all)
    write_csv(discovered_candidate_all, artefacts.seed_discovered_candidates_all)
    write_input_rejections_csv(artefacts.seed_input_rejections_all, input_rejections_all)

    return {
        "seed_all": seed_all,
        "err_all": err_all,
        "no_div_all": no_div_all,
        "discovered_candidate_all": discovered_candidate_all,
        "input_rejections_all": input_rejections_all,
    }


def drop_heavy_stage1_frames(results: Sequence[object]) -> None:
    for result in results:
        result.universe_df = None
        result.seed_df = None
        result.err_df = None
        result.no_div_df = None
        result.discovered_candidate_df = None
        result.input_rejection_df = None