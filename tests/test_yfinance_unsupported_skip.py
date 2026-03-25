# tests/test_yfinance_unsupported_skip.py

from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("yfinance")


def test_unsupported_override_skips_network() -> None:
    from engine.divpipe.adaptors.yfinance_adaptor import YFinanceAdaptor

    universe = pd.DataFrame(
        [
            {
                "underlying": "FOO",
                "underlying_ccy": "AED",
                "chosen_ticker": "UNSUPPORTED_YF",
                "resolution_reason": "unsupported_vendor:yfinance",
                "resolution_method": "override",
                "isin": "TESTISIN000000",
                "exists_ns": False,
                "exists_bo": False,
            }
        ]
    )

    adaptor = YFinanceAdaptor()
    df, err_df, no_div_df, discovered_df = adaptor.fetch_dividends(
        universe,
        chosen_map_path="",
    )

    assert len(df) == 0
    assert len(err_df) == 0
    assert len(no_div_df) == 1
    assert len(discovered_df) == 1
    assert no_div_df.iloc[0]["status"] == "unsupported_vendor"
    assert discovered_df.iloc[0]["resolution_status"] == "unsupported_vendor"