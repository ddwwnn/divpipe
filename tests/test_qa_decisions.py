# tests/test_qa_decisions.py

from __future__ import annotations

import pandas as pd

from engine.divpipe.pipeline.overrides import apply_qa_decisions


def _rows_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vendor_event_id": "V1",
                "underlying": "VALE3",
                "ex_date": "2025-12-27",
                "amount": 0.145875,
                "div_ccy": "BRL",
                "economic_event_id": "E_OLD",
            },
            {
                "vendor_event_id": "V1",
                "underlying": "VALE3",
                "ex_date": "2025-12-27",
                "amount": 0.118401,
                "div_ccy": "BRL",
                "economic_event_id": "E_OLD",
            },
            {
                "vendor_event_id": "V2",
                "underlying": "PETR4",
                "ex_date": "2025-01-15",
                "amount": 0.10,
                "div_ccy": "BRL",
                "economic_event_id": "E_KEEP",
            },
        ]
    )


def _base_override_cols() -> dict:
    # apply_qa_decisions() does not strictly require action/economic_event_id/anchor_date/note,
    # but we include these columns to align with the loader schema and keep fixtures consistent.
    return {"anchor_date": "", "note": ""}


def test_override_drop_exact_match() -> None:
    rows = _rows_df()

    overrides = pd.DataFrame(
        [
            {
                "vendor_event_id": "V2",
                "underlying": "PETR4",
                "ex_date": "2025-01-15",
                "action": "DROP",
                "amount": 0.10,
                "div_ccy": "BRL",
                "economic_event_id": "",
                **_base_override_cols(),
            }
        ]
    )

    out = apply_qa_decisions(rows, overrides)
    assert (out["vendor_event_id"] == "V2").sum() == 0
    assert len(out) == 2


def test_override_set_econ_id_wildcard_amount_ccy_blank() -> None:
    rows = _rows_df()

    overrides = pd.DataFrame(
        [
            {
                "vendor_event_id": "V1",
                "underlying": "VALE3",
                "ex_date": "2025-12-27",
                "action": "SET_ECON_ID",
                # Wildcard: blank amount/div_ccy must match BOTH V1 rows.
                "amount": "",
                "div_ccy": "",
                "economic_event_id": "E_NEW",
                **_base_override_cols(),
            }
        ]
    )

    out = apply_qa_decisions(rows, overrides)

    v1 = out[out["vendor_event_id"] == "V1"]
    assert len(v1) == 2
    assert set(v1["economic_event_id"].tolist()) == {"E_NEW"}

    v2 = out[out["vendor_event_id"] == "V2"]
    assert set(v2["economic_event_id"].tolist()) == {"E_KEEP"}


def test_override_set_econ_id_exact_match_amount_ccy() -> None:
    rows = _rows_df()

    overrides = pd.DataFrame(
        [
            {
                "vendor_event_id": "V1",
                "underlying": "VALE3",
                "ex_date": "2025-12-27",
                "action": "SET_ECON_ID",
                "amount": 0.145875,
                "div_ccy": "BRL",
                "economic_event_id": "E_ONLY_ONE",
                **_base_override_cols(),
            }
        ]
    )

    out = apply_qa_decisions(rows, overrides)

    r_exact = out[(out["vendor_event_id"] == "V1") & (out["amount"] == 0.145875)]
    r_other = out[(out["vendor_event_id"] == "V1") & (out["amount"] == 0.118401)]

    assert set(r_exact["economic_event_id"].tolist()) == {"E_ONLY_ONE"}
    assert set(r_other["economic_event_id"].tolist()) == {"E_OLD"}