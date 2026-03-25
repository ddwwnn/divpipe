# tests/test_check_severity_guardrails.py

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from engine.divpipe import check_severity as cs


def _make_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "output" / "runs" / "divpipe__TEST__guardrail"
    stage1 = run_root / "stage1_seed"
    stage1.mkdir(parents=True, exist_ok=True)

    dividends = stage1 / "seed_yfinance_dividends_all.csv"
    dividends.write_text(
        "source,underlying,amount,ex_date,pay_date\n"
        "fixture,AAA,1.0,2025-01-01,2025-01-15\n",
        encoding="utf-8",
    )

    no_div = stage1 / "seed_yfinance_no_dividends_all.csv"
    no_div.write_text(
        "source,underlying,underlying_ccy,isin,status,exists_ticker,candidates,start,end\n",
        encoding="utf-8",
    )

    return run_root


def _all_stage2_output_paths(paths: cs.Stage2Paths) -> tuple[Path, ...]:
    return (
        paths.out_rows,
        paths.out_econ,
        paths.out_qa_econ,
        paths.out_qa_rows,
        paths.out_fixture_dbg,
        paths.out_o3_pairs,
        paths.out_qa_o3_pairs,
        paths.out_qa_o3_econ,
        paths.out_rows_br,
        paths.out_rows_nonbr,
        paths.out_no_div_br,
        paths.out_rows_kr,
        paths.out_no_div_kr,
    )


def _patch_guardrail_breach_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_assign_economic_events(
        df: pd.DataFrame,
        respect_existing: bool = False,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "economic_event_id": "E1",
                    "underlying": "AAA",
                    "isin": "US0000000001",
                    "yfinance_ticker": "AAA",
                    "div_ccy": "USD",
                    "amount": 1.0,
                    "ex_date": "2025-01-01",
                    "pay_date": "2025-01-15",
                }
            ]
        )

    def fake_build_outputs(
        *,
        policy,
        rows: pd.DataFrame,
        no_div_all_path: Path,
        o3_max_ex_shift_window_days: int,
    ) -> cs.Stage2ComputedOutputs:
        econ = pd.DataFrame(
            [
                {
                    "economic_event_id": "E1",
                    "severity_tier": 0,
                    "row_count": 3,
                    "amount_nunique": 3,
                    "anchor_spread_days": 0,
                    "ccy_nunique": 1,
                    "pay_date_nunique": 1,
                    "severity_reasons": "amount_nunique(3) >= tier0_amount_unique_ge(3)",
                }
            ]
        )

        qa_econ = econ.copy()

        rows2 = pd.DataFrame(
            [
                {
                    "economic_event_id": "E1",
                    "severity_tier": 0,
                    "underlying": "AAA",
                    "isin": "US0000000001",
                    "yfinance_ticker": "AAA",
                    "div_ccy": "USD",
                }
            ]
        )

        empty_no_div = pd.DataFrame(
            columns=[
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
        )

        return cs.Stage2ComputedOutputs(
            econ=econ,
            qa_econ=qa_econ,
            rows2=rows2,
            pairs_all=pd.DataFrame(),
            fixture_dbg=None,
            rows_br=pd.DataFrame(columns=rows2.columns),
            rows_nonbr=rows2.copy(),
            rows_kr=pd.DataFrame(columns=rows2.columns),
            no_div_br=empty_no_div.copy(),
            no_div_kr=empty_no_div.copy(),
        )

    def fake_apply_o3_workflow_if_any(
        *,
        args,
        rows: pd.DataFrame,
        outputs: cs.Stage2ComputedOutputs,
        policy,
        no_div_all_path: Path,
    ) -> tuple[cs.Stage2ComputedOutputs, pd.DataFrame | None, pd.DataFrame | None, bool]:
        return outputs, None, None, False

    monkeypatch.setattr(cs, "assign_economic_events", fake_assign_economic_events)
    monkeypatch.setattr(cs, "_build_outputs", fake_build_outputs)
    monkeypatch.setattr(cs, "_apply_o3_workflow_if_any", fake_apply_o3_workflow_if_any)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_validate_args_rejects_out_of_range_max_tier0_ratio(value: float) -> None:
    args = cs.build_parser().parse_args(["--max-tier0-ratio", str(value)])

    with pytest.raises(ValueError, match="max-tier0-ratio"):
        cs._validate_args(args)


def test_main_logic_fails_when_tier0_ratio_breaches_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = _make_run_root(tmp_path)
    _patch_guardrail_breach_flow(monkeypatch)

    args = cs.parse_args(
        [
            "--run-root",
            str(run_root),
            "--max-tier0-ratio",
            "0.0",
        ]
    )

    with pytest.raises(cs.Stage2GateError, match="tier0_ratio"):
        cs.main_logic(args)


def test_main_logic_does_not_write_final_stage2_outputs_when_guardrail_breaches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = _make_run_root(tmp_path)
    _patch_guardrail_breach_flow(monkeypatch)

    stage2 = run_root / "stage2_analysis"
    paths = cs._build_stage2_paths(stage2)

    for path in _all_stage2_output_paths(paths):
        assert not path.exists(), f"test precondition failed, artefact already exists: {path}"

    args = cs.parse_args(
        [
            "--run-root",
            str(run_root),
            "--max-tier0-ratio",
            "0.0",
        ]
    )

    with pytest.raises(cs.Stage2GateError):
        cs.main_logic(args)

    for path in _all_stage2_output_paths(paths):
        assert not path.exists(), f"guardrail breach should not persist artefact: {path}"