# tests/test_econ_id_stability.py
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.divpipe.pipeline.link_events import assign_economic_events


def _mk_base_df() -> pd.DataFrame:
    """
    Build a small but adversarial dataset to stress determinism:
      - multiple ids, mixed ccy formatting, blanks, and repeated vendor_event_id groups
      - enough rows to create multiple economic groups and linking chains
    """
    return pd.DataFrame(
        [
            # Group A (ISIN wins), should link within day-shift threshold
            {
                "vendor_event_id": "v1",
                "source_event_key": "sek_a_1",
                "isin": "US0000000001",
                "underlying": "AAA",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": " usd ",
                "ex_date": "2025-01-10",
                "record_date": "",
                "pay_date": "",
                "amount": 1.00,
                "status": "historical",
                "div_type": "cash",
            },
            {
                "vendor_event_id": "v1",
                "source_event_key": "sek_a_2",
                "isin": "US0000000001",
                "underlying": "AAA",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": "USD",
                "ex_date": "2025-01-12",
                "record_date": "",
                "pay_date": "",
                "amount": 1.05,
                "status": "historical",
                "div_type": "cash",
            },
            # Group B (no ISIN -> underlying), different ccy
            {
                "vendor_event_id": "",
                "source_event_key": "sek_b_1",
                "isin": "",
                "underlying": "BBB",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": "krw",
                "ex_date": "2025-02-01",
                "record_date": "",
                "pay_date": "",
                "amount": 100.0,
                "status": "historical",
                "div_type": "cash",
            },
            {
                "vendor_event_id": "",
                "source_event_key": "sek_b_2",
                "isin": "",
                "underlying": "BBB",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": " KRW ",
                "ex_date": "2025-02-03",
                "record_date": "",
                "pay_date": "",
                "amount": 100.0,
                "status": "historical",
                "div_type": "cash",
            },
            # Group C: missing/invalid ccy should be invalid rows (skip)
            {
                "vendor_event_id": "",
                "source_event_key": "sek_c_1",
                "isin": "GB0000000002",
                "underlying": "CCC",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": "GBp",  # should become NA => invalid
                "ex_date": "2025-03-01",
                "record_date": "",
                "pay_date": "",
                "amount": 0.5,
                "status": "historical",
                "div_type": "cash",
            },
            # Group D: tie-break path (no vendor_event_id, no sek) => hashed fingerprint
            {
                "vendor_event_id": "",
                "source_event_key": "",
                "isin": "JP0000000003",
                "underlying": "DDD",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": "JPY",
                "ex_date": "2025-04-01",
                "record_date": "",
                "pay_date": "",
                "amount": 10.0,
                "status": "historical",
                "div_type": "cash",
            },
            {
                "vendor_event_id": "",
                "source_event_key": "",
                "isin": "JP0000000003",
                "underlying": "DDD",
                "action_type": "cash_dividend",
                "share_class": "common",
                "amount_ccy": "JPY",
                "ex_date": "2025-04-02",
                "record_date": "",
                "pay_date": "",
                "amount": 10.0,
                "status": "historical",
                "div_type": "cash",
            },
        ]
    )


def _baseline_signature(df_out: pd.DataFrame) -> pd.DataFrame:
    """
    Order-invariant signature:
      - keep only deterministic identity columns and assigned ids
      - sort by stable per-row key (prefer vendor_event_id/sek/isin+date+amount)
    """
    def _row_key(r) -> str:
        vid = str(r.get("vendor_event_id", "") or "").strip()
        sek = str(r.get("source_event_key", "") or "").strip()
        isin = str(r.get("isin", "") or "").strip()
        und = str(r.get("underlying", "") or "").strip()
        exd = str(r.get("ex_date", "") or "").strip()
        amt = str(r.get("amount", "") or "").strip()
        ccy = str(r.get("amount_ccy", "") or r.get("div_ccy", "") or "").strip()
        return "|".join([vid, sek, isin or und, ccy, exd, amt])

    sig = df_out.copy()
    sig["_k"] = sig.apply(_row_key, axis=1)

    keep = [
        "_k",
        "economic_event_key",
        "economic_event_id",
        "event_link_reason",
    ]
    for c in keep:
        if c not in sig.columns:
            sig[c] = ""

    sig = sig[keep].copy()
    sig = sig.sort_values("_k", kind="mergesort").reset_index(drop=True)
    return sig


def _group_signature(df_out: pd.DataFrame) -> pd.DataFrame:
    """
    Group-level signature:
      - for each economic_event_id, capture set of rows (via _k)
      - compare as a mapping: econ_id -> sorted list of _k hashes
    """
    sig = df_out.copy()

    def _row_key(r) -> str:
        vid = str(r.get("vendor_event_id", "") or "").strip()
        sek = str(r.get("source_event_key", "") or "").strip()
        isin = str(r.get("isin", "") or "").strip()
        und = str(r.get("underlying", "") or "").strip()
        exd = str(r.get("ex_date", "") or "").strip()
        amt = str(r.get("amount", "") or "").strip()
        ccy = str(r.get("amount_ccy", "") or r.get("div_ccy", "") or "").strip()
        return "|".join([vid, sek, isin or und, ccy, exd, amt])

    sig["_k"] = sig.apply(_row_key, axis=1)
    sig["economic_event_id"] = sig["economic_event_id"].astype("string").fillna("")

    g = (
        sig[sig["economic_event_id"].ne("")]
        .groupby("economic_event_id", sort=False)["_k"]
        .apply(lambda s: tuple(sorted(s.astype(str).tolist())))
        .reset_index()
        .sort_values("economic_event_id", kind="mergesort")
        .reset_index(drop=True)
    )
    return g


def test_econ_id_is_shuffle_invariant_rowwise():
    base = _mk_base_df()
    out0 = assign_economic_events(base, respect_existing=False)
    sig0 = _baseline_signature(out0)

    rng = np.random.default_rng(42)
    for _ in range(50):
        perm = rng.permutation(len(base))
        shuffled = base.iloc[perm].reset_index(drop=True)
        out = assign_economic_events(shuffled, respect_existing=False)
        sig = _baseline_signature(out)
        pd.testing.assert_frame_equal(sig0, sig)


def test_econ_id_is_shuffle_invariant_groupwise():
    base = _mk_base_df()
    out0 = assign_economic_events(base, respect_existing=False)
    g0 = _group_signature(out0)

    rng = np.random.default_rng(7)
    for _ in range(50):
        perm = rng.permutation(len(base))
        shuffled = base.iloc[perm].reset_index(drop=True)
        out = assign_economic_events(shuffled, respect_existing=False)
        g = _group_signature(out)
        pd.testing.assert_frame_equal(g0, g)