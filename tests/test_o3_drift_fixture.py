# tests/test_o3_drift_fixture.py

# Purpose: Validate that v1 can reproduce an "O3 ex-date drift (anchor drift)" with a minimal fixture.
# - Runs Stage2 (scripts/check_severity.py) via subprocess to generate/validate run-root artefacts.
# - Since v1 is single-vendor, O3 may not appear naturally; we inject two rows into the Stage1 seed CSV.

# Assertions (used as a "v1 exit" gate):
# 1) econ_severity_summary.csv contains at least one econ with row_count == 2
# 2) anchor_spread_days >= 1 (drift is actually detected)
# 3) (Optional) applying SET_ANCHOR_DATE collapses anchor_spread_days to 0

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


def _repo_root() -> Path:
    # Assumes this test file lives under tests/
    return Path(__file__).resolve().parents[1]


def _run_check_severity(*args: str) -> None:
    repo = _repo_root()
    cmd = [sys.executable, "scripts/check_severity.py", *args]
    subprocess.run(cmd, cwd=str(repo), check=True)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _minimal_no_div_seed(path: Path) -> None:
    # Some Stage2 flows expect stage1_seed/seed_yfinance_no_dividends_all.csv to exist.
    # Provide an empty file with the expected header.
    cols = [
        "underlying",
        "yfinance_ticker",
        "exists_ticker",
        "reason",
        "asof_date",
        "holdings_tag",
        "holdings_file",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()


def _make_o3_seed_rows() -> list[dict]:
    """
    O3 fixture design:
    - Same underlying / same pay_date / same amount / same ccy
    - ex_date drifts by +1 day
    - vendor_event_id must differ
    - anchor_date is explicitly set to ex_date so anchor_spread_days can detect the drift
    """
    base = dict(
        economic_event_id="",  # Let Stage2 generate/fill
        source="fixture",
        source_event_key="2330.TW|TWD|PAY=2025-04-17|AMT=4.50002",  # Intentionally identical to cluster
        underlying="2330",
        isin="",
        market="TW",
        currency="TWD",
        yfinance_ticker="2330.TW",
        action_type="DIVIDEND",
        period_type="REGULAR",
        share_class="COMMON",
        status="DECLARED",
        declared_date="2025-03-01",
        record_date="",
        pay_date="2025-04-17",
        amount="4.50002",
        amount_type="CASH",
        amount_ccy="TWD",
        confidence="0.9",
        evidence_json="{}",
        asof_date="2026-02-09",
        ingest_ts=datetime.now(UTC).isoformat(timespec="seconds"),
        holdings_tag="TEST",
        holdings_file="tests-fixture",
        case_tag="O3",
    )

    r1 = dict(base)
    r1.update(
        vendor_event_id="OBS|2a738f4afe85b7ab__O3A",
        ex_date="2025-03-18",
        anchor_date="2025-03-18",
    )

    r2 = dict(base)
    r2.update(
        vendor_event_id="OBS|2a738f4afe85b7ab__O3B",
        ex_date="2025-03-19",
        anchor_date="2025-03-19",
    )

    return [r1, r2]


def test_o3_drift_fixture_surfaces_anchor_spread(tmp_path: Path) -> None:
    """
    1) Build a temp run-root
    2) Write a 2-row O3 fixture into stage1_seed/seed_yfinance_dividends_all.csv
    3) Run Stage2
    4) Assert anchor_spread_days >= 1 for at least one econ with row_count == 2
    """
    run_root = tmp_path / "output" / "runs" / "divpipe__TEST__o3"
    stage1 = run_root / "stage1_seed"
    stage2 = run_root / "stage2_analysis"

    _write_csv(stage1 / "seed_yfinance_dividends_all.csv", _make_o3_seed_rows())
    _minimal_no_div_seed(stage1 / "seed_yfinance_no_dividends_all.csv")

    _run_check_severity("--run-root", str(run_root))

    econ = pd.read_csv(stage2 / "econ_severity_summary.csv")

    hit = econ.loc[econ.get("row_count", 0) == 2].copy()
    assert len(hit) >= 1, f"expected at least one econ with row_count==2; got {len(hit)}"

    assert "anchor_spread_days" in hit.columns, "econ_severity_summary.csv missing anchor_spread_days"
    assert (hit["anchor_spread_days"] >= 1).any(), (
        "expected anchor_spread_days>=1 in at least one hit:\n"
        f"{hit.head(10)}"
    )


def test_o3_set_anchor_date_override_collapses_spread(tmp_path: Path) -> None:
    """
    After drift is detected, apply SET_ANCHOR_DATE overrides to force a single canonical anchor.
    Expect anchor_spread_days == 0 for an econ with row_count == 2.
    """
    run_root = tmp_path / "output" / "runs" / "divpipe__TEST__o3_override"
    stage1 = run_root / "stage1_seed"
    stage2 = run_root / "stage2_analysis"

    _write_csv(stage1 / "seed_yfinance_dividends_all.csv", _make_o3_seed_rows())
    _minimal_no_div_seed(stage1 / "seed_yfinance_no_dividends_all.csv")

    _run_check_severity("--run-root", str(run_root))

    qa = stage2 / "qa_decisions.csv"
    qa.parent.mkdir(parents=True, exist_ok=True)
    qa.write_text(
        "\n".join(
            [
                "vendor_event_id,underlying,ex_date,action,economic_event_id,amount,div_ccy,anchor_date,note",
                "OBS|2a738f4afe85b7ab__O3A,2330,2025-03-18,SET_ANCHOR_DATE,,,,2025-03-18,collapse anchor",
                "OBS|2a738f4afe85b7ab__O3B,2330,2025-03-19,SET_ANCHOR_DATE,,,,2025-03-18,collapse anchor",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    _run_check_severity("--run-root", str(run_root), "--qa-decisions", str(qa))

    econ = pd.read_csv(stage2 / "econ_severity_summary.csv")
    hit = econ.loc[econ.get("row_count", 0) == 2].copy()
    assert len(hit) >= 1, f"expected at least one econ with row_count==2; got {len(hit)}"

    assert (hit["anchor_spread_days"] == 0).any(), (
        "expected anchor_spread_days==0 after override:\n"
        f"{hit.head(10)}"
    )