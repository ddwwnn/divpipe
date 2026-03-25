# tests/test_run_pipeline_lastest.py

from __future__ import annotations

from pathlib import Path

import pandas as pd

import engine.divpipe.run_pipeline as rp
from engine.divpipe.schema.columns import STAGE1_ERRORS_REQUIRED_COLUMNS


def test_main_logic_skips_latest_update_on_partial_failure_by_default(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    holdings = repo_root / "holdings_EEM.csv"
    holdings.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(rp, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(rp, "_get_error_columns", lambda: list(STAGE1_ERRORS_REQUIRED_COLUMNS))

    monkeypatch.setattr(
        rp,
        "load_holdings",
        lambda path, include_zero_weight=False: pd.DataFrame(
            {
                "underlying": ["AAA"],
                "weight": [1.0],
                "underlying_ccy": ["USD"],
            }
        ),
    )
    monkeypatch.setattr(
        rp,
        "build_universe",
        lambda holdings_df: holdings_df.assign(isin="US0000000001"),
    )

    class DummyAdaptor:
        def fetch_dividends(
            self,
            universe: pd.DataFrame,
            *,
            start: str = "",
            end: str = "",
            sleep_sec: float = 0.0,
            progress_every: int = 50,
            exists_lookback_period: str = "5d",
            chosen_map_path: str = "",
            return_details: bool = False,
            isin_search_timeout_sec: float = 10.0,
            isin_quotes_count: int = 10,
            universe_region: str = "EM",
            asof_date: str | None = None,
            max_workers: int = 8,
        ):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    called = {"value": False}

    def fake_update_latest_symlink(out_root: Path) -> None:
        called["value"] = True

    monkeypatch.setattr(rp, "update_latest_symlink", fake_update_latest_symlink)

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "--out",
            "output",
            "--bgn",
            "20250101",
            "--end",
            "20250131",
        ]
    )

    rp.main_logic(args)
    assert called["value"] is False


def test_main_logic_updates_latest_on_partial_failure_when_flag_enabled(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    holdings = repo_root / "holdings_EEM.csv"
    holdings.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(rp, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(rp, "_get_error_columns", lambda: list(STAGE1_ERRORS_REQUIRED_COLUMNS))

    monkeypatch.setattr(
        rp,
        "load_holdings",
        lambda path, include_zero_weight=False: pd.DataFrame(
            {
                "underlying": ["AAA"],
                "weight": [1.0],
                "underlying_ccy": ["USD"],
            }
        ),
    )
    monkeypatch.setattr(
        rp,
        "build_universe",
        lambda holdings_df: holdings_df.assign(isin="US0000000001"),
    )

    class DummyAdaptor:
        def fetch_dividends(
            self,
            universe: pd.DataFrame,
            *,
            start: str = "",
            end: str = "",
            sleep_sec: float = 0.0,
            progress_every: int = 50,
            exists_lookback_period: str = "5d",
            chosen_map_path: str = "",
            return_details: bool = False,
            isin_search_timeout_sec: float = 10.0,
            isin_quotes_count: int = 10,
            universe_region: str = "EM",
            asof_date: str | None = None,
            max_workers: int = 8,
        ):
            raise RuntimeError("forced failure")

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    called = {"value": False}

    def fake_update_latest_symlink(out_root: Path) -> None:
        called["value"] = True

    monkeypatch.setattr(rp, "update_latest_symlink", fake_update_latest_symlink)

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "--publish-latest-on-partial-failure",
            "--out",
            "output",
            "--bgn",
            "20250101",
            "--end",
            "20250131",
        ]
    )

    rp.main_logic(args)
    assert called["value"] is True


def test_main_logic_updates_latest_on_full_success(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    holdings = repo_root / "holdings_EEM.csv"
    holdings.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(rp, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(rp, "_get_error_columns", lambda: list(STAGE1_ERRORS_REQUIRED_COLUMNS))

    monkeypatch.setattr(
        rp,
        "load_holdings",
        lambda path, include_zero_weight=False: pd.DataFrame(
            {
                "underlying": ["AAA"],
                "weight": [1.0],
                "underlying_ccy": ["USD"],
            }
        ),
    )
    monkeypatch.setattr(
        rp,
        "build_universe",
        lambda holdings_df: holdings_df.assign(isin="US0000000001"),
    )

    class DummyAdaptor:
        def fetch_dividends(
            self,
            universe: pd.DataFrame,
            *,
            start: str = "",
            end: str = "",
            sleep_sec: float = 0.0,
            progress_every: int = 50,
            exists_lookback_period: str = "5d",
            chosen_map_path: str = "",
            return_details: bool = False,
            isin_search_timeout_sec: float = 10.0,
            isin_quotes_count: int = 10,
            universe_region: str = "EM",
            asof_date: str | None = None,
            max_workers: int = 8,
        ):
            seed_df = pd.DataFrame(
                {
                    "source": ["yfinance"],
                    "underlying": universe["underlying"].tolist(),
                    "underlying_ccy": universe["underlying_ccy"].tolist(),
                    "isin": universe["isin"].tolist(),
                    "amount": ["1.25"],
                    "ex_date": ["2025-01-15"],
                }
            )
            seed_err = pd.DataFrame(columns=STAGE1_ERRORS_REQUIRED_COLUMNS)
            seed_no_div = pd.DataFrame(columns=[])
            return seed_df, seed_err, seed_no_div, pd.DataFrame()

    monkeypatch.setattr(rp, "_build_stage1_adaptor", lambda: DummyAdaptor())

    called = {"value": False}

    def fake_update_latest_symlink(out_root: Path) -> None:
        called["value"] = True

    monkeypatch.setattr(rp, "update_latest_symlink", fake_update_latest_symlink)

    args = rp.build_parser().parse_args(
        [
            "--holdings",
            str(holdings),
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "--out",
            "output",
            "--bgn",
            "20250101",
            "--end",
            "20250131",
        ]
    )

    rp.main_logic(args)
    assert called["value"] is True
