# tests/test_econ_id_shuffle_invariant.py

from pathlib import Path

import pandas as pd
import pytest

from engine.divpipe.pipeline.link_events import assign_economic_events


def _map_vid_to_eid(df: pd.DataFrame, *, respect_existing: bool = False) -> dict[str, str]:
    x = assign_economic_events(df, respect_existing=respect_existing)

    m = x[["vendor_event_id", "economic_event_id"]].fillna("").astype(str)
    m = m[m["vendor_event_id"].str.strip().ne("")]

    bad = m.groupby("vendor_event_id")["economic_event_id"].nunique()
    assert int((bad > 1).sum()) == 0

    return dict(zip(m["vendor_event_id"], m["economic_event_id"]))


def test_shuffle_invariant_vendor_event_to_econ_event():
    df = pd.read_csv("tests/fixtures/seed_yfinance_dividends_all.csv")
    a = _map_vid_to_eid(df)
    b = _map_vid_to_eid(df.sample(frac=1.0, random_state=7).reset_index(drop=True))
    assert a == b


def test_shuffle_invariant_with_respect_existing():
    path = Path("tests/fixtures/seed_yfinance_dividends_all.csv")
    df = pd.read_csv(path).copy()

    # Inject preset economic_event_id into a subset of rows.
    df.loc[df["vendor_event_id"].isin(["DEMO_VEND_001", "DEMO_VEND_002"]), "economic_event_id"] = "PRESET_X"

    a = _map_vid_to_eid(df, respect_existing=True)
    b = _map_vid_to_eid(df.sample(frac=1.0, random_state=7).reset_index(drop=True), respect_existing=True)

    assert a == b


def test_conflicting_preset_same_vendor_event_id_raises():
    df = pd.read_csv("tests/fixtures/seed_yfinance_dividends_all.csv").copy()

    # Create two rows with the same vendor_event_id but different preset economic_event_id values.
    # (If the fixture does not already contain duplicate vendor_event_id values, duplicate a row to construct the case.)
    r = df.iloc[[0]].copy()
    r2 = r.copy()
    r2["economic_event_id"] = "PRESET_B"
    r["economic_event_id"] = "PRESET_A"
    r2["vendor_event_id"] = r["vendor_event_id"].iloc[0]  # Keep the same vendor_event_id.

    x = pd.concat([df, r, r2], ignore_index=True)

    with pytest.raises(ValueError):
        assign_economic_events(x, respect_existing=True)