# tests/test_o3_decisions.py

import pandas as pd

from scripts.check_severity import (
    _apply_o3_merges_to_rows,
    _apply_o3_suppression,
    _build_o3_merge_map,
    _o3_pair_key,
)


def test_o3_pair_key_order_independent():
    assert _o3_pair_key("B", "A") == "A||B"
    assert _o3_pair_key("A", "B") == "A||B"
    assert _o3_pair_key("A", "A") == "A||A"

def test_apply_o3_suppression_removes_reviewed_keep_pairs():
    qa_pairs = pd.DataFrame([
        {"econ_id_a": "A", "econ_id_b": "B", "underlying": "X"},
        {"econ_id_a": "C", "econ_id_b": "D", "underlying": "X"},
    ])
    decisions = pd.DataFrame([
        {"enabled": "true", "underlying": "X", "econ_id_a": "B", "econ_id_b": "A", "decision": "KEEP", "canonical_econ_id": "", "note": ""},
    ])

    out = _apply_o3_suppression(qa_pairs, decisions)
    assert len(out) == 1
    assert out.iloc[0]["econ_id_a"] == "C"
    assert out.iloc[0]["econ_id_b"] == "D"

def test_build_o3_merge_map_transitive_closure():
    decisions = pd.DataFrame([
        {"enabled": "true", "underlying": "X", "econ_id_a": "A", "econ_id_b": "B", "decision": "MERGE", "canonical_econ_id": "", "note": ""},
        {"enabled": "true", "underlying": "X", "econ_id_a": "B", "econ_id_b": "C", "decision": "MERGE", "canonical_econ_id": "", "note": ""},
    ])
    m = _build_o3_merge_map(decisions)
    # b->a, c->b->a
    assert m["B"] == "A"
    assert m["C"] == "A"

def test_apply_o3_merges_to_rows_rewrites_econ_ids():
    rows = pd.DataFrame([
        {"economic_event_id": "A", "x": 1},
        {"economic_event_id": "B", "x": 2},
        {"economic_event_id": "C", "x": 3},
    ])
    merge_map = {"B": "A", "C": "A"}
    out = _apply_o3_merges_to_rows(rows, merge_map)
    assert out["economic_event_id"].tolist() == ["A", "A", "A"]