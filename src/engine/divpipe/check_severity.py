# src/engine/divpipe/check_severity.py

from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from .paths import RunPaths
from .pipeline.link_events import assign_economic_events
from .pipeline.overrides import (
    OPT_COLS,
    REQ_COLS,
    apply_qa_decisions,
    load_qa_decisions,
)
from .pipeline.severity import SeverityPolicy, attach_severity_tier, build_econ_severity
from .utils.repo import get_repo_root

logger = logging.getLogger(__name__)


class Stage2GateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Stage2Paths:
    out_rows: Path
    out_econ: Path
    out_qa_econ: Path
    out_qa_rows: Path
    out_fixture_dbg: Path
    out_o3_pairs: Path
    out_qa_o3_pairs: Path
    out_qa_o3_econ: Path
    out_rows_br: Path
    out_rows_nonbr: Path
    out_no_div_br: Path
    out_rows_kr: Path
    out_no_div_kr: Path


@dataclass(slots=True)
class Stage2ComputedOutputs:
    econ: pd.DataFrame
    qa_econ: pd.DataFrame
    rows2: pd.DataFrame
    pairs_all: pd.DataFrame
    fixture_dbg: pd.DataFrame | None
    rows_br: pd.DataFrame
    rows_nonbr: pd.DataFrame
    rows_kr: pd.DataFrame
    no_div_br: pd.DataFrame | None
    no_div_kr: pd.DataFrame | None


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--run-root", default="", type=str)
    ap.add_argument("--runs-dir", default="", type=str)
    ap.add_argument("--in", dest="in_path", default="", type=str)
    ap.add_argument("--qa-decisions", default="", type=str)
    ap.add_argument("--respect-existing-econ-id", action="store_true")
    ap.add_argument("--no-relax-split", action="store_true")
    ap.add_argument("--relax-split-non-br-only", action="store_true")
    ap.add_argument(
        "--max-tier0-ratio",
        default=None,
        type=float,
        help="Optional Stage 2 guardrail: fail validation if Tier 0 econ ratio exceeds this value (0 to 1).",
    )

    ap.add_argument("--o3-enable", action="store_true")
    ap.add_argument("--o3-ex-shift-days-ge", default=1, type=int)
    ap.add_argument("--o3-pay-shift-days-le", default=1, type=int)
    ap.add_argument("--o3-amount-abs-diff-le", default=0.02, type=float)
    ap.add_argument("--o3-require-same-ccy", action="store_true")
    ap.add_argument("--o3-decisions", default="", type=str)
    ap.add_argument("--o3-suppress-reviewed", action="store_true")
    ap.add_argument("--o3-max-ex-shift-window-days", default=30, type=int)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="divpipe severity")
    add_arguments(ap)
    return ap


def register_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "severity",
        help="Stage 2: link events + severity + QA surfaces",
    )
    add_arguments(p)
    p.set_defaults(func=main_logic)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = build_parser()
    return ap.parse_args(list(argv) if argv is not None else None)


def _repo_root() -> Path:
    return get_repo_root(start=Path(__file__), fallback_to_cwd=False)


def pick_latest_run(runs_dir: Path, *, prefix: str = "divpipe__") -> Path:
    if not runs_dir.exists():
        raise FileNotFoundError(f"Runs directory not found: {runs_dir}")
    candidates = [p for p in runs_dir.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {runs_dir} matching {prefix}*")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def resolve_run_root(runs_dir: Path, run_root_arg: str) -> Path:
    if run_root_arg:
        return Path(run_root_arg).expanduser().resolve()

    latest_link = runs_dir / "latest"
    if latest_link.exists():
        return latest_link.resolve()

    return pick_latest_run(runs_dir)


def _stage1_dir(run_root: Path) -> Path:
    return RunPaths(run_root).stage1_dir


def _stage2_dir(run_root: Path) -> Path:
    d = RunPaths(run_root).stage2_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _build_stage2_paths(stage2: Path) -> Stage2Paths:
    return Stage2Paths(
        out_rows=stage2 / "seed_yfinance_dividends_all__linked_severity.csv",
        out_econ=stage2 / "econ_severity_summary.csv",
        out_qa_econ=stage2 / "qa_queue__econ.csv",
        out_qa_rows=stage2 / "qa_queue__rows.csv",
        out_fixture_dbg=stage2 / "fixture_debug__case_tag_severity.csv",
        out_o3_pairs=stage2 / "fixture_debug__o3_within_run_pairs.csv",
        out_qa_o3_pairs=stage2 / "qa_queue__o3_pairs.csv",
        out_qa_o3_econ=stage2 / "qa_queue__o3_econ.csv",
        out_rows_br=stage2 / "rows__brazil.csv",
        out_rows_nonbr=stage2 / "rows__non_brazil.csv",
        out_no_div_br=stage2 / "no_div__brazil.csv",
        out_rows_kr=stage2 / "rows__korea.csv",
        out_no_div_kr=stage2 / "no_div__korea.csv",
    )


def _resolve_input_paths(run_root: Path, in_path_arg: str) -> tuple[Path, Path]:
    stage1 = _stage1_dir(run_root)

    if in_path_arg:
        dividends = Path(in_path_arg).expanduser().resolve()
    else:
        stage1_div = stage1 / "seed_yfinance_dividends_all.csv"
        root_div = run_root / "seed_yfinance_dividends_all.csv"
        dividends = stage1_div if stage1_div.exists() else root_div

    stage1_nd = stage1 / "seed_yfinance_no_dividends_all.csv"
    root_nd = run_root / "seed_yfinance_no_dividends_all.csv"
    no_div = stage1_nd if stage1_nd.exists() else root_nd

    return dividends, no_div


def _build_policy(args: argparse.Namespace) -> SeverityPolicy:
    base_kwargs = dict(
        tier0_amount_unique_ge=3,
        tier1_amount_unique_ge=2,
        tier0_anchor_spread_days_ge=7,
        tier1_anchor_spread_days_ge=3,
        tier0_row_count_ge=10,
        tier1_row_count_ge=5,
    )

    ext_kwargs = dict(
        relax_split_pay_date_nunique_ge=2,
        relax_split_amount_nunique_le=2,
        relax_split_anchor_spread_days_le=0,
        relax_split_reduce_tier_by=1,
        brazil_isin_prefix="BR",
        brazil_div_ccy="BRL",
        brazil_underlying_suffixes=(".SA",),
        relax_disable_for_brazil=True if args.relax_split_non_br_only else False,
    )

    if args.no_relax_split:
        ext_kwargs["relax_split_pay_date_nunique_ge"] = 10**9

    return SeverityPolicy(**base_kwargs, **ext_kwargs)


def _validate_args(args: argparse.Namespace) -> None:
    max_tier0_ratio = getattr(args, "max_tier0_ratio", None)
    if max_tier0_ratio is not None and not 0.0 <= float(max_tier0_ratio) <= 1.0:
        raise ValueError(
            f"--max-tier0-ratio must be between 0 and 1 inclusive; got {max_tier0_ratio}"
        )


def _col_as_str(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="string")
    return df[name].astype("string").fillna("")


def _is_brazil_rows(df: pd.DataFrame) -> pd.Series:
    isin = _col_as_str(df, "isin").str.upper().str.strip()
    div_ccy = _col_as_str(df, "div_ccy").str.upper().str.strip()
    underlying = _col_as_str(df, "underlying").str.upper().str.strip()
    yft = _col_as_str(df, "yfinance_ticker").str.upper().str.strip()

    return (
        isin.str.startswith("BR")
        | div_ccy.eq("BRL")
        | underlying.str.endswith(".SA")
        | yft.str.endswith(".SA")
    )


def _is_korea_rows(df: pd.DataFrame) -> pd.Series:
    isin = _col_as_str(df, "isin").str.upper().str.strip()
    underlying = _col_as_str(df, "underlying").str.upper().str.strip()
    yft = _col_as_str(df, "yfinance_ticker").str.upper().str.strip()

    return (
        isin.str.startswith("KR")
        | yft.str.endswith(".KS")
        | yft.str.endswith(".KQ")
        | underlying.str.endswith(".KS")
        | underlying.str.endswith(".KQ")
    )


def _i(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return default


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _to_dt(s: pd.Series, *, label: str = "") -> pd.Series:
    out = pd.to_datetime(s, errors="coerce")
    nat_count = int(out.isna().sum())
    if nat_count > 0:
        logger.debug("[date-parse] %s NaT count=%s", label or "<unnamed>", nat_count)
    return out


def _compute_tier0_ratio(econ: pd.DataFrame) -> tuple[int, int, float]:
    if econ is None or econ.empty or "severity_tier" not in econ.columns:
        return 0, 0, 0.0

    total_econ = int(len(econ))
    tier0_count = int(pd.to_numeric(econ["severity_tier"], errors="coerce").fillna(999).eq(0).sum())
    tier0_ratio = (tier0_count / total_econ) if total_econ > 0 else 0.0
    return tier0_count, total_econ, tier0_ratio


def _enforce_stage2_guardrails(*, args: argparse.Namespace, econ: pd.DataFrame) -> None:
    max_tier0_ratio = getattr(args, "max_tier0_ratio", None)
    if max_tier0_ratio is None:
        return

    tier0_count, total_econ, tier0_ratio = _compute_tier0_ratio(econ)

    logger.info(
        "[stage2][guardrail] tier0_count=%s total_econ=%s tier0_ratio=%.12f threshold=%.12f",
        tier0_count,
        total_econ,
        tier0_ratio,
        float(max_tier0_ratio),
    )

    if tier0_ratio > float(max_tier0_ratio):
        raise Stage2GateError(
            "Stage 2 guardrail breached: "
            f"tier0_ratio={tier0_ratio:.12f} > max_tier0_ratio={float(max_tier0_ratio):.12f} "
            f"(tier0_count={tier0_count}, total_econ={total_econ})"
        )


def _explain_tier_triggers(econ_row: pd.Series, policy: SeverityPolicy) -> str:
    reasons_txt = str(econ_row.get("severity_reasons", "")).strip()
    if reasons_txt:
        return reasons_txt

    tier = _i(econ_row.get("severity_tier", 999), default=999)
    amount_nunique = _i(econ_row.get("amount_nunique", 0))
    anchor_spread_days = _f(econ_row.get("anchor_spread_days", 0))
    row_count = _i(econ_row.get("row_count", 0))
    ccy_nunique = _i(econ_row.get("ccy_nunique", econ_row.get("div_ccy_nunique", 0)))
    pay_date_nunique = _i(econ_row.get("pay_date_nunique", 0))

    out: list[str] = []

    if tier == 0:
        if amount_nunique >= getattr(policy, "tier0_amount_unique_ge", 10**9):
            out.append(f"amount_nunique({amount_nunique}) >= tier0_amount_unique_ge({policy.tier0_amount_unique_ge})")
        if anchor_spread_days >= getattr(policy, "tier0_anchor_spread_days_ge", 10**9):
            out.append(
                f"anchor_spread_days({anchor_spread_days:g}) >= tier0_anchor_spread_days_ge({policy.tier0_anchor_spread_days_ge})"
            )
        if row_count >= getattr(policy, "tier0_row_count_ge", 10**9):
            out.append(f"row_count({row_count}) >= tier0_row_count_ge({policy.tier0_row_count_ge})")
        if ccy_nunique >= 2:
            out.append(f"ccy_nunique({ccy_nunique}) >= 2")
        if pay_date_nunique >= 2:
            out.append(f"pay_date_nunique({pay_date_nunique}) >= 2")

    elif tier == 1:
        if amount_nunique >= getattr(policy, "tier1_amount_unique_ge", 10**9):
            out.append(f"amount_nunique({amount_nunique}) >= tier1_amount_unique_ge({policy.tier1_amount_unique_ge})")
        if anchor_spread_days >= getattr(policy, "tier1_anchor_spread_days_ge", 10**9):
            out.append(
                f"anchor_spread_days({anchor_spread_days:g}) >= tier1_anchor_spread_days_ge({policy.tier1_anchor_spread_days_ge})"
            )
        if row_count >= getattr(policy, "tier1_row_count_ge", 10**9):
            out.append(f"row_count({row_count}) >= tier1_row_count_ge({policy.tier1_row_count_ge})")
        if ccy_nunique >= 2:
            out.append(f"ccy_nunique({ccy_nunique}) >= 2")
        if pay_date_nunique >= 2:
            out.append(f"pay_date_nunique({pay_date_nunique}) >= 2")

    return " | ".join(out)


def _not_flagged_summary(econ_row: pd.Series, policy: SeverityPolicy) -> str:
    tier = _i(econ_row.get("severity_tier", 999), default=999)
    if tier in (0, 1):
        return ""

    reasons_txt = str(econ_row.get("severity_reasons", "")).strip().lower()
    relaxed = "relax" in reasons_txt

    amount_nunique = _i(econ_row.get("amount_nunique", 0))
    anchor_spread_days = _f(econ_row.get("anchor_spread_days", 0))
    row_count = _i(econ_row.get("row_count", 0))
    ccy_nunique = _i(econ_row.get("ccy_nunique", econ_row.get("div_ccy_nunique", 0)))

    met: list[str] = []
    below: list[str] = []

    t1_amt = getattr(policy, "tier1_amount_unique_ge", 10**9)
    t1_anch = getattr(policy, "tier1_anchor_spread_days_ge", 10**9)
    t1_rows = getattr(policy, "tier1_row_count_ge", 10**9)

    if amount_nunique >= t1_amt:
        met.append("amount_nunique")
    else:
        below.append("amount_nunique")

    if anchor_spread_days >= t1_anch:
        met.append("anchor_spread_days")
    else:
        below.append("anchor_spread_days")

    if row_count >= t1_rows:
        met.append("row_count")
    else:
        below.append("row_count")

    if ccy_nunique >= 2:
        met.append("currency_mixture")
    else:
        below.append("currency_mixture")

    if relaxed:
        met_txt = ", ".join(met) if met else "no tier-1 triggers"
        return f"Not flagged: relaxed by split rule; underlying triggers were {met_txt}."

    below_txt = ", ".join(below) if below else "none"
    return f"Not flagged: below tier-1 on {below_txt}."


def _build_o3_pairs(
    rows2: pd.DataFrame,
    *,
    max_pairs: int = 5000,
    max_ex_shift_days: int = 30,
) -> pd.DataFrame:
    need = ["case_tag", "underlying", "ex_date", "pay_date", "amount", "div_ccy", "economic_event_id", "vendor_event_id"]
    miss = [c for c in need if c not in rows2.columns]
    if miss:
        return pd.DataFrame()

    df = rows2.copy()
    df["ex_dt"] = _to_dt(df["ex_date"], label="ex_date")
    df["pay_dt"] = _to_dt(df["pay_date"], label="pay_date")
    df["div_ccy_u"] = df["div_ccy"].astype("string").fillna("").str.upper().str.strip()

    df = df[df["case_tag"].astype(str).str.startswith("O3")].copy()
    if df.empty:
        return pd.DataFrame()

    out_rows: list[dict] = []

    for underlying, g in df.groupby("underlying", sort=True):
        g = g.sort_values(["ex_dt", "pay_dt", "amount"], kind="mergesort").reset_index(drop=True)
        n = len(g)
        if n < 2:
            continue

        for i in range(n):
            a = g.loc[i]
            if pd.isna(a["ex_dt"]):
                continue

            for j in range(i + 1, n):
                b = g.loc[j]
                if pd.isna(b["ex_dt"]):
                    continue

                ex_shift = _i((b["ex_dt"] - a["ex_dt"]).days)
                if ex_shift < 0:
                    raise ValueError(
                        f"O3 ex-date ordering invariant breached for underlying={underlying}: "
                        f"ex_date_a={a['ex_date']} ex_date_b={b['ex_date']}"
                    )

                if ex_shift > max_ex_shift_days:
                    break

                pay_shift = ""
                if pd.notna(a["pay_dt"]) and pd.notna(b["pay_dt"]):
                    pay_shift = _i(abs((a["pay_dt"] - b["pay_dt"]).days))

                same_ccy = bool(a["div_ccy_u"] == b["div_ccy_u"])
                amt_diff = _f(abs(_f(a["amount"]) - _f(b["amount"])))

                out_rows.append(
                    {
                        "case_tag_a": a["case_tag"],
                        "case_tag_b": b["case_tag"],
                        "underlying": underlying,
                        "econ_id_a": a["economic_event_id"],
                        "econ_id_b": b["economic_event_id"],
                        "vendor_event_id_a": a["vendor_event_id"],
                        "vendor_event_id_b": b["vendor_event_id"],
                        "ex_date_a": a["ex_date"],
                        "ex_date_b": b["ex_date"],
                        "pay_date_a": a["pay_date"],
                        "pay_date_b": b["pay_date"],
                        "div_ccy": a["div_ccy_u"],
                        "same_ccy": same_ccy,
                        "amount_a": a["amount"],
                        "amount_b": b["amount"],
                        "amount_abs_diff": amt_diff,
                        "ex_date_abs_shift_days": ex_shift,
                        "pay_date_abs_shift_days": pay_shift,
                    }
                )

                if len(out_rows) >= max_pairs:
                    return pd.DataFrame(out_rows)

    return pd.DataFrame(out_rows)


def _filter_o3_pairs_for_qa(pairs: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if pairs.empty:
        return pairs

    df = pairs.copy()

    df["ex_date_abs_shift_days"] = df["ex_date_abs_shift_days"].apply(lambda v: _i(v, default=0))
    df["amount_abs_diff"] = df["amount_abs_diff"].apply(lambda v: _f(v, default=0.0))

    def _pay_shift(v) -> int:
        if v == "" or pd.isna(v):
            return 10**9
        return _i(v, default=10**9)

    df["pay_date_abs_shift_days"] = df["pay_date_abs_shift_days"].apply(_pay_shift)

    mask = (
        (df["ex_date_abs_shift_days"] >= int(args.o3_ex_shift_days_ge))
        & (df["pay_date_abs_shift_days"] <= int(args.o3_pay_shift_days_le))
        & (df["amount_abs_diff"] <= float(args.o3_amount_abs_diff_le))
    )

    if args.o3_require_same_ccy:
        s = df["same_ccy"]
        if s.dtype.name != "boolean":
            s = s.astype("string").str.strip().str.lower()
            df["same_ccy"] = s.isin(["1", "true", "yes", "y"])
        df["same_ccy"] = df["same_ccy"].astype("boolean").fillna(False)
        mask = mask & df["same_ccy"].astype("boolean").fillna(False).eq(True)

    df = df.loc[mask].copy()

    df = df.sort_values(
        ["underlying", "ex_date_abs_shift_days", "amount_abs_diff"],
        ascending=[True, False, True],
        kind="mergesort",
    )

    return df


def _write_csv_template(
    *,
    path: Path,
    header: list[str],
    sample_rows: list[list[str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(sample_rows)


def _qa_decisions_sample_rows() -> list[list[str]]:
    return [
        [
            "VENDOR_EXAMPLE_001",
            "VALE3",
            "2025-12-27",
            "SET_ECON_ID",
            "",
            "",
            "ECON_VALE3_20251227",
            "",
            "Wildcard: assign a single economic_event_id to all rows under this key.",
        ],
        [
            "VENDOR_EXAMPLE_002",
            "PETR4",
            "2025-01-15",
            "DROP",
            "0.10",
            "BRL",
            "",
            "",
            "Exact match: drop only this specific amount+currency row.",
        ],
        [
            "VENDOR_EXAMPLE_003",
            "005930",
            "2025-12-27",
            "SET_ANCHOR_DATE",
            "",
            "",
            "",
            "2025-12-27",
            "Set anchor_date (applies only if rows support anchor_date).",
        ],
    ]


def _o3_decisions_sample_rows() -> list[list[str]]:
    return [
        [
            "true",
            "GHI",
            "eco_demo_f6a6e85551eebfc1",
            "eco_demo_c0026a677adcabff",
            "KEEP",
            "",
            "Reviewed: keep as distinct economic events; suppress future alerts for this pair.",
        ],
        [
            "true",
            "GHJ",
            "eco_demo_ca899c37938f214d",
            "eco_demo_6d4ffea513079eb9",
            "MERGE",
            "",
            "Reviewed: treat as same economic event; merge econ_id_b into econ_id_a.",
        ],
    ]


def _ensure_decision_file_or_create_template(
    *,
    path_arg: str,
    header: list[str],
    sample_rows: list[list[str]],
    label: str,
) -> Path | None:
    if not path_arg:
        return None

    path = Path(path_arg).expanduser().resolve()
    if path.exists():
        return path

    _write_csv_template(path=path, header=header, sample_rows=sample_rows)
    logger.info("%s template created: %s", label, path)
    logger.info("Populate it and re-run.")
    return None


def _read_o3_decisions(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype="string").fillna("")
    for c in ["enabled", "underlying", "econ_id_a", "econ_id_b", "decision", "canonical_econ_id", "note"]:
        if c not in df.columns:
            df[c] = ""

    df["enabled"] = df["enabled"].astype("string").str.strip().str.lower()
    df = df[df["enabled"].isin(["1", "true", "yes"])].copy()

    df["underlying"] = df["underlying"].astype("string").str.strip()
    df["econ_id_a"] = df["econ_id_a"].astype("string").str.strip()
    df["econ_id_b"] = df["econ_id_b"].astype("string").str.strip()
    df["decision"] = df["decision"].astype("string").str.strip().str.upper()
    df["canonical_econ_id"] = df["canonical_econ_id"].astype("string").str.strip()

    df = df[df["decision"].isin(["KEEP", "MERGE"])].copy()
    df = df[(df["econ_id_a"] != "") & (df["econ_id_b"] != "")].copy()

    return df


def _load_main_qa_decisions_if_any(qa_decisions_arg: str) -> tuple[pd.DataFrame, bool]:
    if not qa_decisions_arg:
        return pd.DataFrame(), False

    qa_path = _ensure_decision_file_or_create_template(
        path_arg=qa_decisions_arg,
        header=REQ_COLS + OPT_COLS,
        sample_rows=_qa_decisions_sample_rows(),
        label="QA decisions",
    )
    if qa_path is None:
        return pd.DataFrame(), True

    decisions = load_qa_decisions(qa_path)
    if "enabled" in decisions.columns:
        decisions = decisions[decisions["enabled"].astype(str).str.lower().isin(["1", "true", "yes"])]

    return decisions, False


def _apply_main_qa_decisions_if_any(rows: pd.DataFrame, qa_decisions_arg: str) -> tuple[pd.DataFrame, bool]:
    decisions, should_exit = _load_main_qa_decisions_if_any(qa_decisions_arg)
    if should_exit:
        return pd.DataFrame(), True
    if decisions.empty:
        return rows, False
    return apply_qa_decisions(rows, decisions), False


def _load_o3_decisions_if_any(o3_decisions_arg: str) -> tuple[pd.DataFrame, bool]:
    if not o3_decisions_arg:
        return pd.DataFrame(), False

    o3_path = _ensure_decision_file_or_create_template(
        path_arg=o3_decisions_arg,
        header=[
            "enabled",
            "underlying",
            "econ_id_a",
            "econ_id_b",
            "decision",
            "canonical_econ_id",
            "note",
        ],
        sample_rows=_o3_decisions_sample_rows(),
        label="O3 decisions",
    )
    if o3_path is None:
        return pd.DataFrame(), True

    return _read_o3_decisions(o3_path), False


def _o3_pair_key(econ_id_a: str, econ_id_b: str) -> str:
    a = str(econ_id_a).strip()
    b = str(econ_id_b).strip()
    if a <= b:
        return f"{a}||{b}"
    return f"{b}||{a}"


def _apply_o3_suppression(qa_pairs: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    if qa_pairs.empty or decisions.empty:
        return qa_pairs

    keep = decisions[decisions["decision"].eq("KEEP")].copy()
    if keep.empty:
        return qa_pairs

    keep["pair_key"] = keep.apply(lambda r: _o3_pair_key(r["econ_id_a"], r["econ_id_b"]), axis=1)

    df = qa_pairs.copy()
    df["pair_key"] = df.apply(lambda r: _o3_pair_key(r.get("econ_id_a", ""), r.get("econ_id_b", "")), axis=1)

    reviewed = set(keep["pair_key"].tolist())
    df = df[~df["pair_key"].isin(reviewed)].copy()

    return df.drop(columns=["pair_key"], errors="ignore")


def _build_o3_merge_map(decisions: pd.DataFrame) -> dict[str, str]:
    if decisions.empty:
        return {}

    merge = decisions[decisions["decision"].eq("MERGE")].copy()
    if merge.empty:
        return {}

    mapping: dict[str, str] = {}
    for _, r in merge.iterrows():
        a = str(r["econ_id_a"]).strip()
        b = str(r["econ_id_b"]).strip()
        canon = str(r["canonical_econ_id"]).strip() or a
        if a and b and canon:
            mapping[b] = canon

    max_passes = max(1, len(mapping) + 1)

    for _ in range(max_passes):
        changed = False
        for k, v in list(mapping.items()):
            vv = mapping.get(v, v)
            if vv != v:
                mapping[k] = vv
                changed = True
        if not changed:
            return mapping

    raise ValueError("O3 merge decisions contain a cycle or unresolved chain.")


def _apply_o3_merges_to_rows(rows: pd.DataFrame, merge_map: dict[str, str]) -> pd.DataFrame:
    if rows.empty or not merge_map:
        return rows

    if "economic_event_id" not in rows.columns:
        return rows

    out = rows.copy()
    out.loc[:, "economic_event_id"] = (
        out["economic_event_id"].astype("string").fillna("").map(lambda x: merge_map.get(x, x))
    )
    return out


def _build_econ_outputs(
    *,
    rows: pd.DataFrame,
    policy: SeverityPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    econ = build_econ_severity(rows, policy)
    econ["not_flagged_summary"] = econ.apply(lambda r: _not_flagged_summary(r, policy), axis=1)

    qa_econ = (
        econ[econ["severity_tier"].isin([0, 1])]
        .copy()
        .sort_values(["severity_tier", "row_count"], ascending=[True, False], kind="mergesort")
    )

    rows2 = attach_severity_tier(rows, econ)
    return econ, qa_econ, rows2


def _build_fixture_debug_df(
    *,
    rows2: pd.DataFrame,
    econ: pd.DataFrame,
    policy: SeverityPolicy,
) -> pd.DataFrame | None:
    if "case_tag" not in rows2.columns:
        logger.info("[fixture] case_tag not found; skipping fixture debug summary")
        return None

    m = rows2[["case_tag", "economic_event_id"]].dropna().drop_duplicates()

    want_cols = [
        "economic_event_id",
        "severity_tier",
        "row_count",
        "amount_nunique",
        "pay_date_nunique",
        "ccy_nunique",
        "anchor_spread_days",
        "severity_reasons",
        "not_flagged_summary",
    ]
    econ_cols = [c for c in want_cols if c in econ.columns]
    econ_view = econ[econ_cols].copy()

    dbg = m.merge(econ_view, on="economic_event_id", how="left")
    dbg["tier_triggers"] = dbg.apply(lambda r: _explain_tier_triggers(r, policy), axis=1)

    sort_cols = [c for c in ["case_tag", "severity_tier", "row_count"] if c in dbg.columns]
    if sort_cols:
        ascending = [False if c == "row_count" else True for c in sort_cols]
        dbg = dbg.sort_values(sort_cols, ascending=ascending, kind="mergesort")

    return dbg


def _build_region_split_frames(rows2: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    br_mask = _is_brazil_rows(rows2)
    kr_mask = _is_korea_rows(rows2)

    rows_br = rows2.loc[br_mask].copy()
    rows_nonbr = rows2.loc[~br_mask].copy()
    rows_kr = rows2.loc[kr_mask].copy()

    return rows_br, rows_nonbr, rows_kr


def _build_no_div_split_frames(no_div_all_path: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    if not no_div_all_path.exists():
        logger.warning("[extra] no-div input not found; skipping no_div splits")
        return None, None

    nd = pd.read_csv(no_div_all_path)
    nd_br = nd[_is_brazil_rows(nd)].copy()
    nd_kr = nd[_is_korea_rows(nd)].copy()

    logger.info("[extra] no_div__brazil rows=%s", len(nd_br))
    logger.info("[extra] no_div__korea rows=%s", len(nd_kr))
    return nd_br, nd_kr


def _build_outputs(
    *,
    policy: SeverityPolicy,
    rows: pd.DataFrame,
    no_div_all_path: Path,
    o3_max_ex_shift_window_days: int,
) -> Stage2ComputedOutputs:
    econ, qa_econ, rows2 = _build_econ_outputs(
        rows=rows,
        policy=policy,
    )

    fixture_dbg = _build_fixture_debug_df(
        rows2=rows2,
        econ=econ,
        policy=policy,
    )

    rows_br, rows_nonbr, rows_kr = _build_region_split_frames(rows2)
    no_div_br, no_div_kr = _build_no_div_split_frames(no_div_all_path)

    pairs_all = _build_o3_pairs(
        rows2,
        max_ex_shift_days=o3_max_ex_shift_window_days,
    )

    return Stage2ComputedOutputs(
        econ=econ,
        qa_econ=qa_econ,
        rows2=rows2,
        pairs_all=pairs_all,
        fixture_dbg=fixture_dbg,
        rows_br=rows_br,
        rows_nonbr=rows_nonbr,
        rows_kr=rows_kr,
        no_div_br=no_div_br,
        no_div_kr=no_div_kr,
    )


def _build_qa_rows(outputs: Stage2ComputedOutputs) -> pd.DataFrame:
    if outputs.rows2.empty or outputs.qa_econ.empty:
        return pd.DataFrame(columns=list(outputs.rows2.columns))

    return outputs.rows2[outputs.rows2["economic_event_id"].isin(outputs.qa_econ["economic_event_id"])].copy()


def _persist_outputs(
    *,
    outputs: Stage2ComputedOutputs,
    paths: Stage2Paths,
) -> None:
    outputs.econ.to_csv(paths.out_econ, index=False, encoding="utf-8-sig")
    outputs.qa_econ.to_csv(paths.out_qa_econ, index=False, encoding="utf-8-sig")
    outputs.rows2.to_csv(paths.out_rows, index=False, encoding="utf-8-sig")

    qa_rows = _build_qa_rows(outputs)
    qa_rows.to_csv(paths.out_qa_rows, index=False, encoding="utf-8-sig")

    if outputs.fixture_dbg is not None:
        outputs.fixture_dbg.to_csv(paths.out_fixture_dbg, index=False, encoding="utf-8-sig")
        logger.info("[fixture] wrote: %s", paths.out_fixture_dbg)

        view_cols = [
            "case_tag",
            "economic_event_id",
            "severity_tier",
            "row_count",
            "amount_nunique",
            "pay_date_nunique",
            "ccy_nunique",
            "anchor_spread_days",
            "tier_triggers",
            "not_flagged_summary",
        ]
        view_cols = [c for c in view_cols if c in outputs.fixture_dbg.columns]
        logger.debug("\n%s", outputs.fixture_dbg[view_cols].head(50).to_string(index=False))

    if not outputs.pairs_all.empty:
        outputs.pairs_all.to_csv(paths.out_o3_pairs, index=False, encoding="utf-8-sig")
        logger.info("[fixture] wrote: %s", paths.out_o3_pairs)
    else:
        logger.info("[fixture] no O3 pairs detected")

    outputs.rows_br.to_csv(paths.out_rows_br, index=False, encoding="utf-8-sig")
    outputs.rows_nonbr.to_csv(paths.out_rows_nonbr, index=False, encoding="utf-8-sig")
    outputs.rows_kr.to_csv(paths.out_rows_kr, index=False, encoding="utf-8-sig")

    if outputs.no_div_br is not None:
        outputs.no_div_br.to_csv(paths.out_no_div_br, index=False, encoding="utf-8-sig")
    if outputs.no_div_kr is not None:
        outputs.no_div_kr.to_csv(paths.out_no_div_kr, index=False, encoding="utf-8-sig")


def _build_o3_econ_view(econ: pd.DataFrame, qa_pairs: pd.DataFrame) -> pd.DataFrame:
    if qa_pairs.empty:
        return pd.DataFrame(columns=["economic_event_id"])

    econ_ids = pd.unique(pd.concat([qa_pairs["econ_id_a"], qa_pairs["econ_id_b"]], ignore_index=True))
    econ_ids = [e for e in econ_ids if isinstance(e, str) and e.strip()]

    econ_view_cols = [
        c
        for c in [
            "economic_event_id",
            "underlying",
            "severity_tier",
            "row_count",
            "amount_nunique",
            "pay_date_nunique",
            "ccy_nunique",
            "anchor_spread_days",
        ]
        if c in econ.columns
    ]
    econ_view = econ.loc[econ["economic_event_id"].isin(econ_ids), econ_view_cols].copy()
    return econ_view.sort_values(["severity_tier", "row_count"], ascending=[True, False], kind="mergesort")


def _persist_o3_outputs(
    *,
    qa_pairs: pd.DataFrame | None,
    qa_o3_econ: pd.DataFrame | None,
    paths: Stage2Paths,
    o3_enabled: bool,
) -> None:
    if not o3_enabled:
        return

    if qa_pairs is None:
        qa_pairs = pd.DataFrame()
    if qa_o3_econ is None:
        qa_o3_econ = pd.DataFrame(columns=["economic_event_id"])

    qa_pairs.to_csv(paths.out_qa_o3_pairs, index=False, encoding="utf-8-sig")
    logger.info("[qa] wrote: %s rows=%s", paths.out_qa_o3_pairs, len(qa_pairs))

    qa_o3_econ.to_csv(paths.out_qa_o3_econ, index=False, encoding="utf-8-sig")
    logger.info("[qa] wrote: %s rows=%s", paths.out_qa_o3_econ, len(qa_o3_econ))


def _log_run_context(
    *,
    root: Path,
    runs_dir: Path,
    run_root: Path,
    stage1: Path,
    stage2: Path,
    dividends_all_path: Path,
    no_div_all_path: Path,
) -> None:
    latest_link = runs_dir / "latest"
    latest_target = latest_link.resolve() if latest_link.exists() else "(missing)"

    logger.info("_repo_root: %s", root)
    logger.info("runs_dir : %s", runs_dir)
    logger.info("run_root : %s", run_root)
    logger.info("stage1   : %s %s", stage1, "(present)" if stage1.exists() else "(missing)")
    logger.info("stage2   : %s", stage2)
    logger.info("input(dividends_all): %s", dividends_all_path)
    logger.info("input(no_div_all)   : %s", no_div_all_path)
    logger.info("latest_link  : %s", latest_link)
    logger.info("latest_target: %s", latest_target)


def _load_stage2_input_df(dividends_all_path: Path) -> pd.DataFrame:
    if not dividends_all_path.exists():
        raise FileNotFoundError(
            "Input CSV not found.\n"
            f"  tried: {dividends_all_path}\n"
            f"  run_root: {dividends_all_path.parent.parent}\n"
            "Hint: run stage1 for this run_root, or pass --in explicitly."
        )

    df = pd.read_csv(dividends_all_path)

    if "amount" in df.columns:
        logger.info("[stage2] df amount dtype after read: %s", df["amount"].dtype)
        logger.debug("%s", df["amount"].head())
    else:
        logger.info("[stage2] df missing amount column")

    return df


def _apply_o3_workflow_if_any(
    *,
    args: argparse.Namespace,
    rows: pd.DataFrame,
    outputs: Stage2ComputedOutputs,
    policy: SeverityPolicy,
    no_div_all_path: Path,
) -> tuple[Stage2ComputedOutputs, pd.DataFrame | None, pd.DataFrame | None, bool]:
    if not args.o3_enable:
        return outputs, None, None, False

    if outputs.pairs_all.empty:
        logger.warning("[qa] o3 enabled but no pairs found; skipping o3 QA outputs")
        return outputs, pd.DataFrame(), pd.DataFrame(columns=["economic_event_id"]), False

    qa_pairs = _filter_o3_pairs_for_qa(outputs.pairs_all, args)

    decisions_df, should_exit = _load_o3_decisions_if_any(args.o3_decisions)
    if should_exit:
        return outputs, None, None, True

    if args.o3_suppress_reviewed and not decisions_df.empty:
        qa_pairs = _apply_o3_suppression(qa_pairs, decisions_df)

    qa_o3_econ = _build_o3_econ_view(outputs.econ, qa_pairs)

    if decisions_df.empty:
        return outputs, qa_pairs, qa_o3_econ, False

    merge_map = _build_o3_merge_map(decisions_df)
    if not merge_map:
        return outputs, qa_pairs, qa_o3_econ, False

    rows_merged = _apply_o3_merges_to_rows(rows, merge_map)
    merged_outputs = _build_outputs(
        policy=policy,
        rows=rows_merged,
        no_div_all_path=no_div_all_path,
        o3_max_ex_shift_window_days=int(args.o3_max_ex_shift_window_days),
    )
    merged_qa_o3_econ = _build_o3_econ_view(merged_outputs.econ, qa_pairs)

    logger.info("[qa] applied O3 MERGE decisions and recomputed Stage 2 outputs in memory")
    return merged_outputs, qa_pairs, merged_qa_o3_econ, False


def _log_saved_outputs(
    *,
    base_paths: list[Path],
    o3_paths: list[Path] | None = None,
    o3_enabled: bool = False,
) -> None:
    logger.info("saved outputs:")
    for path in base_paths:
        logger.info(" - %s", path)

    if o3_enabled and o3_paths:
        logger.info("saved O3 outputs:")
        for path in o3_paths:
            logger.info(" - %s", path)


def main_logic(args: argparse.Namespace) -> None:
    _validate_args(args)

    root = _repo_root()
    runs_dir = Path(args.runs_dir).expanduser().resolve() if args.runs_dir else (root / "output" / "runs")
    run_root = resolve_run_root(runs_dir, args.run_root)

    stage1 = _stage1_dir(run_root)
    stage2 = _stage2_dir(run_root)
    paths = _build_stage2_paths(stage2)

    dividends_all_path, no_div_all_path = _resolve_input_paths(run_root, args.in_path)

    _log_run_context(
        root=root,
        runs_dir=runs_dir,
        run_root=run_root,
        stage1=stage1,
        stage2=stage2,
        dividends_all_path=dividends_all_path,
        no_div_all_path=no_div_all_path,
    )

    df = _load_stage2_input_df(dividends_all_path)
    rows = assign_economic_events(df.copy(), respect_existing=args.respect_existing_econ_id)

    if "amount" in rows.columns:
        logger.info("[stage2] rows amount dtype after econ_id: %s", rows["amount"].dtype)
        logger.debug("%s", rows["amount"].head())
    else:
        logger.info("[stage2] rows missing amount column")

    rows_after_decisions, should_exit = _apply_main_qa_decisions_if_any(rows, args.qa_decisions)
    if should_exit:
        return
    rows = rows_after_decisions

    policy = _build_policy(args)

    outputs = _build_outputs(
        policy=policy,
        rows=rows,
        no_div_all_path=no_div_all_path,
        o3_max_ex_shift_window_days=int(args.o3_max_ex_shift_window_days),
    )

    outputs, qa_pairs, qa_o3_econ, should_exit = _apply_o3_workflow_if_any(
        args=args,
        rows=rows,
        outputs=outputs,
        policy=policy,
        no_div_all_path=no_div_all_path,
    )
    if should_exit:
        return

    _enforce_stage2_guardrails(args=args, econ=outputs.econ)

    _persist_outputs(
        outputs=outputs,
        paths=paths,
    )
    _persist_o3_outputs(
        qa_pairs=qa_pairs,
        qa_o3_econ=qa_o3_econ,
        paths=paths,
        o3_enabled=args.o3_enable,
    )

    _log_saved_outputs(
        base_paths=[
            paths.out_rows,
            paths.out_econ,
            paths.out_qa_econ,
            paths.out_qa_rows,
            paths.out_fixture_dbg,
            paths.out_o3_pairs,
            paths.out_rows_br,
            paths.out_rows_nonbr,
            paths.out_no_div_br,
            paths.out_rows_kr,
            paths.out_no_div_kr,
        ],
        o3_paths=[
            paths.out_qa_o3_pairs,
            paths.out_qa_o3_econ,
        ],
        o3_enabled=args.o3_enable,
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    main_logic(args)


if __name__ == "__main__":
    main()