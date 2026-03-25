from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from providers.ishares_normaliser import latest_raw_file, normalise_ishares_json


def test_latest_raw_file_picks_latest_json(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    (raw_dir / "20260319_EEM.json").write_text("{}", encoding="utf-8")
    (raw_dir / "20260320_EEM.json").write_text("{}", encoding="utf-8")

    got = latest_raw_file("EEM", raw_dir=raw_dir)
    assert got.name == "20260320_EEM.json"


def test_normalise_ishares_json_outputs_holdings_contract(tmp_path: Path) -> None:
    raw_path = tmp_path / "20260320_EEM.json"
    out_path = tmp_path / "holdings_EEM.csv"

    payload = {
        "aaData": [
            [
                "2330",
                "TAIWAN SEMICONDUCTOR MANUFACTURING",
                "Information Technology",
                "Equity",
                {"display": "$3,535,847,433.77", "raw": 3535847433.77},
                {"display": "60.00", "raw": 60.0},
                {"display": "3,535,847,433.77", "raw": 3535847433.77},
                {"display": "61,109,000.00", "raw": 61109000},
                "S68891068",
                "TW0002330008",
                "6889106",
                {"display": "57.86", "raw": 57.86},
                "Taiwan",
                "Taiwan Stock Exchange",
                "TWD",
                "31.97",
                "Nov 10, 1994",
            ],
            [
                "005930",
                "SAMSUNG ELECTRONICS",
                "Information Technology",
                "Equity",
                {"display": "$2,000,000,000.00", "raw": 2000000000.0},
                {"display": "40.00", "raw": 40.0},
                {"display": "2,000,000,000.00", "raw": 2000000000.0},
                {"display": "10,000,000.00", "raw": 10000000},
                "",
                "KR7005930003",
                "6771720",
                {"display": "200.00", "raw": 200.0},
                "Korea",
                "Korea Exchange",
                "KRW",
                "1300.0",
                "Jan 01, 2000",
            ],
        ]
    }

    raw_path.write_text(json.dumps(payload), encoding="utf-8")

    normalise_ishares_json(
        raw_path=raw_path,
        etf_symbol="EEM",
        out_full_path=out_path,
    )

    df = pd.read_csv(out_path, encoding="utf-8-sig", dtype={"underlying": "string", "isin": "string"})
    assert {"underlying", "weight", "underlying_ccy", "isin"}.issubset(df.columns)
    assert len(df) == 2
    assert abs(df["weight"].sum() - 1.0) < 1e-9
    assert set(df["underlying"]) == {"2330", "005930"}
    assert set(df["isin"]) == {"TW0002330008", "KR7005930003"}
