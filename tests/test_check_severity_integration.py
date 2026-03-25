# tests/test_check_severity_integration.py

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd


def run(cmd: list[str], cwd: Path) -> tuple[str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout, p.stderr


def _pair_key(a: str, b: str) -> str:
    a = str(a).strip()
    b = str(b).strip()
    return "||".join(sorted([a, b]))


def test_o3_decisions_suppression_and_merge(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]

    run_root = tmp_path / "runs" / "demo__override_fixture"
    decisions_path = tmp_path / "o3_decisions_demo.csv"

    # 0) Build the demo run_root fixture (stage1_seed/*) inside tmp_path
    run(
        [
            "python",
            "scripts/gen_synthetic_rows_fixture.py",
            "--run-root",
            str(run_root),
        ],
        cwd=repo,
    )

    # 1) Trigger template creation
    if decisions_path.exists():
        decisions_path.unlink()

    run(
        [
            "python",
            "scripts/check_severity.py",
            "--run-root",
            str(run_root),
            "--respect-existing-econ-id",
            "--o3-enable",
            "--o3-decisions",
            str(decisions_path),
            "--o3-suppress-reviewed",
        ],
        cwd=repo,
    )

    assert decisions_path.exists(), "O3 decisions template file was not created"

    # 2) Populate decisions (test fixture)
    keep_a = "eco_demo_f6a6e85551eebfc1"
    keep_b = "eco_demo_c0026a677adcabff"
    merge_a = "eco_demo_ca899c37938f214d"
    merge_b = "eco_demo_6d4ffea513079eb9"

    decisions_path.write_text(
        "enabled,underlying,econ_id_a,econ_id_b,decision,canonical_econ_id,note\n"
        f"true,GHI,{keep_a},{keep_b},KEEP,,\n"
        f"true,GHJ,{merge_a},{merge_b},MERGE,,\n",
        encoding="utf-8",
    )

    # 3) Re-run with the populated decisions
    run(
        [
            "python",
            "scripts/check_severity.py",
            "--run-root",
            str(run_root),
            "--respect-existing-econ-id",
            "--o3-enable",
            "--o3-ex-shift-days-ge",
            "1",
            "--o3-pay-shift-days-le",
            "1",
            "--o3-amount-abs-diff-le",
            "0.02",
            "--o3-require-same-ccy",
            "--o3-decisions",
            str(decisions_path),
            "--o3-suppress-reviewed",
        ],
        cwd=repo,
    )

    stage2 = run_root / "stage2_analysis"

    # A) Suppression checks
    qa_pairs = pd.read_csv(stage2 / "qa_queue__o3_pairs.csv")
    assert len(qa_pairs) == 3

    qa_pairs["pair_key"] = (
        qa_pairs[["econ_id_a", "econ_id_b"]]
        .astype("string")
        .fillna("")
        .apply(lambda s: "||".join(sorted([s.iloc[0].strip(), s.iloc[1].strip()])), axis=1)
    )

    suppressed_key = _pair_key(keep_a, keep_b)
    assert suppressed_key not in set(qa_pairs["pair_key"])

    # B) Merge checks
    rows = pd.read_csv(stage2 / "seed_yfinance_dividends_all__linked_severity.csv")
    assert (rows["economic_event_id"] == merge_b).sum() == 0
    assert (rows["economic_event_id"] == merge_a).sum() >= 1