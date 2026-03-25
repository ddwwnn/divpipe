# src/engine/divpipe/pipeline/overrides.py

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

Action = Literal["DROP", "SET_ECON_ID", "SET_ANCHOR_DATE"]

REQ_COLS = ["vendor_event_id", "underlying", "ex_date", "action"]
OPT_COLS = ["amount", "div_ccy", "economic_event_id", "anchor_date", "note"]


def load_qa_decisions(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    missing = [c for c in REQ_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"manual overrides missing required columns: {missing} in {path}")

    # normalise strings
    for c in ["vendor_event_id", "underlying", "ex_date", "div_ccy", "action", "economic_event_id", "anchor_date"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # normalise action
    df["action"] = df["action"].str.upper()
    bad_actions = sorted(set(df["action"]) - {"DROP", "SET_ECON_ID", "SET_ANCHOR_DATE"})
    if bad_actions:
        raise ValueError(f"unknown override action(s): {bad_actions} in {path}")

    # action-specific validation
    need_econ = df["action"].eq("SET_ECON_ID") & df.get("economic_event_id", "").eq("")
    if need_econ.any():
        raise ValueError("SET_ECON_ID requires economic_event_id (non-empty)")

    need_anchor = df["action"].eq("SET_ANCHOR_DATE") & df.get("anchor_date", "").eq("")
    if need_anchor.any():
        raise ValueError("SET_ANCHOR_DATE requires anchor_date (non-empty)")

    return df


def _col_as_str(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="string")
    return df[name].fillna("").astype("string").str.strip()


def _build_match_key(df: pd.DataFrame) -> pd.Series:
    """
    vendor_event_id|underlying|ex_date|amount|div_ccy
    NOTE: does NOT mutate df dtypes.
    """
    return (
        _col_as_str(df, "vendor_event_id")
        + "|"
        + _col_as_str(df, "underlying")
        + "|"
        + _col_as_str(df, "ex_date")
        + "|"
        + _col_as_str(df, "amount")
        + "|"
        + _col_as_str(df, "div_ccy")
    )


def _wild_key(df: pd.DataFrame) -> pd.Series:
    """
    vendor_event_id|underlying|ex_date||
    """
    return _col_as_str(df, "vendor_event_id") + "|" + _col_as_str(df, "underlying") + "|" + _col_as_str(df, "ex_date") + "||"


def apply_qa_decisions(rows: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    """
    rows must contain: vendor_event_id, underlying, ex_date, amount, div_ccy, economic_event_id
    overrides must contain at least: vendor_event_id, underlying, ex_date, action
    Optional: amount/div_ccy (blank => wildcard), economic_event_id, anchor_date
    """
    out = rows.copy()

    for c in ["vendor_event_id", "underlying", "ex_date", "amount", "div_ccy", "economic_event_id"]:
        if c not in out.columns:
            raise ValueError(f"rows missing required column: {c}")

    ov = overrides.copy()

    # Build keys (no dtype mutation)
    out["_row_key"] = _build_match_key(out)
    out["_wild_key"] = _wild_key(out)

    ov["_ov_key"] = _build_match_key(ov)
    ov["_wild_key"] = _wild_key(ov)

    # Determine whether each override row is wildcard (amount/div_ccy blank after normalisation)
    ov_amount = _col_as_str(ov, "amount")
    ov_ccy = _col_as_str(ov, "div_ccy")
    ov_is_wild = (ov_amount.eq("")) & (ov_ccy.eq(""))

    ov_exact = ov.loc[~ov_is_wild].copy()
    ov_wild = ov.loc[ov_is_wild].copy()

    # Determinism: reject duplicate keys (otherwise "last wins" silently)
    if ov_exact["_ov_key"].duplicated().any():
        dups = ov_exact.loc[ov_exact["_ov_key"].duplicated(), "_ov_key"].unique().tolist()
        raise ValueError(f"duplicate exact override keys: {dups}")

    if ov_wild["_wild_key"].duplicated().any():
        dups = ov_wild.loc[ov_wild["_wild_key"].duplicated(), "_wild_key"].unique().tolist()
        raise ValueError(f"duplicate wildcard override keys: {dups}")

    exact_map = ov_exact.set_index("_ov_key")
    wild_map = ov_wild.set_index("_wild_key")

    # For each row: prefer exact match, else wildcard match
    exact_hit = out["_row_key"].isin(exact_map.index)
    wild_hit = (~exact_hit) & out["_wild_key"].isin(wild_map.index)

    # Build action series
    action = pd.Series([""] * len(out), index=out.index, dtype="string")
    if exact_hit.any():
        action.loc[exact_hit] = exact_map.loc[out.loc[exact_hit, "_row_key"], "action"].astype("string").values
    if wild_hit.any():
        action.loc[wild_hit] = wild_map.loc[out.loc[wild_hit, "_wild_key"], "action"].astype("string").values

    # DROP
    drop_mask = action.eq("DROP")
    if drop_mask.any():
        out = out.loc[~drop_mask].copy()
        # recompute hits after drop
        out["_row_key"] = _build_match_key(out)
        out["_wild_key"] = _wild_key(out)
        exact_hit = out["_row_key"].isin(exact_map.index)
        wild_hit = (~exact_hit) & out["_wild_key"].isin(wild_map.index)
        action = pd.Series([""] * len(out), index=out.index, dtype="string")
        if exact_hit.any():
            action.loc[exact_hit] = exact_map.loc[out.loc[exact_hit, "_row_key"], "action"].astype("string").values
        if wild_hit.any():
            action.loc[wild_hit] = wild_map.loc[out.loc[wild_hit, "_wild_key"], "action"].astype("string").values

    # SET_ECON_ID
    set_econ = action.eq("SET_ECON_ID")
    if set_econ.any():
        # exact rows
        m = set_econ & exact_hit
        if m.any():
            out.loc[m, "economic_event_id"] = exact_map.loc[out.loc[m, "_row_key"], "economic_event_id"].astype("string").values
        # wildcard rows
        m = set_econ & wild_hit
        if m.any():
            out.loc[m, "economic_event_id"] = wild_map.loc[out.loc[m, "_wild_key"], "economic_event_id"].astype("string").values

    # SET_ANCHOR_DATE
    if "anchor_date" in out.columns:
        set_anchor = action.eq("SET_ANCHOR_DATE")
        if set_anchor.any():
            m = set_anchor & exact_hit
            if m.any():
                out.loc[m, "anchor_date"] = exact_map.loc[out.loc[m, "_row_key"], "anchor_date"].astype("string").values
            m = set_anchor & wild_hit
            if m.any():
                out.loc[m, "anchor_date"] = wild_map.loc[out.loc[m, "_wild_key"], "anchor_date"].astype("string").values

    # Cleanup
    out.drop(columns=[c for c in ["_row_key", "_wild_key"] if c in out.columns], inplace=True)
    return out