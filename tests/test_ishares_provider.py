from __future__ import annotations

import json
from pathlib import Path

import pytest

from providers.ishares_provider import (
    _aa_data_to_csv_bytes,
    _clean_float,
    _clean_text,
    _discover_holdings_json_url_and_asof,
    _latest_raw_version_path,
    _load_ishares_json_with_bom,
    _next_raw_version_path,
    _parse_json_asof_date,
    parse_args,
)


class DummyResponse:
    def __init__(self, *, content: bytes, status_code: int = 200, headers: dict[str, str] | None = None) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        return None


def test_ishares_provider_parser_accepts_registered_etfs() -> None:
    args = parse_args(["--etf", "EEM", "EFA"])
    assert args.etf == ["EEM", "EFA"]


def test_ishares_provider_parser_default_out() -> None:
    args = parse_args(["--etf", "EEM"])
    assert args.out == "data/raw/ishares"


def test_parse_json_asof_date() -> None:
    assert _parse_json_asof_date("Mar 20, 2026") == "20260320"
    assert _parse_json_asof_date("2026-03-20") == "20260320"


def test_clean_text_and_float() -> None:
    assert _clean_text({"raw": "ABC"}) == "ABC"
    assert _clean_text({"display": "XYZ"}) == "XYZ"
    assert _clean_text(None) == ""

    assert _clean_float({"raw": 12.34}) == "12.34"
    assert _clean_float({"display": "$1,234.56"}) == "1234.56"
    assert _clean_float("7.5") == "7.5"
    assert _clean_float("") == ""


def test_load_ishares_json_with_bom() -> None:
    payload = json.dumps({"aaData": [["2330", "TSMC"]]}).encode("utf-8-sig")
    resp = DummyResponse(content=payload)
    data = _load_ishares_json_with_bom(resp, symbol="EEM", json_url="https://example.com/test.json")
    assert "aaData" in data
    assert data["aaData"][0][0] == "2330"


def test_load_ishares_json_with_bom_rejects_non_json() -> None:
    resp = DummyResponse(content=b"<html>nope</html>", headers={"content-type": "text/html"})
    with pytest.raises(ValueError, match="Non-JSON iShares payload"):
        _load_ishares_json_with_bom(resp, symbol="EEM", json_url="https://example.com/test.json")


def test_discover_holdings_json_url_and_asof(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html>
      <body>
        <a href="/us/products/239637/ishares-msci-emerging-markets-etf/1467271812596.ajax?tab=all&amp;fileType=json">holdings</a>
        <div>as of Mar 20, 2026</div>
      </body>
    </html>
    """

    class HtmlResponse:
        text = html

        def raise_for_status(self) -> None:
            return None

    def fake_get(*args, **kwargs):
        return HtmlResponse()

    monkeypatch.setattr("providers.ishares_provider.requests.get", fake_get)

    url, asof = _discover_holdings_json_url_and_asof(
        "https://www.ishares.com/us/products/239637/ishares-msci-emerging-markets-etf"
    )
    assert url == "https://www.ishares.com/us/products/239637/ishares-msci-emerging-markets-etf/1467271812596.ajax?tab=all&fileType=json"
    assert asof == "20260320"


def test_aa_data_to_csv_bytes() -> None:
    aa_data = [
        [
            "2330",
            "TAIWAN SEMICONDUCTOR MANUFACTURING",
            "Information Technology",
            "Equity",
            {"display": "$3,535,847,433.77", "raw": 3535847433.77},
            {"display": "13.21", "raw": 13.21409},
            {"display": "3,535,847,433.77", "raw": 3535847433.77},
            {"display": "61,109,000.00", "raw": 61109000},
            "S68891068",
            "TW0002330008",
            "6889106",
            {"display": "57.86", "raw": 57.86},
            "Taiwan",
            "Taiwan Stock Exchange",
            "USD",
            "31.97",
            "Nov 10, 1994",
        ]
    ]
    payload = _aa_data_to_csv_bytes(aa_data=aa_data, symbol="EEM", asof_yyyymmdd="20260320")
    text = payload.decode("utf-8-sig")
    assert "Fund Holdings as of" in text
    assert "2330,TAIWAN SEMICONDUCTOR MANUFACTURING" in text
    assert "TW0002330008" in text


def test_next_raw_version_path_picks_next_number(tmp_path: Path) -> None:
    bucket = tmp_path / "EEM" / "20260320"
    bucket.mkdir(parents=True, exist_ok=True)
    (bucket / "raw_1.json").write_text("a", encoding="utf-8")
    (bucket / "raw_2.json").write_text("b", encoding="utf-8")
    (bucket / "raw_5.json").write_text("c", encoding="utf-8")

    out = _next_raw_version_path(bucket, suffix=".json")
    assert out.name == "raw_6.json"


def test_latest_raw_version_path_picks_highest_numeric_suffix(tmp_path: Path) -> None:
    bucket = tmp_path / "EEM" / "20260320"
    bucket.mkdir(parents=True, exist_ok=True)
    (bucket / "raw_1.json").write_text("a", encoding="utf-8")
    (bucket / "raw_2.json").write_text("b", encoding="utf-8")
    (bucket / "raw_10.json").write_text("c", encoding="utf-8")

    out = _latest_raw_version_path(bucket, suffix=".json")
    assert out is not None
    assert out.name == "raw_10.json"


def test_latest_raw_version_path_returns_none_for_empty_bucket(tmp_path: Path) -> None:
    bucket = tmp_path / "EEM" / "20260320"
    bucket.mkdir(parents=True, exist_ok=True)

    out = _latest_raw_version_path(bucket, suffix=".json")
    assert out is None
