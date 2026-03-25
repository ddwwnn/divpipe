# src/engine/divpipe/pipeline/link_events.py

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

import pandas as pd

from ..core.event_id import (
    LinkPolicy,
    _safe_float,
    make_economic_event_id,
    should_link_events,
)
from ..utils.ccy import normalise_ccy


def _sha256_hex_n(s: str, n_hex: int = 32) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n_hex]


def _blank_to_na(s: pd.Series) -> pd.Series:
    s = s.astype("string").fillna("").str.strip()
    return s.replace({"": pd.NA})


def _normalise_text_sentinels(s: pd.Series) -> pd.Series:
    s = _blank_to_na(s).astype("string")
    return s.replace(
        {
            "NONE": pd.NA,
            "NAN": pd.NA,
            "<NA>": pd.NA,
            "None": pd.NA,
            "nan": pd.NA,
        }
    )


def _get_series(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col in df.columns:
        return df[col]
    return pd.Series([default] * len(df), index=df.index, dtype="string")


def _norm_text(s: pd.Series, *, upper: bool = True) -> pd.Series:
    out = _normalise_text_sentinels(s).astype("string")
    if upper:
        out = out.str.upper()
    return out


def _norm_ccy(s: pd.Series) -> pd.Series:
    out = _normalise_text_sentinels(s).map(normalise_ccy).astype("string")
    return out.str.upper()


def _safe_key_part(x: Any) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return str(x).strip()


def _to_date_series(s: pd.Series) -> pd.Series:
    dt = pd.to_datetime(_blank_to_na(s), errors="coerce")
    return dt.dt.date


def _pick_anchor_date(df: pd.DataFrame) -> pd.Series:
    exd = _to_date_series(_get_series(df, "ex_date", ""))
    rcd = _to_date_series(_get_series(df, "record_date", ""))
    pyd = _to_date_series(_get_series(df, "pay_date", ""))
    return exd.fillna(rcd).fillna(pyd)


def _primary_ident(df: pd.DataFrame) -> pd.Series:
    isin = _norm_text(_get_series(df, "isin", ""))
    und = _norm_text(_get_series(df, "underlying", ""))
    return isin.fillna(und)


def _div_ccy(df: pd.DataFrame) -> pd.Series:
    if "div_ccy" in df.columns:
        return _norm_ccy(df["div_ccy"])
    if "amount_ccy" in df.columns:
        return _norm_ccy(df["amount_ccy"])
    if "currency" in df.columns:
        return _norm_ccy(df["currency"])
    return pd.Series([pd.NA] * len(df), index=df.index, dtype="string")


def _mk_econ_group_key(ident: str, action: str, share: str, ccy: str) -> str:
    vals = [_safe_key_part(v) for v in [ident, action, share, ccy]]
    return "|".join(vals)


def _mk_econ_event_key(group_key: str, anchor: date, seed_tie: str) -> str:
    """
    Build the economic-event key.

    The key includes:
      - canonical group identity
      - anchor date
      - seed tie

    The seed tie is included so that two rows with the same canonical group
    and the same anchor date can still form different economic events when
    the linking policy decides they must not link.

    This prevents forced collisions under a pure:
      group_key + anchor_date
    scheme.

    In other words:
      same anchor date does not imply same economic event.
    """
    return f"{group_key}|{anchor.isoformat()}|{seed_tie}"


def _stable_amount_text(s: pd.Series, *, decimals: int) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.map(lambda v: f"{v:.{decimals}f}" if pd.notna(v) else "")


def _source_priority_series(df: pd.DataFrame, *, policy: LinkPolicy) -> pd.Series:
    if not policy.source_priority:
        return pd.Series(999_999, index=df.index, dtype="int64")

    src = _norm_text(_get_series(df, "source", "")).fillna("").astype("string")
    return src.map(lambda x: int(policy.source_priority.get(str(x), 999_999))).astype("int64")


def _build_tie_raw(df: pd.DataFrame, *, policy: LinkPolicy) -> pd.Series:
    div_type = _norm_text(_get_series(df, "div_type", "unknown")).fillna("UNKNOWN").astype("string")
    status = _norm_text(_get_series(df, "status", "unknown")).fillna("UNKNOWN").astype("string")
    amt_txt = _stable_amount_text(
        df.get("amt_link", pd.Series([pd.NA] * len(df), index=df.index)),
        decimals=policy.stable_amount_decimals,
    )

    return (
        df.get("primary_ident", pd.Series([pd.NA] * len(df), index=df.index)).astype("string").fillna("")
        + "|"
        + df.get("div_ccy", pd.Series([pd.NA] * len(df), index=df.index)).astype("string").fillna("")
        + "|"
        + df.get("anchor_date", pd.Series([pd.NA] * len(df), index=df.index)).astype("string").fillna("")
        + "|"
        + amt_txt
        + "|"
        + div_type
        + "|"
        + status
    )


def _mk_stable_tie(df: pd.DataFrame, *, policy: LinkPolicy) -> tuple[pd.Series, pd.Series]:
    v = _blank_to_na(_get_series(df, "vendor_event_id", "")).astype("string").fillna("").str.strip()
    out = v

    missing = out.eq("")
    if "source_event_key" in df.columns:
        sek = _blank_to_na(df["source_event_key"]).astype("string").fillna("").str.strip()
        out = out.where(~missing, sek)

    tie_raw = _build_tie_raw(df, policy=policy)

    still_missing = out.eq("")
    fp = tie_raw.map(lambda x: _sha256_hex_n(str(x), 32))
    out = out.where(~still_missing, fp)
    return out, tie_raw


def _nunique_nonblank(s: pd.Series) -> int:
    if s is None:
        return 0
    ss = s.astype("string").fillna("").str.strip().str.upper()
    ss = ss[ss.ne("")]
    return int(ss.nunique(dropna=True))


def _amount_rel_spread(s: pd.Series, *, min_denom: float = 1e-9) -> float:
    x = pd.to_numeric(s, errors="coerce").dropna()
    if x.empty:
        return 0.0

    max_abs = float(x.abs().max())
    min_abs = float(x.abs().min())

    if max_abs <= min_denom:
        return 0.0

    return (max_abs - min_abs) / max_abs


def _build_skip_reason(
    *,
    missing_ident: pd.Series,
    missing_div_ccy: pd.Series,
    missing_anchor_date: pd.Series,
) -> pd.Series:
    a = missing_ident.map(lambda x: "missing_ident" if x else "")
    b = missing_div_ccy.map(lambda x: "missing_div_ccy" if x else "")
    c = missing_anchor_date.map(lambda x: "missing_anchor_date" if x else "")

    out = pd.Series([""] * len(a), index=a.index, dtype="string")
    out = out.where(a.eq(""), a)
    out = out.where(b.eq(""), out + b.where(out.eq(""), "," + b))
    out = out.where(c.eq(""), out + c.where(out.eq(""), "," + c))
    return "skip:" + out


def _validate_vendor_event_groups(
    df: pd.DataFrame,
    *,
    policy: LinkPolicy,
) -> None:
    if "vendor_event_id" not in df.columns:
        return

    v = df["vendor_event_id"].astype("string").fillna("").str.strip()
    has_vid = v.ne("")
    if not has_vid.any():
        return

    tmp = df.loc[has_vid].copy()
    tmp["vendor_event_id_norm"] = v.loc[has_vid].astype("string")
    tmp["anchor_dt"] = pd.to_datetime(tmp.get("anchor_date"), errors="coerce")

    grouped = tmp.groupby("vendor_event_id_norm", sort=False)

    agg = pd.DataFrame(index=grouped.size().index)
    if "primary_ident" in tmp.columns:
        agg["ident_nunique"] = grouped["primary_ident"].apply(_nunique_nonblank).astype("int64")
    else:
        agg["ident_nunique"] = 0

    if "div_ccy" in tmp.columns:
        agg["ccy_nunique"] = grouped["div_ccy"].apply(_nunique_nonblank).astype("int64")
    else:
        agg["ccy_nunique"] = 0

    if "amount" in tmp.columns:
        agg["amount_rel_spread"] = grouped["amount"].apply(_amount_rel_spread).astype("float64")
    else:
        agg["amount_rel_spread"] = 0.0

    anchor_min = grouped["anchor_dt"].min()
    anchor_max = grouped["anchor_dt"].max()
    agg["anchor_spread_days"] = (anchor_max - anchor_min).dt.days.fillna(0).astype("int64")

    bad_mask = (
        (agg["ident_nunique"] > 1)
        | (agg["ccy_nunique"] > 1)
        | (agg["anchor_spread_days"] > policy.vendor_group_max_anchor_spread_days)
        | (agg["amount_rel_spread"] > policy.vendor_group_max_amount_rel_spread)
    )

    bad_vids = sorted(agg.index[bad_mask].tolist())
    if not bad_vids:
        return

    sample_cols = [
        c
        for c in [
            "vendor_event_id",
            "primary_ident",
            "div_ccy",
            "anchor_date",
            "amount",
            "source",
            "source_event_key",
        ]
        if c in tmp.columns
    ]
    sample = (
        tmp[tmp["vendor_event_id_norm"].isin(bad_vids)]
        .loc[:, sample_cols]
        .drop_duplicates()
        .sort_values(["vendor_event_id", "anchor_date", "source_event_key"], kind="mergesort")
        .head(30)
    )

    raise ValueError(
        "vendor_event_id group failed canonicalisation guardrail. "
        f"bad_vendor_event_id_count={len(bad_vids)} sample=\n{sample.to_string(index=False)}"
    )


def _canonicalise_by_observation(df: pd.DataFrame, *, policy: LinkPolicy) -> pd.DataFrame:
    if "vendor_event_id" not in df.columns:
        return df

    v = df["vendor_event_id"].astype("string").fillna("").str.strip()
    has_vid = v.ne("")
    if not has_vid.any():
        return df

    tie = df["stable_tie"].astype("string").fillna("")
    src_pri = _source_priority_series(df, policy=policy)

    isin = _blank_to_na(df.get("isin", pd.Series([pd.NA] * len(df), index=df.index)))
    und = _blank_to_na(df.get("underlying", pd.Series([pd.NA] * len(df), index=df.index)))
    ident = isin.fillna(und).astype("string").str.upper()

    div_ccy = _div_ccy(df).astype("string")
    anchor = _pick_anchor_date(df)
    action = _norm_text(df.get("action_type", "unknown")).fillna("UNKNOWN").astype("string")
    share = _norm_text(df.get("share_class", "unknown")).fillna("UNKNOWN").astype("string")

    tmp = pd.DataFrame(
        {
            "vendor_event_id": v,
            "ident_norm": ident,
            "div_ccy_norm": div_ccy,
            "anchor_norm": anchor,
            "action_norm": action,
            "share_norm": share,
            "source_priority": src_pri,
            "stable_tie": tie.astype("string"),
        },
        index=df.index,
    )

    t = tmp.loc[has_vid].copy()
    t = t.sort_values(
        [
            "vendor_event_id",
            "source_priority",
            "anchor_norm",
            "ident_norm",
            "div_ccy_norm",
            "action_norm",
            "share_norm",
            "stable_tie",
        ],
        kind="mergesort",
    )
    canon = t.groupby("vendor_event_id", sort=False, as_index=True).first()

    df2 = df.copy()
    mapped_vid = tmp.loc[has_vid, "vendor_event_id"]

    df2.loc[has_vid, "primary_ident"] = mapped_vid.map(canon["ident_norm"])
    df2.loc[has_vid, "div_ccy"] = mapped_vid.map(canon["div_ccy_norm"])
    df2.loc[has_vid, "anchor_date"] = mapped_vid.map(canon["anchor_norm"])
    df2.loc[has_vid, "action_type"] = mapped_vid.map(canon["action_norm"])
    df2.loc[has_vid, "share_class"] = mapped_vid.map(canon["share_norm"])

    return df2


def _normalise_event_link_reason_seeded(df_out: pd.DataFrame) -> pd.DataFrame:
    """
    Convert per-row reasons into:
      - 'seed' for the canonical first non-preset row per economic_event_id
      - 'linked' for all other non-preset rows with an economic_event_id

    Leaves:
      - 'preset' untouched
      - 'skip:...' untouched
    """
    if df_out is None or df_out.empty:
        return df_out
    if "economic_event_id" not in df_out.columns or "anchor_date" not in df_out.columns:
        return df_out

    econ = df_out["economic_event_id"].astype("string").fillna("").str.strip()
    has_econ = econ.ne("")
    if not has_econ.any():
        return df_out

    if "event_link_reason" in df_out.columns:
        reason = df_out["event_link_reason"].astype("string").fillna("")
        is_preset = reason.eq("preset")
    else:
        df_out["event_link_reason"] = ""
        is_preset = pd.Series([False] * len(df_out), index=df_out.index)

    non_preset_mask = has_econ & (~is_preset)
    if not non_preset_mask.any():
        return df_out

    tie = (
        df_out["stable_tie"].astype("string").fillna("")
        if "stable_tie" in df_out.columns
        else pd.Series([""] * len(df_out), index=df_out.index, dtype="string")
    )

    # Reduced row fingerprint:
    # use stable_tie plus a small secondary payload only.
    sec_a = (
        df_out["source"].astype("string").fillna("")
        if "source" in df_out.columns
        else pd.Series([""] * len(df_out), index=df_out.index, dtype="string")
    )
    sec_b = (
        df_out["source_event_key"].astype("string").fillna("")
        if "source_event_key" in df_out.columns
        else pd.Series([""] * len(df_out), index=df_out.index, dtype="string")
    )
    row_fp = (sec_a + "|" + sec_b).map(lambda x: _sha256_hex_n(str(x), 16))

    tmp = df_out.loc[non_preset_mask, ["economic_event_id", "anchor_date"]].copy()
    tmp["stable_tie"] = tie.loc[non_preset_mask].astype("string").fillna("")
    tmp["row_fp"] = row_fp.loc[non_preset_mask].astype("string").fillna("")
    tmp = tmp.sort_values(["economic_event_id", "anchor_date", "stable_tie", "row_fp"], kind="mergesort")

    seed_idx = tmp.groupby("economic_event_id", sort=False).head(1).index

    df_out.loc[non_preset_mask, "event_link_reason"] = "linked"
    df_out.loc[seed_idx, "event_link_reason"] = "seed"
    return df_out


def _prepare_linking_frame(
    divs: pd.DataFrame,
    *,
    respect_existing: bool,
    policy: LinkPolicy,
    keep_debug_cols: bool,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
    df = divs.copy()
    df["row_idx_link"] = range(len(df))

    df["action_type"] = _norm_text(_get_series(df, "action_type", "unknown")).fillna("UNKNOWN")
    df["share_class"] = _norm_text(_get_series(df, "share_class", "unknown")).fillna("UNKNOWN")
    df["primary_ident"] = _primary_ident(df)
    df["div_ccy"] = _div_ccy(df)
    df["anchor_date"] = _pick_anchor_date(df)
    df["amt_link"] = pd.to_numeric(df.get("amount", pd.NA), errors="coerce")

    stable_tie, debug_tie_raw = _mk_stable_tie(df, policy=policy)
    df["stable_tie"] = stable_tie
    if keep_debug_cols:
        df["debug_tie_raw"] = debug_tie_raw

    if "economic_event_key" not in df.columns:
        df["economic_event_key"] = ""
    else:
        df["economic_event_key"] = df["economic_event_key"].astype("string").fillna("")

    if "economic_event_id" not in df.columns:
        df["economic_event_id"] = ""
    else:
        df["economic_event_id"] = df["economic_event_id"].astype("string").fillna("")

    if "event_link_reason" not in df.columns:
        df["event_link_reason"] = ""
    else:
        df["event_link_reason"] = df["event_link_reason"].astype("string").fillna("")

    if respect_existing and "economic_event_id" in divs.columns:
        preset_econ = divs["economic_event_id"].astype("string").fillna("").str.strip()
        preset_mask = preset_econ.ne("")
        preset_econ = preset_econ.where(preset_mask, "")
    else:
        preset_mask = pd.Series([False] * len(df), index=df.index)
        preset_econ = pd.Series([""] * len(df), index=df.index, dtype="string")

    missing_ident = df["primary_ident"].isna()
    missing_div_ccy = df["div_ccy"].isna()
    missing_anchor_date = df["anchor_date"].isna()
    invalid = missing_ident | missing_div_ccy | missing_anchor_date

    skip_reason = pd.Series([""] * len(df), index=df.index, dtype="string")
    if invalid.any():
        skip_reason = _build_skip_reason(
            missing_ident=missing_ident,
            missing_div_ccy=missing_div_ccy,
            missing_anchor_date=missing_anchor_date,
        )
        df.loc[invalid, "event_link_reason"] = skip_reason.loc[invalid]

        if respect_existing and preset_mask.any():
            preset_econ = preset_econ.where(~invalid, "")

    return df, invalid, preset_mask, preset_econ, skip_reason


def _apply_existing_economic_ids(
    df: pd.DataFrame,
    *,
    preset_mask: pd.Series,
    preset_econ: pd.Series,
    respect_existing: bool,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    if not (respect_existing and preset_mask.any() and "vendor_event_id" in df.columns):
        return df, preset_mask, preset_econ

    v = df["vendor_event_id"].astype("string").fillna("").str.strip()
    has_v = v.ne("")
    m = preset_mask & has_v

    if m.any():
        tmp = pd.DataFrame(
            {
                "vendor_event_id": v.loc[m],
                "preset_econ": preset_econ.loc[m].astype("string").fillna("").str.strip(),
            }
        )
        tmp = tmp[tmp["preset_econ"].ne("")]

        if not tmp.empty:
            nunq = tmp.groupby("vendor_event_id", sort=False)["preset_econ"].nunique()
            bad_vids = nunq[nunq > 1].index.tolist()
            if bad_vids:
                sample = (
                    tmp[tmp["vendor_event_id"].isin(bad_vids)]
                    .drop_duplicates()
                    .sort_values(["vendor_event_id", "preset_econ"])
                    .head(30)
                )
                raise ValueError(
                    "conflicting preset economic_event_id for same vendor_event_id. "
                    f"bad_vendor_event_id_count={len(bad_vids)} sample=\n{sample.to_string(index=False)}"
                )

            canon = tmp.groupby("vendor_event_id", sort=False)["preset_econ"].first()
            preset_econ = v.map(canon).fillna(preset_econ)
            preset_mask = preset_econ.astype("string").fillna("").str.strip().ne("")

    if preset_mask.any():
        ok_preset = preset_econ.astype("string").fillna("").str.strip().ne("")
        if ok_preset.any():
            df.loc[ok_preset, "economic_event_id"] = preset_econ.loc[ok_preset].astype("string")
            df.loc[ok_preset, "event_link_reason"] = "preset"
        preset_mask = ok_preset

    return df, preset_mask, preset_econ


def _link_valid_groups(
    valid: pd.DataFrame,
    *,
    policy: LinkPolicy,
) -> pd.DataFrame:
    """
    Link rows within each canonical group.

    The event identity is seeded by the first row of each cluster.
    When a new cluster starts, its seed tie becomes part of the
    economic-event key.
    """
    out_rows: list[dict[str, Any]] = []
    group_cols = ["primary_ident", "action_type", "share_class", "div_ccy"]

    valid = valid.sort_values(
        ["primary_ident", "action_type", "share_class", "div_ccy", "anchor_date", "stable_tie"],
        kind="mergesort",
    ).reset_index(drop=True)

    for keys, g in valid.groupby(group_cols, sort=False):
        ident, action, share, ccy = keys
        g = g.sort_values(["anchor_date", "stable_tie"], kind="mergesort").reset_index(drop=True)

        group_key = _mk_econ_group_key(str(ident), str(action), str(share), str(ccy))
        rows = list(g.itertuples(index=False, name="LinkRow"))

        current_anchor: date | None = None
        current_amt: float | None = None
        current_event_key: str | None = None
        current_seed_tie: str | None = None

        for idx, r in enumerate(rows):
            anchor = r.anchor_date
            amt = _safe_float(r.amt_link)
            row_seed_tie = str(r.stable_tie)

            if idx == 0:
                current_anchor = anchor
                current_amt = amt
                current_seed_tie = row_seed_tie
                current_event_key = _mk_econ_event_key(group_key, anchor, current_seed_tie)
                link_reason = "seed"
            else:
                ok, reason = should_link_events(current_anchor, current_amt, anchor, amt, policy)
                if ok:
                    link_reason = f"linked:{reason}"
                    current_anchor = anchor
                    if amt is not None and amt != 0.0:
                        current_amt = amt
                else:
                    current_anchor = anchor
                    current_amt = amt
                    current_seed_tie = row_seed_tie
                    current_event_key = _mk_econ_event_key(group_key, anchor, current_seed_tie)
                    link_reason = f"new:{reason}"

            out_rows.append(
                {
                    "row_idx_link": int(r.row_idx_link),
                    "economic_event_key": current_event_key,
                    "economic_event_id": make_economic_event_id(current_event_key),
                    "event_link_reason": link_reason,
                }
            )

    return pd.DataFrame(out_rows)


def _finalise_link_output(
    df: pd.DataFrame,
    *,
    linked: pd.DataFrame,
    invalid: pd.Series,
    skip_reason: pd.Series,
    preset_mask: pd.Series,
    preset_econ: pd.Series,
    respect_existing: bool,
    keep_debug_cols: bool,
) -> pd.DataFrame:
    df_out = df.copy()

    if not linked.empty:
        linked_idx = linked.set_index("row_idx_link")
        target_idx = linked_idx.index

        df_out.loc[target_idx, "economic_event_key"] = linked_idx["economic_event_key"].values
        df_out.loc[target_idx, "economic_event_id"] = linked_idx["economic_event_id"].values
        df_out.loc[target_idx, "event_link_reason"] = linked_idx["event_link_reason"].values

    if respect_existing and preset_mask.any():
        df_out.loc[preset_mask, "economic_event_id"] = preset_econ.loc[preset_mask].astype("string")
        df_out.loc[preset_mask, "event_link_reason"] = "preset"

    if invalid.any():
        df_out.loc[invalid, "economic_event_id"] = ""
        df_out.loc[invalid, "event_link_reason"] = skip_reason.loc[invalid].astype("string")

    df_out = _normalise_event_link_reason_seeded(df_out)

    if respect_existing and preset_mask.any():
        # Re-assert preset after seed/linked normalisation.
        df_out.loc[preset_mask, "economic_event_id"] = preset_econ.loc[preset_mask].astype("string")
        df_out.loc[preset_mask, "event_link_reason"] = "preset"

    df_out = df_out.sort_values("row_idx_link", kind="mergesort").reset_index(drop=True)

    drop_cols = ["row_idx_link", "amt_link", "stable_tie"]
    if not keep_debug_cols:
        drop_cols.append("debug_tie_raw")

    return df_out.drop(columns=drop_cols, errors="ignore")


def assign_economic_events(
    divs: pd.DataFrame,
    policy: LinkPolicy | None = None,
    *,
    respect_existing: bool = False,
    keep_debug_cols: bool = False,
) -> pd.DataFrame:
    if policy is None:
        policy = LinkPolicy()

    if divs is None or divs.empty:
        return pd.DataFrame()

    df, invalid, preset_mask, preset_econ, skip_reason = _prepare_linking_frame(
        divs,
        respect_existing=respect_existing,
        policy=policy,
        keep_debug_cols=keep_debug_cols,
    )

    _validate_vendor_event_groups(df, policy=policy)
    df = _canonicalise_by_observation(df, policy=policy)

    df, preset_mask, preset_econ = _apply_existing_economic_ids(
        df,
        preset_mask=preset_mask,
        preset_econ=preset_econ,
        respect_existing=respect_existing,
    )

    linkable = (~invalid) & (~preset_mask)
    valid = df.loc[linkable].copy()

    if valid.empty:
        out = df.sort_values("row_idx_link", kind="mergesort").reset_index(drop=True)
        drop_cols = ["row_idx_link", "amt_link", "stable_tie"]
        if not keep_debug_cols:
            drop_cols.append("debug_tie_raw")
        return out.drop(columns=drop_cols, errors="ignore")

    linked = _link_valid_groups(valid, policy=policy)

    return _finalise_link_output(
        df,
        linked=linked,
        invalid=invalid,
        skip_reason=skip_reason,
        preset_mask=preset_mask,
        preset_econ=preset_econ,
        respect_existing=respect_existing,
        keep_debug_cols=keep_debug_cols,
    )