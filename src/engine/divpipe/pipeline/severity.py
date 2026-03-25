# src/engine/divpipe/pipeline/severity.py

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SeverityPolicy:
    """
    Tier definition (suggested):
      - Tier 0: must review (high risk)
      - Tier 1: review recommended (medium risk)
      - Tier 2: auto-accept (low risk / clean)

    Thresholds are tunable without changing the rule code.
    """
    # Amount variation inside one econ event
    tier0_amount_unique_ge: int = 3          # >=3 distinct amounts -> Tier 0
    tier1_amount_unique_ge: int = 2          # >=2 distinct amounts -> Tier 1

    # Anchor date spread (max-min days) inside one econ event
    tier0_anchor_spread_days_ge: int = 7     # >=7 days spread -> Tier 0
    tier1_anchor_spread_days_ge: int = 3     # >=3 days spread -> Tier 1

    # If there are too many rows per econ event, likely over-merging / noisy vendor
    tier0_row_count_ge: int = 10
    tier1_row_count_ge: int = 5

    # Currency / identity inconsistencies inside econ id (should normally be 1)
    tier0_ccy_unique_gt: int = 1
    tier0_ident_unique_gt: int = 1

    # Missing critical fields (row-level) aggregated to econ-level
    tier0_missing_amount_any: bool = False   # if True: any missing amount -> Tier 0
    tier1_missing_amount_any: bool = True    # if True: any missing amount -> Tier 1

    # --- Split/instalment relaxation (heuristic; div type absent) ---
    # If pay dates split but anchor is stable and amount does not fan out,
    # lower the tier by one step (0->1, 1->2) to reduce QA surface.
    relax_split_enabled: bool = True
    relax_split_pay_date_nunique_ge: int = 2
    relax_split_amount_nunique_le: int = 2
    relax_split_anchor_spread_days_le: int = 0
    relax_split_reduce_tier_by: int = 1

    # --- Brazil detection (used for guardrails + BR relax) ---
    brazil_isin_prefix: str = "BR"
    brazil_div_ccy: str = "BRL"
    brazil_underlying_suffixes: tuple[str, ...] = (".SA",)

    # --- Brazil guardrail (disable split relaxation) ---
    relax_disable_for_brazil: bool = True

    # --- Brazil Tier1 relax (reduce QA surface, Tier0 unchanged) ---
    relax_br_tier1_enabled: bool = True
    relax_br_tier1_amount_unique_ge: int = 3      # default 2 -> 3 for BR
    relax_br_tier1_anchor_spread_days_ge: int = 7 # default 3 -> 7 for BR
    relax_br_tier1_row_count_ge: int = 8          # default 5 -> 8 for BR
    relax_br_tag_reason: bool = True              # add br_relaxed_tier1 to reasons


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"[severity] missing required columns: {missing}")


def _to_date(s: pd.Series) -> pd.Series:
    # Accepts date/datetime/strings; returns datetime64[ns] with NaT for invalid
    return pd.to_datetime(s, errors="coerce")


def _nunique_nonblank(s: pd.Series) -> int:
    if s is None:
        return 0
    ss = s.astype("string").fillna("").str.strip()
    ss = ss[ss.ne("")]
    return int(ss.nunique(dropna=True))


def _has_any_missing_numeric(s: pd.Series) -> bool:
    x = pd.to_numeric(s, errors="coerce")
    return bool(x.isna().any())


def _amount_nunique(s: pd.Series) -> int:
    x = pd.to_numeric(s, errors="coerce")
    # Treat NaN as missing; nunique(dropna=True) ignores NaN
    return int(x.nunique(dropna=True))


def _first_non_empty(s: pd.Series) -> str:
    ss = s.astype("string").fillna("").str.strip()
    ss = ss[ss.ne("")]
    return str(ss.iloc[0]) if len(ss) else ""


def _pay_date_nunique(s: pd.Series) -> int:
    x = pd.to_datetime(s, errors="coerce")
    return int(x.nunique(dropna=True))


def _is_brazil_cluster(
    r: pd.Series,
    *,
    policy: SeverityPolicy,
    isin_col: str = "isin",
    div_ccy_col: str = "div_ccy",
    underlying_col: str = "underlying",
) -> bool:
    isin = str(r.get(isin_col, "")).strip().upper()
    div_ccy = str(r.get(div_ccy_col, "")).strip().upper()
    underlying = str(r.get(underlying_col, "")).strip().upper()

    if isin.startswith(policy.brazil_isin_prefix):
        return True
    if div_ccy == policy.brazil_div_ccy:
        return True
    for suf in policy.brazil_underlying_suffixes:
        if underlying.endswith(str(suf).upper()):
            return True
    return False


def build_econ_severity(
    linked_rows: pd.DataFrame,
    policy: SeverityPolicy | None = None,
    *,
    econ_id_col: str = "economic_event_id",
    anchor_col: str = "anchor_date",
    amount_col: str = "amount",
    ident_col: str = "primary_ident",
    ccy_col: str = "div_ccy",
) -> pd.DataFrame:
    """
    Input: row-level dataframe after assign_economic_events() (must contain econ id + anchor + amount).
    Output: econ-level summary with severity_tier (0/1/2), reasons, and supporting metrics.

    Assumes:
      - economic_event_id is blank for skipped rows; we exclude blanks from econ aggregation.
    """
    if policy is None:
        policy = SeverityPolicy()

    _ensure_cols(linked_rows, [econ_id_col])

    df = linked_rows.copy()

    # Focus only rows with an assigned econ id
    econ_id = df[econ_id_col].astype("string").fillna("").str.strip()
    df = df.loc[econ_id.ne("")].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                econ_id_col,
                "severity_tier",
                "severity_reasons",
                "row_count",
                "amount_nunique",
                "anchor_min",
                "anchor_max",
                "anchor_spread_days",
                "pay_date_nunique",
                "ccy_nunique",
                "ident_nunique",
                "missing_amount_any",
                "underlying",
                "isin",
                "div_ccy",
                "underlying_ccy",
            ]
        )

    # Compute anchor spread
    if anchor_col in df.columns:
        anchor_dt = _to_date(df[anchor_col])
    else:
        anchor_dt = pd.Series([pd.NaT] * len(df), index=df.index)
    df["_anchor_dt"] = anchor_dt

    # Group-level aggregations
    g = df.groupby(econ_id_col, sort=False)

    out = pd.DataFrame(
        {
            econ_id_col: g.size().index.astype("string"),
            "row_count": g.size().values,
        }
    ).set_index(econ_id_col)

    # Amount diversity
    if amount_col in df.columns:
        out["amount_nunique"] = g[amount_col].apply(_amount_nunique).astype("int64")
        out["missing_amount_any"] = g[amount_col].apply(_has_any_missing_numeric)
    else:
        out["amount_nunique"] = 0
        out["missing_amount_any"] = False

    # Anchor min/max/spread
    out["anchor_min"] = g["_anchor_dt"].min()
    out["anchor_max"] = g["_anchor_dt"].max()
    out["anchor_spread_days"] = (
        (out["anchor_max"] - out["anchor_min"]).dt.days.fillna(0).astype("int64")
    )

    # Pay date diversity (used by split/instalment heuristic)
    if "pay_date" in df.columns:
        out["pay_date_nunique"] = g["pay_date"].apply(_pay_date_nunique).astype("int64")
    else:
        out["pay_date_nunique"] = 0

    # Carry-through identifiers (first non-empty) for downstream heuristics / guardrails
    for _col in ["underlying", "isin", "div_ccy", "underlying_ccy"]:
        if _col in df.columns:
            out[_col] = g[_col].apply(_first_non_empty).astype("string")
        else:
            out[_col] = ""

    # Invariants
    if ccy_col in df.columns:
        out["ccy_nunique"] = g[ccy_col].apply(_nunique_nonblank).astype("int64")
    else:
        out["ccy_nunique"] = 0

    if ident_col in df.columns:
        out["ident_nunique"] = g[ident_col].apply(_nunique_nonblank).astype("int64")
    else:
        out["ident_nunique"] = 0

    # Tier + reasons
    def _tier_and_reasons(r: pd.Series) -> tuple[int, str]:
        reasons: list[str] = []
        tier = 2

        is_br = _is_brazil_cluster(r, policy=policy)

        # ----- Effective Tier1 thresholds (BR relax applies ONLY to Tier1)
        tier1_amount_ge = policy.tier1_amount_unique_ge
        tier1_anchor_ge = policy.tier1_anchor_spread_days_ge
        tier1_row_ge = policy.tier1_row_count_ge

        if is_br and policy.relax_br_tier1_enabled:
            tier1_amount_ge = int(policy.relax_br_tier1_amount_unique_ge)
            tier1_anchor_ge = int(policy.relax_br_tier1_anchor_spread_days_ge)
            tier1_row_ge = int(policy.relax_br_tier1_row_count_ge)

        # Hard invariants -> tier 0
        if int(r.get("ccy_nunique", 0)) > policy.tier0_ccy_unique_gt:
            tier = 0
            reasons.append(f"ccy_nunique={int(r['ccy_nunique'])}>1")
        if int(r.get("ident_nunique", 0)) > policy.tier0_ident_unique_gt:
            tier = 0
            reasons.append(f"ident_nunique={int(r['ident_nunique'])}>1")

        # Amount variation
        amt_nu = int(r.get("amount_nunique", 0))
        if amt_nu >= policy.tier0_amount_unique_ge:
            tier = min(tier, 0)
            reasons.append(f"amount_nunique={amt_nu}>=tier0")
        elif amt_nu >= tier1_amount_ge:
            tier = min(tier, 1)
            reasons.append(f"amount_nunique={amt_nu}>=tier1")

        # Anchor spread
        spr = int(r.get("anchor_spread_days", 0))
        if spr >= policy.tier0_anchor_spread_days_ge:
            tier = min(tier, 0)
            reasons.append(f"anchor_spread_days={spr}>=tier0")
        elif spr >= tier1_anchor_ge:
            tier = min(tier, 1)
            reasons.append(f"anchor_spread_days={spr}>=tier1")

        # Row count (over-merge / noisy)
        rc = int(r.get("row_count", 0))
        if rc >= policy.tier0_row_count_ge:
            tier = min(tier, 0)
            reasons.append(f"row_count={rc}>=tier0")
        elif rc >= tier1_row_ge:
            tier = min(tier, 1)
            reasons.append(f"row_count={rc}>=tier1")

        # Missing amount
        if bool(r.get("missing_amount_any", False)) and policy.tier0_missing_amount_any:
            tier = min(tier, 0)
            reasons.append("missing_amount_any")
        elif bool(r.get("missing_amount_any", False)) and policy.tier1_missing_amount_any:
            tier = min(tier, 1)
            reasons.append("missing_amount_any")

        # Tag: BR relax was in force and would have triggered Tier1 under default policy
        if is_br and policy.relax_br_tier1_enabled and policy.relax_br_tag_reason:
            default_tier1_hit = (
                (amt_nu >= policy.tier1_amount_unique_ge and amt_nu < policy.tier0_amount_unique_ge)
                or (spr >= policy.tier1_anchor_spread_days_ge and spr < policy.tier0_anchor_spread_days_ge)
                or (rc >= policy.tier1_row_count_ge and rc < policy.tier0_row_count_ge)
            )
            br_relaxed_now = (tier == 2) and default_tier1_hit
            if br_relaxed_now:
                reasons.append("br_relaxed_tier1")

        # Split/instalment relaxation (heuristic; non-Brazil only if guardrail enabled)
        if policy.relax_split_enabled and tier in (0, 1):
            if not (policy.relax_disable_for_brazil and is_br):
                pay_nu = int(r.get("pay_date_nunique", 0))
                relax_ok = (
                    (pay_nu >= policy.relax_split_pay_date_nunique_ge)
                    and (amt_nu <= policy.relax_split_amount_nunique_le)
                    and (spr <= policy.relax_split_anchor_spread_days_le)
                )
                if relax_ok:
                    tier = min(2, tier + policy.relax_split_reduce_tier_by)
                    reasons.append("relax_split_paydate")

        if not reasons:
            reasons = ["clean"]

        return tier, "|".join(reasons)

    tmp = out.apply(lambda r: _tier_and_reasons(r), axis=1, result_type="expand")
    out["severity_tier"] = tmp[0].astype("int64")
    out["severity_reasons"] = tmp[1].astype("string")

    out = out.reset_index()

    # Stable ordering: worst first
    out = out.sort_values(
        ["severity_tier", "row_count", "amount_nunique", "anchor_spread_days", econ_id_col],
        ascending=[True, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)

    return out[
        [
            econ_id_col,
            "severity_tier",
            "severity_reasons",
            "row_count",
            "amount_nunique",
            "missing_amount_any",
            "anchor_min",
            "anchor_max",
            "anchor_spread_days",
            "pay_date_nunique",
            "ccy_nunique",
            "ident_nunique",
            "underlying",
            "isin",
            "div_ccy",
            "underlying_ccy",
        ]
    ]


def attach_severity_tier(
    linked_rows: pd.DataFrame,
    econ_summary: pd.DataFrame,
    *,
    econ_id_col: str = "economic_event_id",
) -> pd.DataFrame:
    """
    Add econ-level severity_tier + severity_reasons back to each row.
    Rows with blank econ id stay blank tier/reason.
    """
    df = linked_rows.copy()
    if econ_summary is None or econ_summary.empty:
        df["severity_tier"] = pd.NA
        df["severity_reasons"] = pd.NA
        return df

    m = econ_summary[[econ_id_col, "severity_tier", "severity_reasons"]].copy()
    df = df.merge(m, on=econ_id_col, how="left")
    return df