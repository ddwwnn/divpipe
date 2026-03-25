#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/make_overlap_samples.py

"""
Demo-run: build guaranteed O1–O6 overlap-pattern examples using:
- Stage1 seed dividends (e.g. yfinance output)
- Holdings files (EEM/EFA full) to supply ISINs for bucket inference

Why:
- holdings alone do NOT have ex/pay/amount, so cannot form O1–O6.
- demo-run validates: (1) flag logic (2) sampling logic (3) end-to-end artefact format.

Repo "latest" conventions:
- output/runs/latest is a symlink -> newest run directory (created by run_pipeline).
- Seed file may live either:
    (A) <run_dir>/seed_yfinance_dividends_all.csv
    (B) <run_dir>/stage1_seed/seed_yfinance_dividends_all.csv
So this script defines "latest seed" as:
  1) If explicit --seed-divs provided: use it
  2) Else search in order:
      - repo_root/latest/<seed> (optional convention)
      - output/runs/latest/(stage1_seed/)<seed>
      - known fallback locations (_sandbox/_legacy/tests fixtures)
      - finally: scan output/runs/* and pick newest seed that is actually usable

CLI philosophy:
- Defaults are conservative (inject-only=False, pure-only=False).
- For *demo runs*, you typically want --inject-only for determinism + clean debugging.
- Use --pure-only as a strict debugging/verification mode (row-level purity).
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# -------------------------
# Defaults / seed latest resolution
# -------------------------
DEFAULT_SEED_BASENAME = "seed_yfinance_dividends_all.csv"

SEED_REL_CANDIDATES = [
    Path(DEFAULT_SEED_BASENAME),
    Path("stage1_seed") / DEFAULT_SEED_BASENAME,
]

DIRECT_FALLBACKS = [
    Path("output") / "_sandbox" / "yf_run" / DEFAULT_SEED_BASENAME,
    Path("output") / "_legacy" / "divpipe_run__legacy" / DEFAULT_SEED_BASENAME,
    Path("tests") / "fixtures" / DEFAULT_SEED_BASENAME,
]

REPO_LATEST_SEED = Path("latest") / DEFAULT_SEED_BASENAME


def _is_file(p: Path) -> bool:
    return p.exists() and p.is_file()


def _try_seed_in_run_dir(run_dir: Path) -> Optional[Path]:
    """
    Check:
      run_dir/<seed>
      run_dir/stage1_seed/<seed>
    Return first that exists.
    """
    for rel in SEED_REL_CANDIDATES:
        cand = run_dir / rel
        if _is_file(cand):
            return cand.resolve()
    return None


def _load_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported input: {path}")


# -------------------------
# Canonical column names
# -------------------------
REQ_MIN = ["isin", "div_ccy", "ex_date", "amount"]

DATE_COLS = ["declared_date", "ex_date", "record_date", "pay_date"]
STR_COLS = [
    "isin",
    "div_ccy",
    "underlying",
    "div_type",
    "status",
    "vendor_event_id",
    "source",
    "note",
    "source_event_key",
]
NUM_COLS = ["amount"]

DEFAULT_COLMAP = {
    # ISIN
    "ISIN": "isin",
    "Isin": "isin",
    # Dates
    "Ex": "ex_date",
    "Ex Date": "ex_date",
    "ex": "ex_date",
    "Pay": "pay_date",
    "Pay Date": "pay_date",
    "pay": "pay_date",
    "Declaration": "declared_date",
    "Declared": "declared_date",
    "Record": "record_date",
    "Record Date": "record_date",
    # Amount
    "Div Amount": "amount",
    "Dividend Amount": "amount",
    "Amount": "amount",
    # CCY (yfinance uses amount_ccy)
    "div_ccy": "div_ccy",
    "Div CCY": "div_ccy",
    "Dividend Currency": "div_ccy",
    "amount_ccy": "div_ccy",
    "Amount CCY": "div_ccy",
    # Identifiers / labels
    "Underlying": "underlying",
    "Ticker": "underlying",
    "Div Type": "div_type",
    "Type": "div_type",
    "Status": "status",
    "Vendor Event Id": "vendor_event_id",
    "Source": "source",
    # debug
    "Note": "note",
    "Source Event Key": "source_event_key",
}


# -------------------------
# Bucketing (ISIN + div_ccy)
# -------------------------
def _ccy_norm(x: str) -> str:
    return str(x).strip().upper()


def _isin_cc(isin: str) -> str:
    s = str(isin).strip().upper()
    return s[:2] if len(s) >= 2 else ""


def infer_bucket(isin: str, div_ccy: str) -> Tuple[str, str]:
    cc = _isin_cc(isin)
    ccy = _ccy_norm(div_ccy)

    # explicit expands (requested)
    if cc == "JP":
        return "JP", "ISIN=JP"
    if cc == "AU":
        return "AU", "ISIN=AU"
    if cc == "US":
        return "US", "ISIN=US"

    # existing / common
    if cc == "KR":
        return "KR", "ISIN=KR"
    if cc == "BR":
        return "BR", "ISIN=BR"
    if cc == "IN":
        return "IN", "ISIN=IN"
    if cc == "TW":
        return "TW", "ISIN=TW"
    if cc == "HK":
        return "HK", "ISIN=HK"
    if cc == "GB":
        return "GB", "ISIN=GB"
    if cc == "FR":
        return "FR", "ISIN=FR"
    if cc == "DE":
        return "DE", "ISIN=DE"
    if cc == "CH":
        return "CH", "ISIN=CH"
    if cc == "SE":
        return "SE", "ISIN=SE"

    # extra reasonable expansion (low-risk)
    if cc == "CA":
        return "CA", "ISIN=CA"
    if cc == "NL":
        return "NL", "ISIN=NL"
    if cc == "IT":
        return "IT", "ISIN=IT"
    if cc == "ES":
        return "ES", "ISIN=ES"
    if cc == "BE":
        return "BE", "ISIN=BE"
    if cc == "SG":
        return "SG", "ISIN=SG"

    if cc == "CN":
        if ccy == "HKD":
            return "HK_PROXY", "ISIN=CN + CCY=HKD"
        if ccy in {"CNY", "CNH"}:
            return "CN", "ISIN=CN + CCY=CNY/CNH"
        return "CN", "ISIN=CN"

    if cc and cc != "US" and ccy == "USD":
        return f"{cc}_USD_PAY", "non-US ISIN + USD div_ccy"

    return "OTHER", f"ISIN={cc or 'NA'}"


# -------------------------
# Normalisation
# -------------------------
def _clean_str_series(s: pd.Series) -> pd.Series:
    """
    Avoid pandas FutureWarning about silent downcasting on replace.
    Keep values as string-like, but preserve missing as NA.
    """
    out = s.astype("string")
    out = out.replace({"nan": pd.NA, "NaN": pd.NA, "NAN": pd.NA, "None": pd.NA})
    return out.astype(object)


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    ren: Dict[str, str] = {}
    for c in df.columns:
        if c in DEFAULT_COLMAP:
            ren[c] = DEFAULT_COLMAP[c]
    if ren:
        df = df.rename(columns=ren)

    for c in STR_COLS:
        if c not in df.columns:
            df[c] = np.nan
    for c in DATE_COLS:
        if c not in df.columns:
            df[c] = pd.NaT
    for c in NUM_COLS:
        if c not in df.columns:
            df[c] = np.nan
    if "synthetic" not in df.columns:
        df["synthetic"] = False

    for c in STR_COLS:
        df[c] = _clean_str_series(df[c])
    for c in DATE_COLS:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["synthetic"] = pd.Series(df["synthetic"]).fillna(False).astype(bool)

    df["isin"] = _clean_str_series(df["isin"]).astype(str).str.strip().str.upper().replace({"<NA>": np.nan})
    df["div_ccy"] = _clean_str_series(df["div_ccy"]).astype(str).str.strip().str.upper().replace({"<NA>": np.nan})
    df["underlying"] = _clean_str_series(df["underlying"]).astype(str).str.strip().replace({"<NA>": np.nan})
    df["note"] = _clean_str_series(df["note"]).astype(str).replace({"<NA>": np.nan})
    df["source_event_key"] = _clean_str_series(df["source_event_key"]).astype(str).replace({"<NA>": np.nan})

    # Fallback: if seed has 'currency' and div_ccy missing, fill
    if "currency" in df.columns:
        miss = df["div_ccy"].isna()
        if miss.any():
            df.loc[miss, "div_ccy"] = (
                _clean_str_series(df.loc[miss, "currency"])
                .astype(str)
                .str.strip()
                .str.upper()
                .replace({"<NA>": np.nan})
            )

    buckets = df.apply(lambda r: infer_bucket(r["isin"], r["div_ccy"]), axis=1, result_type="expand")
    df["bucket"] = buckets[0]
    df["bucket_reason"] = buckets[1]

    df["row_id"] = (
        df["isin"].fillna("NA")
        + "|ex=" + df["ex_date"].dt.strftime("%Y-%m-%d").fillna("NA")
        + "|pay=" + df["pay_date"].dt.strftime("%Y-%m-%d").fillna("NA")
        + "|amt=" + df["amount"].round(8).astype(str)
        + "|ccy=" + df["div_ccy"].fillna("NA")
        + "|type=" + df["div_type"].fillna("NA")
        + "|status=" + df["status"].fillna("NA")
        + "|syn=" + df["synthetic"].astype(str)
    )
    return df


# -------------------------
# Seed usability / resolution
# -------------------------
def _seed_is_usable(df: pd.DataFrame) -> bool:
    need = ["ex_date", "amount", "isin", "div_ccy"]
    for c in need:
        if c not in df.columns:
            return False
    return not df.dropna(subset=need).empty


def _pick_newest_usable_seed_under_runs(runs_root: Path) -> Optional[Path]:
    if not runs_root.exists():
        return None

    best_path: Optional[Path] = None
    best_mtime: float = -1.0

    for d in runs_root.iterdir():
        if not d.is_dir():
            continue

        seed_path = _try_seed_in_run_dir(d)
        if not seed_path:
            continue

        try:
            mt = seed_path.stat().st_mtime
        except OSError:
            continue

        try:
            raw = _load_any(seed_path)
            norm = normalise_columns(raw)
            if not _seed_is_usable(norm):
                continue
        except Exception:
            continue

        if mt > best_mtime:
            best_mtime = mt
            best_path = seed_path

    return best_path.resolve() if best_path else None


def resolve_seed_path(seed_arg: str) -> Path:
    s = (seed_arg or "").strip()

    if s and s.lower() != "latest":
        p = Path(s)
        if not p.exists():
            raise FileNotFoundError(f"Seed path not found: {p}")

        if p.is_dir():
            inner_latest = p / "latest"
            if inner_latest.exists():
                hit = _try_seed_in_run_dir(inner_latest.resolve())
                if hit:
                    return hit

            hit = _try_seed_in_run_dir(p)
            if hit:
                return hit

            raise FileNotFoundError(
                f"Seed not found in dir: {p}\n"
                "Expected one of:\n"
                + "\n".join([f"  - {p}/{rel}" for rel in SEED_REL_CANDIDATES])
            )

        return p.resolve()

    tried: List[str] = []

    tried.append(str(REPO_LATEST_SEED))
    if _is_file(REPO_LATEST_SEED):
        return REPO_LATEST_SEED.resolve()

    runs_latest = Path("output") / "runs" / "latest"
    tried.append(str(runs_latest))
    if runs_latest.exists():
        hit = _try_seed_in_run_dir(runs_latest.resolve())
        if hit:
            return hit

    for f in DIRECT_FALLBACKS:
        tried.append(str(f))
        if _is_file(f):
            raw = _load_any(f)
            norm = normalise_columns(raw)
            if _seed_is_usable(norm):
                return f.resolve()

    runs_root = Path("output") / "runs"
    tried.append(str(runs_root / "<scan_for_newest_usable_seed>"))
    hit = _pick_newest_usable_seed_under_runs(runs_root)
    if hit:
        return hit

    msg = "Auto seed resolution failed.\nTried:\n" + "\n".join(f"- {t}" for t in tried)
    msg += (
        "\n\nFix options:\n"
        "1) pass --seed-divs <path-to-seed-csv/xlsx>\n"
        "2) ensure output/runs/latest points to a run that contains the seed\n"
        "3) create repo_root/latest/seed_yfinance_dividends_all.csv (symlink ok)\n"
    )
    raise FileNotFoundError(msg)


# -------------------------
# Holdings ISIN pool
# -------------------------
def load_isin_pool(holdings_paths: List[Path]) -> List[str]:
    isins: List[str] = []
    for p in holdings_paths:
        h = pd.read_csv(p)
        if "isin" not in h.columns:
            continue
        s = (
            _clean_str_series(h["isin"])
            .astype(str)
            .str.strip()
            .str.upper()
            .replace({"<NA>": np.nan})
            .dropna()
            .unique()
            .tolist()
        )
        isins.extend(s)

    isins = sorted(set([x for x in isins if isinstance(x, str) and len(x) >= 2]))
    if not isins:
        raise ValueError("No ISINs found in holdings files.")
    return isins


def attach_isin_from_holdings(seed_df: pd.DataFrame, isin_pool: List[str], *, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = seed_df.copy()

    miss = d["isin"].isna() | (d["isin"].astype(str).str.upper().isin({"", "NAN", "<NA>"}))
    if miss.any():
        picks = rng.choice(np.array(isin_pool), size=int(miss.sum()), replace=True)
        d.loc[miss, "isin"] = picks

    return d


# -------------------------
# Pay date synthesis (yfinance often missing pay_date)
# -------------------------
def ensure_pay_date(df: pd.DataFrame, *, seed: int, min_lag: int = 7, max_lag: int = 60) -> pd.DataFrame:
    d = df.copy()
    if "pay_date" not in d.columns:
        d["pay_date"] = pd.NaT

    miss = d["pay_date"].isna() & d["ex_date"].notna()
    if not miss.any():
        return d

    rng = np.random.default_rng(seed)
    lags = rng.integers(min_lag, max_lag + 1, size=int(miss.sum()))
    d.loc[miss, "pay_date"] = d.loc[miss, "ex_date"] + pd.to_timedelta(lags, unit="D")
    return d


# -------------------------
# Pattern flags (O1–O6)
# -------------------------
def _amt_close(a: float, b: float, rel: float = 0.02) -> bool:
    if np.isnan(a) or np.isnan(b):
        return False
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-9)


def _count_true_flags(row: pd.Series, flag_cols: List[str]) -> int:
    v = row[flag_cols]
    return int(pd.Series(v).fillna(False).astype(bool).sum())


def add_overlap_flags(df: pd.DataFrame, *, group_key: str, max_ex_diff_days: int = 7) -> pd.DataFrame:
    d = df.copy()
    for f in ["O1", "O2", "O3a", "O3b", "O3c", "O3d", "O4", "O5", "O6"]:
        d[f"flag_{f}"] = False

    if group_key not in d.columns:
        group_key = "underlying" if ("underlying" in d.columns and d["underlying"].notna().any()) else "isin"

    base = d.dropna(subset=[group_key, "ex_date"]).copy()

    # O1: same ex, multiple pay
    tmp = base.dropna(subset=["pay_date"])
    idx: List[int] = []
    for _, sub in tmp.groupby([group_key, "ex_date"], dropna=False):
        if sub["pay_date"].nunique(dropna=True) >= 2:
            idx.extend(sub.index.tolist())
    d.loc[idx, "flag_O1"] = True

    # O2: same ex & pay, multiple amounts
    tmp = base.dropna(subset=["pay_date", "amount"])
    idx = []
    for _, sub in tmp.groupby([group_key, "ex_date", "pay_date"], dropna=False):
        if sub["amount"].nunique(dropna=True) >= 2:
            idx.extend(sub.index.tolist())
    d.loc[idx, "flag_O2"] = True

    # O5: >1 div_ccy within group
    idx = []
    for _, sub in base.groupby(group_key, dropna=False):
        if sub["div_ccy"].nunique(dropna=True) >= 2:
            idx.extend(sub.index.tolist())
    d.loc[idx, "flag_O5"] = True

    # O4: vendor_event_id duplicates
    if "vendor_event_id" in d.columns:
        v = d.dropna(subset=["vendor_event_id"])
        dup = v[v.duplicated("vendor_event_id", keep=False)]
        if not dup.empty:
            d.loc[dup.index, "flag_O4"] = True

    # O3* + O6 pairwise per group
    work = base.dropna(subset=[group_key, "ex_date", "pay_date", "amount"]).copy()
    for _, sub in work.groupby(group_key):
        sub = sub.sort_values("ex_date").reset_index()
        n = len(sub)
        if n < 2:
            continue

        for i in range(n - 1):
            for j in range(i + 1, min(n, i + 12)):
                ex_i = sub.loc[i, "ex_date"]
                ex_j = sub.loc[j, "ex_date"]
                ex_diff = abs((ex_j - ex_i).days)
                if ex_diff == 0 or ex_diff > max_ex_diff_days:
                    continue

                pay_i = sub.loc[i, "pay_date"]
                pay_j = sub.loc[j, "pay_date"]
                pay_diff = abs((pay_j - pay_i).days)

                amt_i = float(sub.loc[i, "amount"])
                amt_j = float(sub.loc[j, "amount"])
                close = _amt_close(amt_i, amt_j, rel=0.02)

                idx_i = int(sub.loc[i, "index"])
                idx_j = int(sub.loc[j, "index"])

                if ex_diff in (1, 2) and pay_diff == 0 and close:
                    d.loc[[idx_i, idx_j], "flag_O3a"] = True
                if ex_diff in (1, 2) and pay_diff == 1 and close:
                    d.loc[[idx_i, idx_j], "flag_O3b"] = True
                if ex_diff in (1, 2) and pay_diff == 0 and (not close):
                    d.loc[[idx_i, idx_j], "flag_O3c"] = True
                if 3 <= ex_diff <= 7 and pay_diff == 0 and close:
                    d.loc[[idx_i, idx_j], "flag_O3d"] = True

                # O6 (demo): div_type mismatch ONLY (status excluded)
                t_i = str(sub.loc[i, "div_type"])
                t_j = str(sub.loc[j, "div_type"])
                type_diff = (
                    t_i and t_j
                    and t_i not in {"nan", "None"} and t_j not in {"nan", "None"}
                    and t_i != t_j
                )
                if ex_diff <= 7 and type_diff:
                    d.loc[[idx_i, idx_j], "flag_O6"] = True

    return d


# -------------------------
# Injection: guarantee O1–O6 exist (isolated groups)
# -------------------------
def _clone_row(row: pd.Series) -> Dict:
    return {k: row[k] for k in row.index}


def _safe_add_days(dt: pd.Timestamp, days: int) -> pd.Timestamp:
    if pd.isna(dt):
        return pd.NaT
    return dt + pd.Timedelta(days=int(days))


def _ensure_debug_fields(row: Dict) -> None:
    if "note" not in row:
        row["note"] = ""
    if "source_event_key" not in row or row["source_event_key"] in {None, "", np.nan}:
        ex = row.get("ex_date")
        ex_s = ex.strftime("%Y-%m-%d") if isinstance(ex, pd.Timestamp) and not pd.isna(ex) else "NA"
        amt = row.get("amount")
        amt_s = f"{float(amt):.8f}" if amt is not None and not pd.isna(amt) else "NA"
        ccy = str(row.get("div_ccy") or "NA").upper()
        und = str(row.get("underlying") or "NA")
        row["source_event_key"] = f"{und}|{ccy}|{ex_s}|{amt_s}"


def _tag_row(row: Dict, *, pattern: str, tag: str) -> None:
    _ensure_debug_fields(row)
    row["note"] = (str(row.get("note") or "").strip() + f" [SYN:{pattern}:{tag}]").strip()
    row["source_event_key"] = f"{row['source_event_key']}|SYN={pattern}:{tag}"


def _pick_distinct_isins(
    isin_pool: List[str],
    *,
    rng: np.random.Generator,
    n: int,
    bucket_allowlist: Optional[List[str]] = None,
) -> List[str]:
    pool = [x for x in isin_pool if isinstance(x, str) and len(x) >= 2]
    if bucket_allowlist:
        allow = set([b.strip().upper() for b in bucket_allowlist if b.strip()])
        pool = [x for x in pool if infer_bucket(x, "USD")[0] in allow or infer_bucket(x, "KRW")[0] in allow]
        # Note: infer_bucket depends on div_ccy for CN/HK_PROXY and *_USD_PAY; but for most, ISIN prefix dominates.
        # This filter is "best-effort" to align inject with allow-buckets.

    pool = list(dict.fromkeys(pool))  # stable dedupe
    if len(pool) < n:
        raise ValueError(f"Not enough distinct ISINs after filtering. Need={n}, have={len(pool)}")
    idx = rng.choice(np.arange(len(pool)), size=n, replace=False)
    return [pool[int(i)] for i in idx]


def _force_group_identity(rows: List[Dict], *, group_key: str, value: str) -> None:
    for r in rows:
        r[group_key] = value


def inject_demo_patterns(
    seed_df: pd.DataFrame,
    *,
    seed: int,
    isin_pool: Optional[List[str]] = None,
    bucket_allowlist: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Create guaranteed examples for O1–O6 by cloning and mutating seed rows.

    Key behaviour:
    - Each pattern is assigned a distinct group identity (ISIN) to minimise cross-flag noise.
    - Debugging is made easy by tagging both note and source_event_key with SYN:<pattern>:<tag>.
    """
    rng = np.random.default_rng(seed)

    d = seed_df.copy()
    d["synthetic"] = False
    d["source"] = d["source"].fillna("seed")

    base = d.dropna(subset=["ex_date", "pay_date", "amount", "div_ccy", "isin"]).copy()
    if base.empty:
        diag = {
            "rows_total": int(len(d)),
            "non_na_ex_date": int(d["ex_date"].notna().sum()) if "ex_date" in d.columns else 0,
            "non_na_pay_date": int(d["pay_date"].notna().sum()) if "pay_date" in d.columns else 0,
            "non_na_amount": int(d["amount"].notna().sum()) if "amount" in d.columns else 0,
            "non_na_div_ccy": int(d["div_ccy"].notna().sum()) if "div_ccy" in d.columns else 0,
            "non_na_isin": int(d["isin"].notna().sum()) if "isin" in d.columns else 0,
        }
        raise ValueError(f"Seed dividends have no usable rows. Diagnostics: {diag}")

    if isin_pool is None:
        isin_pool = sorted(set(base["isin"].dropna().astype(str).tolist()))

    # Need 9 distinct group identities: O1,O2,O3a,O3b,O3c,O3d,O4,O5,O6
    pattern_groups = _pick_distinct_isins(isin_pool, rng=rng, n=9, bucket_allowlist=bucket_allowlist)
    g_map = {
        "O1": pattern_groups[0],
        "O2": pattern_groups[1],
        "O3a": pattern_groups[2],
        "O3b": pattern_groups[3],
        "O3c": pattern_groups[4],
        "O3d": pattern_groups[5],
        "O4": pattern_groups[6],
        "O5": pattern_groups[7],
        "O6": pattern_groups[8],
    }

    rows: List[Dict] = []

    def pick_one() -> pd.Series:
        return base.iloc[int(rng.integers(0, len(base)))]

    # O1
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O1"])
    r1["vendor_event_id"] = "SYN_O1_A"
    r2["vendor_event_id"] = "SYN_O1_B"
    r2["pay_date"] = _safe_add_days(r["pay_date"], 30)
    _tag_row(r1, pattern="O1", tag="SYN_O1_A")
    _tag_row(r2, pattern="O1", tag="SYN_O1_B")
    rows += [r1, r2]

    # O2
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O2"])
    r1["vendor_event_id"] = "SYN_O2_A"
    r2["vendor_event_id"] = "SYN_O2_B"
    r2["amount"] = float(r["amount"]) * 1.10
    _tag_row(r1, pattern="O2", tag="SYN_O2_A")
    _tag_row(r2, pattern="O2", tag="SYN_O2_B")
    rows += [r1, r2]

    # O3a
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O3a"])
    r1["vendor_event_id"] = "SYN_O3A_A"
    r2["vendor_event_id"] = "SYN_O3A_B"
    r2["ex_date"] = _safe_add_days(r["ex_date"], 2)
    r2["amount"] = float(r["amount"]) * 1.01
    _tag_row(r1, pattern="O3a", tag="SYN_O3A_A")
    _tag_row(r2, pattern="O3a", tag="SYN_O3A_B")
    rows += [r1, r2]

    # O3b
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O3b"])
    r1["vendor_event_id"] = "SYN_O3B_A"
    r2["vendor_event_id"] = "SYN_O3B_B"
    r2["ex_date"] = _safe_add_days(r["ex_date"], 1)
    r2["pay_date"] = _safe_add_days(r["pay_date"], 1)
    r2["amount"] = float(r["amount"]) * 0.99
    _tag_row(r1, pattern="O3b", tag="SYN_O3B_A")
    _tag_row(r2, pattern="O3b", tag="SYN_O3B_B")
    rows += [r1, r2]

    # O3c
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O3c"])
    r1["vendor_event_id"] = "SYN_O3C_A"
    r2["vendor_event_id"] = "SYN_O3C_B"
    r2["ex_date"] = _safe_add_days(r["ex_date"], 2)
    r2["amount"] = float(r["amount"]) * 1.25
    _tag_row(r1, pattern="O3c", tag="SYN_O3C_A")
    _tag_row(r2, pattern="O3c", tag="SYN_O3C_B")
    rows += [r1, r2]

    # O3d
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O3d"])
    r1["vendor_event_id"] = "SYN_O3D_A"
    r2["vendor_event_id"] = "SYN_O3D_B"
    r1["status"] = "expected"
    r2["status"] = "declared"
    r2["ex_date"] = _safe_add_days(r["ex_date"], 5)
    r2["amount"] = float(r["amount"]) * 1.01
    _tag_row(r1, pattern="O3d", tag="SYN_O3D_A")
    _tag_row(r2, pattern="O3d", tag="SYN_O3D_B")
    rows += [r1, r2]

    # O4
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O4"])
    r1["vendor_event_id"] = "SYN_O4_COLLIDE"
    r2["vendor_event_id"] = "SYN_O4_COLLIDE"
    r2["amount"] = float(r["amount"]) * 1.05
    _tag_row(r1, pattern="O4", tag="SYN_O4_COLLIDE_A")
    _tag_row(r2, pattern="O4", tag="SYN_O4_COLLIDE_B")
    rows += [r1, r2]

    # O5
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O5"])
    r1["vendor_event_id"] = "SYN_O5_LOCAL"
    r2["vendor_event_id"] = "SYN_O5_ALT"
    r2["div_ccy"] = "USD" if str(r1["div_ccy"]).upper() != "USD" else "EUR"
    _tag_row(r1, pattern="O5", tag="SYN_O5_LOCAL")
    _tag_row(r2, pattern="O5", tag="SYN_O5_ALT")
    rows += [r1, r2]

    # O6
    r = pick_one()
    r1, r2 = _clone_row(r), _clone_row(r)
    _force_group_identity([r1, r2], group_key="isin", value=g_map["O6"])
    r1["vendor_event_id"] = "SYN_O6_A"
    r2["vendor_event_id"] = "SYN_O6_B"
    r1["div_type"] = "DIV"
    r2["div_type"] = "JCP"
    r2["ex_date"] = _safe_add_days(r["ex_date"], 1)
    _tag_row(r1, pattern="O6", tag="SYN_O6_A")
    _tag_row(r2, pattern="O6", tag="SYN_O6_B")
    rows += [r1, r2]

    inj = pd.DataFrame(rows)
    inj["source"] = "demo_inject"
    inj["synthetic"] = True

    return pd.concat([d, inj], ignore_index=True)


# -------------------------
# Random sampling per pattern
# -------------------------
PATTERNS = [
    ("O1", "flag_O1"),
    ("O2", "flag_O2"),
    ("O3a", "flag_O3a"),
    ("O3b", "flag_O3b"),
    ("O3c", "flag_O3c"),
    ("O3d", "flag_O3d"),
    ("O4", "flag_O4"),
    ("O5", "flag_O5"),
    ("O6", "flag_O6"),
]


def _pick_rows(
    sub: pd.DataFrame,
    *,
    rng: np.random.Generator,
    k: int,
    flag_cols: List[str],
    pure_only: bool,
) -> pd.DataFrame:
    """
    Sampling policy:
    - If pure_only=True: keep only rows where flag_true_count == 1 (no mixed fill).
    - Else: take pure rows first; if there are not enough, top up with mixed-flag rows.
    """
    if sub.empty:
        return sub

    x = sub.copy()
    x["_flag_true_count"] = x.apply(lambda r: _count_true_flags(r, flag_cols), axis=1)

    pure = x[x["_flag_true_count"] == 1].copy()
    mixed = x[x["_flag_true_count"] > 1].copy()

    if pure_only:
        y = pure
        if y.empty:
            return y
        if len(y) > k:
            idx = rng.choice(y.index.to_numpy(), size=k, replace=False)
            y = y.loc[idx].copy()
        return y.drop(columns=["_flag_true_count"], errors="ignore")

    # pure-first then mixed fill
    parts: List[pd.DataFrame] = []
    if not pure.empty:
        if len(pure) > k:
            idx = rng.choice(pure.index.to_numpy(), size=k, replace=False)
            pure = pure.loc[idx].copy()
        parts.append(pure)

    remain = k - sum(len(p) for p in parts)
    if remain > 0 and not mixed.empty:
        if len(mixed) > remain:
            idx = rng.choice(mixed.index.to_numpy(), size=remain, replace=False)
            mixed = mixed.loc[idx].copy()
        parts.append(mixed)

    out = pd.concat(parts, axis=0) if parts else x.iloc[0:0].copy()
    out = out.drop(columns=["_flag_true_count"], errors="ignore")
    return out


def extract_samples_random(
    df: pd.DataFrame,
    *,
    seed: int,
    k_per_pattern: int,
    group_key: str,
    bucket_allowlist: Optional[List[str]] = None,
    pure_only: bool = False,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = df.copy()

    if bucket_allowlist:
        d = d[d["bucket"].isin(bucket_allowlist)].copy()

    d = add_overlap_flags(d, group_key=group_key)

    if group_key not in d.columns:
        group_key = "underlying" if ("underlying" in d.columns and d["underlying"].notna().any()) else "isin"

    flag_cols = [f"flag_{p[0]}" for p in PATTERNS]

    out_parts: List[pd.DataFrame] = []

    for tag, flag in PATTERNS:
        hit = d[d[flag]].copy()
        if hit.empty:
            continue

        hit["_g"] = hit[group_key].astype(str)

        if tag == "O5":
            groups = hit["_g"].dropna().drop_duplicates().tolist()
            if not groups:
                continue
            chosen_g = groups[int(rng.integers(0, len(groups)))]
            sub = d[d[group_key].astype(str) == str(chosen_g)].copy()
            sub = sub[sub[flag]].copy()
            chosen_b = "MULTI_CCY"
        else:
            hit["_b"] = hit["bucket"].astype(str)
            pairs = hit.dropna(subset=["_g", "_b"])[["_b", "_g"]].drop_duplicates().values.tolist()
            if not pairs:
                continue
            chosen_b, chosen_g = pairs[int(rng.integers(0, len(pairs)))]
            sub = d[
                (d["bucket"].astype(str) == str(chosen_b))
                & (d[group_key].astype(str) == str(chosen_g))
            ].copy()
            sub = sub[sub[flag]].copy()

        if sub.empty:
            continue

        sub = _pick_rows(sub, rng=rng, k=k_per_pattern, flag_cols=flag_cols, pure_only=pure_only)
        if sub.empty:
            continue

        sub["pattern"] = tag
        sub["sample_seed"] = int(seed)
        sub["sample_group_key"] = group_key
        sub["sample_group_value"] = str(chosen_g)
        sub["sample_bucket"] = str(chosen_b)

        base_note = f"random pick: bucket={chosen_b}, {group_key}={chosen_g}"
        sub["note"] = sub["note"].fillna("").astype(str).apply(lambda x: (x + " | " + base_note).strip(" |"))

        out_parts.append(sub)

    if not out_parts:
        return pd.DataFrame([{"note": "NO_SAMPLES"}])

    out = pd.concat(out_parts, ignore_index=True)
    meta = [
        "pattern",
        "synthetic",
        "source",
        "sample_seed",
        "sample_bucket",
        "bucket_reason",
        "sample_group_key",
        "sample_group_value",
        "note",
        "source_event_key",
    ]
    cols = meta + [c for c in out.columns if c not in meta]
    return out[cols]


# -------------------------
# CLI
# -------------------------
def main() -> None:
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--seed-divs",
        default="latest",
        help=(
            "Stage1 dividends seed (CSV/XLSX).\n"
            "If omitted or 'latest': auto-resolves newest usable seed, preferring output/runs/latest.\n"
            "If a directory: searches <dir>/<seed> and <dir>/stage1_seed/<seed>.\n"
        ),
    )

    ap.add_argument("--holdings", required=True, nargs="+", type=Path, help="Holdings CSVs (EEM/EFA full) to supply ISINs")
    ap.add_argument("--out", required=True, type=Path)

    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed. If omitted, a random seed is generated and printed (reproducible if provided).",
    )

    ap.add_argument("--k-per-pattern", type=int, default=2)
    ap.add_argument("--group-key", type=str, default="isin", help="demo default: isin (economic_event_id likely absent)")
    ap.add_argument("--allow-buckets", type=str, default="", help="comma-separated bucket list (e.g. BR,KR,GB,JP,AU,US)")

    ap.add_argument(
        "--pure-only",
        action="store_true",
        help=(
            "Strict sampling: only keep rows where exactly ONE overlap flag is true (row-level purity). "
            "No mixed-row fill. Useful for debugging/verification."
        ),
    )

    ap.add_argument(
        "--inject-only",
        action="store_true",
        help=(
            "Sample only from injected synthetic rows (synthetic=True). "
            "Recommended for deterministic demos; avoids seed noise."
        ),
    )

    args = ap.parse_args()

    seed_used = args.seed if args.seed is not None else secrets.randbits(32)

    allow = [x.strip().upper() for x in args.allow_buckets.split(",") if x.strip()] or None

    seed_path = resolve_seed_path(args.seed_divs)
    seed_raw = _load_any(seed_path)
    seed_df = normalise_columns(seed_raw)

    isin_pool = load_isin_pool(args.holdings)
    seed_df = attach_isin_from_holdings(seed_df, isin_pool, seed=seed_used)
    seed_df = normalise_columns(seed_df)

    seed_df = ensure_pay_date(seed_df, seed=seed_used)
    seed_df = normalise_columns(seed_df)

    demo_df = inject_demo_patterns(seed_df, seed=seed_used, isin_pool=isin_pool, bucket_allowlist=allow)
    demo_df = normalise_columns(demo_df)

    if args.inject_only:
        demo_df = demo_df[demo_df["synthetic"]].copy()
        demo_df = normalise_columns(demo_df)

    missing = [c for c in REQ_MIN if c not in demo_df.columns or demo_df[c].isna().all()]
    if missing:
        raise ValueError(f"Missing required columns (or all-NA): {missing}. Have columns={list(demo_df.columns)}")

    out_df = extract_samples_random(
        demo_df,
        seed=seed_used,
        k_per_pattern=args.k_per_pattern,
        group_key=args.group_key,
        bucket_allowlist=allow,
        pure_only=args.pure_only,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")

    print("seed_used     :", seed_used)
    print("seed_path     :", seed_path)
    print("allow_buckets :", allow)
    print("inject_only   :", bool(args.inject_only))
    print("pure_only     :", bool(args.pure_only))
    print("wrote         :", args.out.resolve())
    print("rows          :", len(out_df))
    if "pattern" in out_df.columns:
        print("pattern counts:\n", out_df["pattern"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()