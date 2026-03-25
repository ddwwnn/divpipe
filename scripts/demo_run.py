#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/demo_run.py

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    run_root = Path("output") / "runs" / "demo_run"
    stage1 = run_root / "stage1_seed"
    stage1.mkdir(parents=True, exist_ok=True)

    ingest_ts = _utc_now_iso()
    asof_date = ingest_ts[:10]

    # Minimal deterministic seed that will trigger tiering:
    # - O1: same ex_date, different pay_date (same underlying)
    # - O2: same ex_date & pay_date, different amounts (same underlying)
    # Keep these isolated by underlying to reduce cross-noise.
    rows = [
        # O1: same ex_date, different pay_date
        {
            "source": "demo",
            "source_event_key": "O1|AAA|2025-12-27|0.10|USD|A",
            "underlying": "AAA",
            "isin": "US000000AAA0",
            "market": "US",
            "currency": "USD",
            "action_type": "DIV",
            "status": "declared",
            "ex_date": "2025-12-27",
            "pay_date": "2026-01-10",
            "amount": 0.10,
            "amount_type": "cash",
            "amount_ccy": "USD",
            "confidence": 0.90,
            "evidence_json": json.dumps({"isin": "US000000AAA0", "note": "demo O1 A"}),
            "asof_date": asof_date,
            "ingest_ts": ingest_ts,
        },
        {
            "source": "demo",
            "source_event_key": "O1|AAA|2025-12-27|0.10|USD|B",
            "underlying": "AAA",
            "isin": "US000000AAA0",
            "market": "US",
            "currency": "USD",
            "action_type": "DIV",
            "status": "declared",
            "ex_date": "2025-12-27",
            "pay_date": "2026-02-10",
            "amount": 0.10,
            "amount_type": "cash",
            "amount_ccy": "USD",
            "confidence": 0.90,
            "evidence_json": json.dumps({"isin": "US000000AAA0", "note": "demo O1 B"}),
            "asof_date": asof_date,
            "ingest_ts": ingest_ts,
        },
        # O2: same ex_date & pay_date, different amounts
        {
            "source": "demo",
            "source_event_key": "O2|BBB|2025-12-30|0.20|USD|A",
            "underlying": "BBB",
            "isin": "US000000BBB0",
            "market": "US",
            "currency": "USD",
            "action_type": "DIV",
            "status": "declared",
            "ex_date": "2025-12-30",
            "pay_date": "2026-01-15",
            "amount": 0.20,
            "amount_type": "cash",
            "amount_ccy": "USD",
            "confidence": 0.90,
            "evidence_json": json.dumps({"isin": "US000000BBB0", "note": "demo O2 A"}),
            "asof_date": asof_date,
            "ingest_ts": ingest_ts,
        },
        {
            "source": "demo",
            "source_event_key": "O2|BBB|2025-12-30|0.22|USD|B",
            "underlying": "BBB",
            "isin": "US000000BBB0",
            "market": "US",
            "currency": "USD",
            "action_type": "DIV",
            "status": "declared",
            "ex_date": "2025-12-30",
            "pay_date": "2026-01-15",
            "amount": 0.22,
            "amount_type": "cash",
            "amount_ccy": "USD",
            "confidence": 0.90,
            "evidence_json": json.dumps({"isin": "US000000BBB0", "note": "demo O2 B"}),
            "asof_date": asof_date,
            "ingest_ts": ingest_ts,
        },
        # A clean, non-flagged single row (tier2-ish) for contrast
        {
            "source": "demo",
            "source_event_key": "OK|CCC|2025-12-20|0.05|USD",
            "underlying": "CCC",
            "isin": "US000000CCC0",
            "market": "US",
            "currency": "USD",
            "action_type": "DIV",
            "status": "declared",
            "ex_date": "2025-12-20",
            "pay_date": "2026-01-05",
            "amount": 0.05,
            "amount_type": "cash",
            "amount_ccy": "USD",
            "confidence": 0.95,
            "evidence_json": json.dumps({"isin": "US000000CCC0", "note": "demo clean"}),
            "asof_date": asof_date,
            "ingest_ts": ingest_ts,
        },
    ]

    divs = pd.DataFrame(rows)

    # Ensure required columns exist even if someone edits rows.
    required_div_cols = [
        "source",
        "source_event_key",
        "underlying",
        "isin",
        "market",
        "currency",
        "action_type",
        "status",
        "ex_date",
        "amount",
        "amount_type",
        "amount_ccy",
        "confidence",
        "evidence_json",
        "asof_date",
        "ingest_ts",
    ]
    for c in required_div_cols:
        if c not in divs.columns:
            divs[c] = ""

    out_divs = stage1 / "seed_yfinance_dividends_all.csv"
    _write_csv(divs[required_div_cols + [c for c in divs.columns if c not in required_div_cols]], out_divs)

    # Optional input for stage2 no-div splits. Keep it empty but schema-correct.
    no_div_cols = [
        "source",
        "underlying",
        "underlying_ccy",
        "isin",
        "status",
        "exists_ticker",
        "candidates",
        "start",
        "end",
    ]
    no_div = pd.DataFrame([], columns=no_div_cols)
    out_no_div = stage1 / "seed_yfinance_no_dividends_all.csv"
    _write_csv(no_div, out_no_div)

    print("wrote:", out_divs)
    print("wrote:", out_no_div)
    print("run_root:", run_root)


if __name__ == "__main__":
    main()