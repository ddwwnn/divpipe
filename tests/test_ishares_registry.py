from __future__ import annotations

import pytest

from providers.ishares_registry import (
    ISHARES_BASE_URL,
    get_fund_spec,
    get_registered_etfs,
)


def test_get_registered_etfs_contains_known_symbols() -> None:
    etfs = get_registered_etfs()
    assert "EEM" in etfs
    assert "EFA" in etfs
    assert etfs == sorted(etfs)


def test_get_fund_spec_returns_expected_spec() -> None:
    spec = get_fund_spec("eem")
    assert spec.symbol == "EEM"
    assert spec.product_path == "239637/ishares-msci-emerging-markets-etf"
    assert spec.default_coverage == "EM"
    assert spec.product_url == f"{ISHARES_BASE_URL}/239637/ishares-msci-emerging-markets-etf"


def test_get_fund_spec_unknown_symbol_raises() -> None:
    with pytest.raises(ValueError, match="Unknown ETF"):
        get_fund_spec("XXX")
