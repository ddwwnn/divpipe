# tests/test_run_pipeline_resolution.py

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import engine.divpipe.run_pipeline as rp



def test_resolve_tags_requires_explicit_opt_in_for_inference() -> None:
    with pytest.raises(ValueError, match="--tags is required unless --allow-tag-inference is explicitly set"):
        rp._resolve_tags([Path("holdings_EEM.csv")], None, allow_inference=False)

def test_infer_tag_prefers_registry_match(monkeypatch) -> None:
    monkeypatch.setattr(rp, "_known_etf_tags", lambda: {"EEM", "EFA", "IVV"})

    assert rp._infer_tag(Path("data/holdings_EEM.csv")) == "EEM"
    assert rp._infer_tag(Path("foo/bar/ivv_holdings_full.csv")) == "IVV"
    assert rp._infer_tag(Path("foo/custom_tag_file.csv")) == "CUSTOM"


def test_infer_tag_ignores_date_like_token(monkeypatch) -> None:
    monkeypatch.setattr(rp, "_known_etf_tags", lambda: {"EEM", "EFA", "IVV"})
    assert rp._infer_tag(Path("data/20260317_EEM.csv")) == "EEM"


def test_infer_tag_fallback_skips_generic_noise_and_date_token(monkeypatch) -> None:
    monkeypatch.setattr(rp, "_known_etf_tags", lambda: set())
    assert rp._infer_tag(Path("foo/20260317_custom_holdings.csv")) == "CUSTOM"


def test_resolve_tags_prefers_explicit_tags() -> None:
    holdings = [Path("a.csv"), Path("b.csv")]
    tags = rp._resolve_tags(holdings, ["eem", "efa"])
    assert tags == ["EEM", "EFA"]


def test_resolve_tags_raises_when_inference_fails(monkeypatch) -> None:
    monkeypatch.setattr(rp, "_known_etf_tags", lambda: set())

    with pytest.raises(ValueError, match="Could not infer tag"):
        rp._resolve_tags([Path("___---.csv")], None)


def test_resolve_regions_prefers_explicit_regions() -> None:
    regions = rp._resolve_regions(["EEM", "EFA"], ["em", "dm"])
    assert regions == ["EM", "DM"]


def test_resolve_regions_raises_when_registry_cannot_infer(monkeypatch) -> None:
    monkeypatch.setattr(rp, "_infer_universe_region", lambda tag: None)

    with pytest.raises(ValueError, match="Could not infer regions"):
        rp._resolve_regions(["CUSTOM"], None)


def test_validate_args_fails_fast_on_bad_bgn() -> None:
    args = rp.build_parser().parse_args(
        [
            "--holdings",
            "a.csv",
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "--bgn",
            "2025-01-01",
            "--end",
            "20250131",
        ]
    )

    with pytest.raises(ValueError, match="--bgn"):
        rp._validate_args(args)


def test_validate_args_fails_fast_on_bad_end() -> None:
    args = rp.build_parser().parse_args(
        [
            "--holdings",
            "a.csv",
            "--tags",
            "EEM",
            "--regions",
            "EM",
            "--bgn",
            "20250101",
            "--end",
            "2025-01-31",
        ]
    )

    with pytest.raises(ValueError, match="--end"):
        rp._validate_args(args)


def test_should_publish_latest_default_policy() -> None:
    ok = rp.Stage1TagResult(
        tag="EEM",
        holdings_path=Path("holdings_EEM.csv"),
        universe_region="EM",
        stage_dir=Path("stage1_seed/EEM"),
        universe_rows=10,
        seed_df=pd.DataFrame({"x": [1]}),
        err_df=pd.DataFrame(),
        no_div_df=pd.DataFrame(),
        failed=False,
        started_at="2026-03-17T00:00:00Z",
        finished_at="2026-03-17T00:00:01Z",
        elapsed_seconds=1.0,
        error=None,
    )
    bad = rp.Stage1TagResult(
        tag="EFA",
        holdings_path=Path("holdings_EFA.csv"),
        universe_region="DM",
        stage_dir=Path("stage1_seed/EFA"),
        universe_rows=0,
        seed_df=None,
        err_df=None,
        no_div_df=None,
        failed=True,
        started_at="2026-03-17T00:00:02Z",
        finished_at="2026-03-17T00:00:02Z",
        elapsed_seconds=0.0,
        error="boom",
    )

    assert rp._should_publish_latest([ok], publish_on_partial_failure=False) is True
    assert rp._should_publish_latest([ok, bad], publish_on_partial_failure=False) is False
    assert rp._should_publish_latest([ok, bad], publish_on_partial_failure=True) is True
