# src/engine/divpipe/pipeline/ticker_qa.py

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypedDict

import pandas as pd

from .ticker_resolution_canonical import FAILURE_STATUSES

_REQUIRED_INPUT_COLUMNS = [
    "underlying",
    "underlying_ccy",
    "chosen_ticker",
    "resolution_status",
]

_EMPTY_REPORT_COLUMNS = [
    "underlying",
    "underlying_ccy",
    "isin",
    "chosen_ticker",
    "candidate_market",
    "candidate_origin",
    "resolution_status",
    "resolution_reason",
    "resolution_method",
    "resolution_source",
    "candidate_count",
    "candidates_json",
    "exists_ticker",
    "exists_ns",
    "exists_bo",
    "is_failed",
]

_DIAGNOSTIC_REPORT_COLUMNS = [
    "mapping_issue_class",
    "candidate_list_pretty",
    "candidate_suffixes",
]

_EXTRA_REPORT_COLUMNS = [
    "holdings_tag",
    "holdings_file",
    "source",
    "start",
    "end",
    "guess_source",
    "canonical_exchange",
    "isin_prefix",
    "prefix_exchange_consistent",
    "weight",
    "weight_matched",
    "weight_match_method",
    "is_anomaly",
]

ANOMALY_GUESS_SOURCES = {"CCY_FALLBACK"}
_WEIGHT_MATCH_METHOD_EXACT = "exact_underlying_ccy_isin"
_WEIGHT_MATCH_METHOD_FALLBACK = "fallback_underlying_ccy"
_WEIGHT_MATCH_METHOD_UNMATCHED = "unmatched"
_DEFAULT_EPSILON = 1e-12

_FAILURE_STATUSES_EXTENDED = {str(x).strip().upper() for x in FAILURE_STATUSES} | {
    "NOT_FOUND",
    "TICKER_NOT_FOUND",
    "AMBIGUOUS",
    "UNSUPPORTED_VENDOR",
    "ERROR",
    "CANDIDATE_UNVERIFIED",
}

_STRICT_ISIN_SG_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]\.SG$")
_PLAIN_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")

_FALSE_LIKE = {"", "NA", "NAN", "NONE", "<NA>", "-", "FALSE", "F", "NO", "N", "0"}
_TRUE_LIKE = {"TRUE", "T", "YES", "Y", "1"}
_NULL_LIKE = _FALSE_LIKE


class UniverseWeightMaps(TypedDict):
    exact: pd.DataFrame
    fallback: pd.DataFrame
    combined: pd.DataFrame


@dataclass(frozen=True)
class MaterialityGateResult:
    failed_rows: int
    anomaly_rows: int
    failed_weight_sum: float
    anomaly_weight_sum: float
    max_failed_weight: float
    unmatched_failed_count: int
    unmatched_failed_weight_sum: float


class TickerMapMaterialityError(RuntimeError):
    pass


def _empty_report_frame() -> pd.DataFrame:
    out = pd.DataFrame(columns=_EMPTY_REPORT_COLUMNS)
    out["candidate_count"] = pd.Series(dtype="int64")
    out["exists_ns"] = pd.Series(dtype="bool")
    out["exists_bo"] = pd.Series(dtype="bool")
    out["is_failed"] = pd.Series(dtype="bool")
    return out.reindex(columns=_EMPTY_REPORT_COLUMNS)


def _clean_text_series(s: pd.Series, *, upper: bool = False) -> pd.Series:
    out = s.astype("string").fillna("").str.strip()
    out = out.replace(
        {
            "<NA>": "",
            "None": "",
            "none": "",
            "nan": "",
            "NaN": "",
            "NONE": "",
            "NAN": "",
        }
    )
    if upper:
        out = out.str.upper()
    return out


def _normalise_int_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0] * len(df), index=df.index, dtype="int64")
    out = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return out.astype("int64")


def _normalise_bool_col(df: pd.DataFrame, col: str, *, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype="bool")

    raw = _clean_text_series(df[col], upper=True)
    invalid = ~(raw.isin(_FALSE_LIKE | _TRUE_LIKE))
    if invalid.any():
        sample = ", ".join(raw.loc[invalid].head(5).tolist())
        raise ValueError(f"invalid values in {col}: {sample}")

    values = raw.isin(_TRUE_LIKE)
    return pd.Series(values, index=df.index, dtype="bool")


def _normalise_nullable_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.array([pd.NA] * len(df), dtype="boolean"), index=df.index)

    raw = df[col]
    out = pd.Series(pd.array([pd.NA] * len(df), dtype="boolean"), index=df.index)

    null_mask = raw.isna()

    text = raw.astype("string").fillna("").str.strip().str.upper()

    true_mask = text.isin(_TRUE_LIKE)
    false_mask = text.isin(_FALSE_LIKE - {"", "NA", "NAN", "NONE", "<NA>", "-"})

    out.loc[true_mask] = True
    out.loc[false_mask] = False
    out.loc[null_mask] = pd.NA
    out.loc[text.isin({"", "NA", "NAN", "NONE", "<NA>", "-"})] = pd.NA

    return out


def _derive_legacy_exists_flags(preverified_exists_ticker: pd.Series) -> tuple[pd.Series, pd.Series]:
    ticker = _clean_text_series(preverified_exists_ticker, upper=True)
    exists_ns = ticker.str.endswith(".NS").astype("bool")
    exists_bo = ticker.str.endswith(".BO").astype("bool")
    return exists_ns, exists_bo


def _validate_required_columns(df: pd.DataFrame) -> None:
    missing = [col for col in _REQUIRED_INPUT_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"ticker map df missing required columns: {missing}")


def _ensure_optional_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    defaults: dict[str, Any] = {
        "isin": "",
        "candidate_market": "",
        "candidate_origin": "",
        "resolution_reason": "",
        "resolution_method": "",
        "resolution_source": "",
        "reason": "",
        "method": "",
        "candidate_count": 0,
        "candidates_json": "",
        "exists_ticker": "",
        "preverified_exists_any": False,
        "preverified_exists_ticker": "",
        "exists_ns": False,
        "exists_bo": False,
        "holdings_tag": "",
        "holdings_file": "",
        "source": "",
        "start": "",
        "end": "",
        "guess_source": "",
        "canonical_exchange": "",
        "isin_prefix": "",
        "prefix_exchange_consistent": pd.NA,
    }

    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    return out


def _normalise_universe_df(universe_df: pd.DataFrame | None) -> pd.DataFrame:
    if universe_df is None or universe_df.empty:
        return pd.DataFrame(columns=["underlying", "underlying_ccy", "isin", "weight"])

    out = universe_df.copy()

    for col in ["underlying", "underlying_ccy", "isin", "weight"]:
        if col not in out.columns:
            out[col] = ""

    out["underlying"] = _clean_text_series(out["underlying"], upper=True)
    out["underlying_ccy"] = _clean_text_series(out["underlying_ccy"], upper=True)
    out["isin"] = _clean_text_series(out["isin"], upper=True)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0).astype("float64")

    return out


def prepare_universe_weight_maps(universe_df: pd.DataFrame | None) -> UniverseWeightMaps:
    uni = _normalise_universe_df(universe_df)

    if uni.empty:
        exact = pd.DataFrame(columns=["underlying", "underlying_ccy", "isin", "weight_exact"])
        fallback = pd.DataFrame(columns=["underlying", "underlying_ccy", "weight_fallback"])
        combined = pd.DataFrame(
            columns=["underlying", "underlying_ccy", "isin", "weight_exact", "weight_fallback"]
        )
        return UniverseWeightMaps(
            exact=exact,
            fallback=fallback,
            combined=combined,
        )

    exact = (
        uni.groupby(["underlying", "underlying_ccy", "isin"], dropna=False, as_index=False)["weight"]
        .sum()
        .rename(columns={"weight": "weight_exact"})
    )

    fallback = (
        uni.groupby(["underlying", "underlying_ccy"], dropna=False, as_index=False)["weight"]
        .sum()
        .rename(columns={"weight": "weight_fallback"})
    )

    combined = exact.merge(
        fallback,
        on=["underlying", "underlying_ccy"],
        how="outer",
    )

    return UniverseWeightMaps(
        exact=exact,
        fallback=fallback,
        combined=combined,
    )


def _resolve_universe_weight_frame(
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if isinstance(universe_maps, pd.DataFrame):
        return universe_maps.copy()

    if isinstance(universe_maps, Mapping):
        if "combined" in universe_maps and isinstance(universe_maps["combined"], pd.DataFrame):
            return universe_maps["combined"].copy()

        if "exact" in universe_maps and "fallback" in universe_maps:
            return universe_maps["exact"].merge(
                universe_maps["fallback"],
                on=["underlying", "underlying_ccy"],
                how="outer",
            )

    return prepare_universe_weight_maps(universe_df)["combined"]


def _merge_report_weights(
    report_df: pd.DataFrame,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    out = report_df.copy()
    uni = _resolve_universe_weight_frame(
        universe_df=universe_df,
        universe_maps=universe_maps,
    )

    if uni.empty:
        out["weight"] = pd.Series([0.0] * len(out), index=out.index, dtype="float64")
        out["weight_match_method"] = pd.Series(
            [_WEIGHT_MATCH_METHOD_UNMATCHED] * len(out),
            index=out.index,
            dtype="string",
        )
        out["weight_matched"] = pd.Series([False] * len(out), index=out.index, dtype="bool")
        return out

    for col in ["underlying", "underlying_ccy", "isin"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = _clean_text_series(out[col], upper=True)

    uni = uni.copy()
    uni["underlying"] = _clean_text_series(uni["underlying"], upper=True)
    uni["underlying_ccy"] = _clean_text_series(uni["underlying_ccy"], upper=True)
    uni["isin"] = _clean_text_series(uni["isin"], upper=True)

    exact_weights = (
        uni[["underlying", "underlying_ccy", "isin", "weight_exact"]]
        .drop_duplicates(subset=["underlying", "underlying_ccy", "isin"])
    )
    fallback_weights = (
        uni[["underlying", "underlying_ccy", "weight_fallback"]]
        .drop_duplicates(subset=["underlying", "underlying_ccy"])
    )

    merged = out.merge(
        exact_weights,
        on=["underlying", "underlying_ccy", "isin"],
        how="left",
    )

    merged = merged.merge(
        fallback_weights,
        on=["underlying", "underlying_ccy"],
        how="left",
    )

    weight_exact = pd.to_numeric(merged["weight_exact"], errors="coerce")
    weight_fallback = pd.to_numeric(merged["weight_fallback"], errors="coerce")

    has_exact = weight_exact.notna()
    has_fallback = weight_fallback.notna()

    merged["weight"] = weight_exact.where(has_exact, weight_fallback).fillna(0.0).astype("float64")
    merged["weight_match_method"] = _WEIGHT_MATCH_METHOD_UNMATCHED
    merged.loc[has_fallback, "weight_match_method"] = _WEIGHT_MATCH_METHOD_FALLBACK
    merged.loc[has_exact, "weight_match_method"] = _WEIGHT_MATCH_METHOD_EXACT
    merged["weight_matched"] = merged["weight_match_method"].ne(_WEIGHT_MATCH_METHOD_UNMATCHED).astype("bool")

    return merged.drop(columns=["weight_exact", "weight_fallback"], errors="ignore")


def summarise_weight_match_diagnostics(report_df: pd.DataFrame | None) -> dict[str, Any]:
    if report_df is None or report_df.empty:
        return {
            "report_rows": 0,
            "exact_match_rows": 0,
            "fallback_match_rows": 0,
            "unmatched_rows": 0,
            "exact_weight_sum": 0.0,
            "fallback_weight_sum": 0.0,
            "unmatched_weight_sum": 0.0,
            "fallback_distinct_keys": 0,
            "fallback_duplicate_rows": 0,
            "has_fallback_duplication_risk": False,
            "weight_match_warning": "",
        }

    out = report_df.copy()

    weight_match_method = _clean_text_series(
        out.get("weight_match_method", pd.Series(index=out.index, dtype="string"))
    )
    weight = pd.to_numeric(out.get("weight", 0.0), errors="coerce").fillna(0.0)

    exact_mask = weight_match_method.eq(_WEIGHT_MATCH_METHOD_EXACT)
    fallback_mask = weight_match_method.eq(_WEIGHT_MATCH_METHOD_FALLBACK)
    unmatched_mask = weight_match_method.eq(_WEIGHT_MATCH_METHOD_UNMATCHED)

    fallback_keys = (
        out.loc[fallback_mask, ["underlying", "underlying_ccy"]]
        .astype("string")
        .fillna("")
        .drop_duplicates()
    )

    fallback_duplicate_rows = max(0, int(fallback_mask.sum()) - int(len(fallback_keys)))
    has_fallback_duplication_risk = fallback_duplicate_rows > 0
    weight_match_warning = (
        "fallback weight may be attached to multiple report rows"
        if has_fallback_duplication_risk
        else ""
    )

    return {
        "report_rows": int(len(out)),
        "exact_match_rows": int(exact_mask.sum()),
        "fallback_match_rows": int(fallback_mask.sum()),
        "unmatched_rows": int(unmatched_mask.sum()),
        "exact_weight_sum": float(weight.loc[exact_mask].sum()),
        "fallback_weight_sum": float(weight.loc[fallback_mask].sum()),
        "unmatched_weight_sum": float(weight.loc[unmatched_mask].sum()),
        "fallback_distinct_keys": int(len(fallback_keys)),
        "fallback_duplicate_rows": int(fallback_duplicate_rows),
        "has_fallback_duplication_risk": has_fallback_duplication_risk,
        "weight_match_warning": weight_match_warning,
    }


def validate_weight_match_diagnostics(
    report_df: pd.DataFrame | None,
    *,
    allow_fallback_duplicate_rows: bool = True,
) -> dict[str, Any]:
    diagnostics = summarise_weight_match_diagnostics(report_df)

    if not allow_fallback_duplicate_rows and diagnostics["fallback_duplicate_rows"] > 0:
        raise TickerMapMaterialityError(
            "ticker QA weight-match diagnostic failed: duplicated fallback-attached rows present "
            f"(fallback_duplicate_rows={diagnostics['fallback_duplicate_rows']}, "
            f"fallback_match_rows={diagnostics['fallback_match_rows']}, "
            f"fallback_distinct_keys={diagnostics['fallback_distinct_keys']})"
        )

    return diagnostics


def summarise_ticker_qa_with_weight_diagnostics(report_df: pd.DataFrame | None) -> dict[str, Any]:
    base = summarise_ticker_qa(report_df)
    weight_diag = summarise_weight_match_diagnostics(report_df)
    return base | weight_diag


def _derive_failure_mask(out: pd.DataFrame) -> pd.Series:
    chosen_blank = out["chosen_ticker"].eq("")
    status = _clean_text_series(out["resolution_status"], upper=True)
    exists_ticker = _clean_text_series(out["exists_ticker"])

    no_div_ok = status.isin({"NO_DIVIDENDS_IN_WINDOW", "VERIFIED_EXISTS_BUT_NO_DIVIDENDS"}) & exists_ticker.ne("")
    success_like = status.isin({"SUCCESS", "DIV_FOUND", "MANUAL_OVERRIDE"}) & exists_ticker.ne("")
    explicit_failure = status.isin(_FAILURE_STATUSES_EXTENDED)
    fallback_failure = (~success_like) & (~no_div_ok) & exists_ticker.eq("")

    return ((chosen_blank | explicit_failure | fallback_failure) & (~no_div_ok)).astype("bool")


def _derive_anomaly_mask(out: pd.DataFrame) -> pd.Series:
    guess_source = _clean_text_series(out["guess_source"], upper=True)
    prefix_exchange_consistent = _normalise_nullable_bool_col(out, "prefix_exchange_consistent")

    bad_prefix = prefix_exchange_consistent.eq(False).fillna(False)
    risky_guess_source = guess_source.isin(ANOMALY_GUESS_SOURCES)

    return (bad_prefix | risky_guess_source).astype("bool")


def _parse_candidates_json(raw: Any) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]

    text = str(raw).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass

    return []


def _candidate_suffix_label(ticker: str) -> str:
    text = str(ticker).strip().upper()
    if not text:
        return ""

    if "." not in text:
        return "US/PLAIN"

    return text.rsplit(".", 1)[-1]


def _is_plain_ticker(ticker: str) -> bool:
    text = str(ticker).strip().upper()
    if not text or "." in text:
        return False
    return bool(_PLAIN_TICKER_RE.fullmatch(text))


def _split_ticker_suffix(ticker: str) -> tuple[str, str]:
    text = str(ticker).strip().upper()
    if not text:
        return "", ""
    if "." not in text:
        return text, ""
    base, suffix = text.rsplit(".", 1)
    return base, suffix


def _classify_isin_sg_alias_pollution(candidates: list[str], _: str, candidate_count: int) -> str | None:
    if candidate_count < 2:
        return None

    cand_u = [str(x).strip().upper() for x in candidates if str(x).strip()]
    has_isin_sg = any(_STRICT_ISIN_SG_RE.fullmatch(x) for x in cand_u)
    has_non_sg = any(not x.endswith(".SG") for x in cand_u)
    return "isin_sg_alias_pollution" if has_isin_sg and has_non_sg else None


def _classify_india_ns_bo_dual(candidates: list[str], _: str, candidate_count: int) -> str | None:
    if candidate_count < 2:
        return None

    cand_u = [str(x).strip().upper() for x in candidates if str(x).strip()]
    has_ns = any(x.endswith(".NS") for x in cand_u)
    has_bo = any(x.endswith(".BO") for x in cand_u)
    return "india_ns_bo_dual" if has_ns and has_bo else None


def _classify_plain_plus_local_alt(candidates: list[str], _: str, candidate_count: int) -> str | None:
    if candidate_count < 2:
        return None

    cand_u = [str(x).strip().upper() for x in candidates if str(x).strip()]
    plain = [x for x in cand_u if _is_plain_ticker(x)]
    local = [x for x in cand_u if "." in x]
    return "plain_plus_local_alt" if plain and local else None


def _classify_same_venue_alias(candidates: list[str], _: str, candidate_count: int) -> str | None:
    if candidate_count < 2:
        return None

    cand_u = [str(x).strip().upper() for x in candidates if str(x).strip()]
    suffixes = [_split_ticker_suffix(x)[1] for x in cand_u if "." in x]
    non_blank_suffixes = [x for x in suffixes if x]
    if non_blank_suffixes and len(set(non_blank_suffixes)) == 1:
        return "same_venue_alias"
    return None


def _classify_single_candidate_no_div(_: list[str], resolution_status: str, candidate_count: int) -> str | None:
    if candidate_count == 1 and str(resolution_status).strip().upper() == "VERIFIED_EXISTS_BUT_NO_DIVIDENDS":
        return "single_candidate_no_div"
    return None


_ISSUE_CLASSIFIERS: tuple[Callable[[list[str], str, int], str | None], ...] = (
    _classify_isin_sg_alias_pollution,
    _classify_india_ns_bo_dual,
    _classify_plain_plus_local_alt,
    _classify_same_venue_alias,
    _classify_single_candidate_no_div,
)


def _classify_mapping_issue(
    *,
    candidate_count: int,
    candidates: list[str],
    resolution_status: str,
) -> str:
    if candidate_count <= 0:
        return "other"

    for classifier in _ISSUE_CLASSIFIERS:
        label = classifier(candidates, resolution_status, candidate_count)
        if label:
            return label

    return "other"


def _build_mapping_issue_fields(out: pd.DataFrame) -> pd.DataFrame:
    candidates_list = out["candidates_json"].map(_parse_candidates_json)

    mapping_issue_class: list[str] = []
    candidate_list_pretty: list[str] = []
    candidate_suffixes: list[str] = []

    for candidate_count, candidates, resolution_status in zip(
        out["candidate_count"].tolist(),
        candidates_list.tolist(),
        out["resolution_status"].tolist(),
    ):
        clean_candidates = [str(x).strip().upper() for x in candidates if str(x).strip()]
        mapping_issue_class.append(
            _classify_mapping_issue(
                candidate_count=int(candidate_count),
                candidates=clean_candidates,
                resolution_status=str(resolution_status),
            )
        )
        candidate_list_pretty.append(" | ".join(clean_candidates))
        candidate_suffixes.append(",".join(_candidate_suffix_label(x) for x in clean_candidates))

    out["mapping_issue_class"] = pd.Series(mapping_issue_class, index=out.index, dtype="string")
    out["candidate_list_pretty"] = pd.Series(candidate_list_pretty, index=out.index, dtype="string")
    out["candidate_suffixes"] = pd.Series(candidate_suffixes, index=out.index, dtype="string")

    return out


def _prepare_report_input(discovered_candidate_df: pd.DataFrame) -> pd.DataFrame:
    _validate_required_columns(discovered_candidate_df)

    input_has_exists_ns = "exists_ns" in discovered_candidate_df.columns
    input_has_exists_bo = "exists_bo" in discovered_candidate_df.columns

    out = _ensure_optional_columns(discovered_candidate_df)

    out["underlying"] = _clean_text_series(out["underlying"], upper=True)
    out["underlying_ccy"] = _clean_text_series(out["underlying_ccy"], upper=True)
    out["isin"] = _clean_text_series(out["isin"], upper=True)
    out["chosen_ticker"] = _clean_text_series(out["chosen_ticker"])
    out["candidate_market"] = _clean_text_series(out["candidate_market"], upper=True)
    out["candidate_origin"] = _clean_text_series(out["candidate_origin"])
    out["resolution_status"] = _clean_text_series(out["resolution_status"], upper=True)

    resolution_reason = _clean_text_series(out["resolution_reason"])
    legacy_reason = _clean_text_series(out["reason"])
    out["resolution_reason"] = resolution_reason.where(resolution_reason.ne(""), legacy_reason)

    resolution_method = _clean_text_series(out["resolution_method"])
    legacy_method = _clean_text_series(out["method"])
    out["resolution_method"] = resolution_method.where(resolution_method.ne(""), legacy_method)

    out["resolution_source"] = _clean_text_series(out["resolution_source"])
    out["candidate_count"] = _normalise_int_col(out, "candidate_count")
    out["candidates_json"] = _clean_text_series(out["candidates_json"])
    out["exists_ticker"] = _clean_text_series(out["exists_ticker"])

    legacy_exists_ns = _normalise_bool_col(out, "exists_ns")
    legacy_exists_bo = _normalise_bool_col(out, "exists_bo")

    preverified_exists_any = _normalise_bool_col(out, "preverified_exists_any")
    preverified_exists_any = (preverified_exists_any | legacy_exists_ns | legacy_exists_bo).astype("bool")
    out["preverified_exists_any"] = preverified_exists_any

    preverified_exists_ticker = _clean_text_series(out["preverified_exists_ticker"], upper=True)
    fallback_preverified_ticker = _clean_text_series(
        out["exists_ticker"].where(out["exists_ticker"].ne(""), out["chosen_ticker"]),
        upper=True,
    )
    needs_preverified_ticker = preverified_exists_ticker.eq("") & preverified_exists_any
    preverified_exists_ticker = preverified_exists_ticker.where(
        ~needs_preverified_ticker,
        fallback_preverified_ticker,
    )
    out["preverified_exists_ticker"] = preverified_exists_ticker

    derived_exists_ns, derived_exists_bo = _derive_legacy_exists_flags(out["preverified_exists_ticker"])
    out["exists_ns"] = legacy_exists_ns if input_has_exists_ns else derived_exists_ns
    out["exists_bo"] = legacy_exists_bo if input_has_exists_bo else derived_exists_bo

    out["holdings_tag"] = _clean_text_series(out["holdings_tag"])
    out["holdings_file"] = _clean_text_series(out["holdings_file"])
    out["source"] = _clean_text_series(out["source"])
    out["start"] = _clean_text_series(out["start"])
    out["end"] = _clean_text_series(out["end"])
    out["guess_source"] = _clean_text_series(out["guess_source"], upper=True)
    out["canonical_exchange"] = _clean_text_series(out["canonical_exchange"], upper=True)
    out["isin_prefix"] = _clean_text_series(out["isin_prefix"], upper=True)
    out["prefix_exchange_consistent"] = _normalise_nullable_bool_col(out, "prefix_exchange_consistent")

    return out


def _enrich_resolution_fields(out: pd.DataFrame) -> pd.DataFrame:
    enriched = out.copy()
    enriched["is_failed"] = _derive_failure_mask(enriched)
    return enriched


def _attach_weight_fields(
    out: pd.DataFrame,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    return _merge_report_weights(
        out,
        universe_df=universe_df,
        universe_maps=universe_maps,
    )


def _attach_anomaly_fields(out: pd.DataFrame) -> pd.DataFrame:
    enriched = out.copy()
    enriched["is_anomaly"] = _derive_anomaly_mask(enriched)
    return enriched


def _attach_mapping_issue_fields(out: pd.DataFrame) -> pd.DataFrame:
    return _build_mapping_issue_fields(out.copy())


def _finalise_report_columns(out: pd.DataFrame) -> pd.DataFrame:
    ordered_cols = (
        _EMPTY_REPORT_COLUMNS
        + _DIAGNOSTIC_REPORT_COLUMNS
        + [c for c in _EXTRA_REPORT_COLUMNS if c in out.columns]
    )
    return out.reindex(columns=ordered_cols).reset_index(drop=True)


def summarise_materiality(report_df: pd.DataFrame) -> MaterialityGateResult:
    if report_df is None or report_df.empty:
        return MaterialityGateResult(
            failed_rows=0,
            anomaly_rows=0,
            failed_weight_sum=0.0,
            anomaly_weight_sum=0.0,
            max_failed_weight=0.0,
            unmatched_failed_count=0,
            unmatched_failed_weight_sum=0.0,
        )

    failed = report_df.loc[report_df["is_failed"]].copy()
    anomaly = (
        report_df.loc[report_df["is_anomaly"]].copy()
        if "is_anomaly" in report_df.columns
        else report_df.iloc[0:0].copy()
    )

    failed_weight = pd.to_numeric(failed.get("weight", 0.0), errors="coerce").fillna(0.0)
    anomaly_weight = pd.to_numeric(anomaly.get("weight", 0.0), errors="coerce").fillna(0.0)

    unmatched_failed = failed.loc[
        _clean_text_series(
            failed.get("weight_match_method", pd.Series(index=failed.index, dtype="string"))
        ).eq(_WEIGHT_MATCH_METHOD_UNMATCHED)
    ].copy()
    unmatched_failed_weight = pd.to_numeric(unmatched_failed.get("weight", 0.0), errors="coerce").fillna(0.0)

    return MaterialityGateResult(
        failed_rows=int(len(failed)),
        anomaly_rows=int(len(anomaly)),
        failed_weight_sum=float(failed_weight.sum()),
        anomaly_weight_sum=float(anomaly_weight.sum()),
        max_failed_weight=float(failed_weight.max()) if len(failed_weight) else 0.0,
        unmatched_failed_count=int(len(unmatched_failed)),
        unmatched_failed_weight_sum=float(unmatched_failed_weight.sum()),
    )


def summarise_ticker_qa(report_df: pd.DataFrame | None) -> dict[str, Any]:
    if report_df is None or report_df.empty:
        return {
            "report_rows": 0,
            "failed_rows": 0,
            "anomaly_rows": 0,
            "failed_weight_sum": 0.0,
            "anomaly_weight_sum": 0.0,
            "max_failed_weight": 0.0,
            "unmatched_failed_count": 0,
            "unmatched_failed_weight_sum": 0.0,
        }

    summary = summarise_materiality(report_df)
    return {
        "report_rows": int(len(report_df)),
        "failed_rows": summary.failed_rows,
        "anomaly_rows": summary.anomaly_rows,
        "failed_weight_sum": summary.failed_weight_sum,
        "anomaly_weight_sum": summary.anomaly_weight_sum,
        "max_failed_weight": summary.max_failed_weight,
        "unmatched_failed_count": summary.unmatched_failed_count,
        "unmatched_failed_weight_sum": summary.unmatched_failed_weight_sum,
    }


def _format_failed_row_summary(row: pd.Series) -> str:
    underlying = str(row.get("underlying", "") or "").strip()
    chosen_ticker = str(row.get("chosen_ticker", "") or "").strip()
    resolution_status = str(row.get("resolution_status", "") or "").strip()
    weight = pd.to_numeric(row.get("weight", 0.0), errors="coerce")
    weight_value = 0.0 if pd.isna(weight) else float(weight)

    return f"{underlying}:{chosen_ticker}:{resolution_status}:{weight_value:.6g}"


def _top_failed_row_summaries(
    report_df: pd.DataFrame,
    *,
    top_n: int = 3,
) -> str:
    if report_df is None or report_df.empty or "is_failed" not in report_df.columns:
        return "none"

    failed = report_df.loc[report_df["is_failed"]].copy()
    if failed.empty:
        return "none"

    failed["weight"] = pd.to_numeric(failed.get("weight", 0.0), errors="coerce").fillna(0.0)
    failed = failed.sort_values(
        ["weight", "underlying", "chosen_ticker"],
        ascending=[False, True, True],
        kind="stable",
    )

    summaries = [
        _format_failed_row_summary(row)
        for _, row in failed.head(int(top_n)).iterrows()
    ]

    return "; ".join(summaries) if summaries else "none"


def validate_ticker_map_materiality(
    report_df: pd.DataFrame,
    *,
    fail_on_unmatched_failed: bool = False,
    single_fail_weight_threshold: float | None = None,
    total_fail_weight_threshold: float | None = None,
    epsilon: float = _DEFAULT_EPSILON,
) -> MaterialityGateResult:
    summary = summarise_materiality(report_df)
    top_failed = _top_failed_row_summaries(report_df, top_n=3)

    if fail_on_unmatched_failed and summary.unmatched_failed_count > 0:
        raise TickerMapMaterialityError(
            "ticker QA materiality gate failed: unmatched failed rows present "
            f"(count={summary.unmatched_failed_count}, "
            f"weight_sum={summary.unmatched_failed_weight_sum}) "
            f"top_failed=[{top_failed}]"
        )

    if single_fail_weight_threshold is not None:
        threshold = float(single_fail_weight_threshold)
        if summary.max_failed_weight > threshold + epsilon:
            raise TickerMapMaterialityError(
                "ticker QA materiality gate failed: single failed weight threshold breached "
                f"(max_failed_weight={summary.max_failed_weight}, threshold={threshold}) "
                f"top_failed=[{top_failed}]"
            )

    if total_fail_weight_threshold is not None:
        threshold = float(total_fail_weight_threshold)
        if summary.failed_weight_sum > threshold + epsilon:
            raise TickerMapMaterialityError(
                "ticker QA materiality gate failed: total failed weight threshold breached "
                f"(failed_weight_sum={summary.failed_weight_sum}, threshold={threshold}) "
                f"top_failed=[{top_failed}]"
            )

    return summary


def build_ticker_map_report(
    discovered_candidate_df: pd.DataFrame | None,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
    run_materiality_gate: bool = False,
    fail_on_unmatched_failed: bool = False,
    single_fail_weight_threshold: float | None = None,
    total_fail_weight_threshold: float | None = None,
) -> pd.DataFrame:
    if discovered_candidate_df is None or discovered_candidate_df.empty:
        return _empty_report_frame()

    out = _prepare_report_input(discovered_candidate_df)
    out = _enrich_resolution_fields(out)
    out = _attach_weight_fields(
        out,
        universe_df=universe_df,
        universe_maps=universe_maps,
    )
    out = _attach_anomaly_fields(out)
    out = _attach_mapping_issue_fields(out)
    out = _finalise_report_columns(out)

    if run_materiality_gate:
        validate_ticker_map_materiality(
            out,
            fail_on_unmatched_failed=fail_on_unmatched_failed,
            single_fail_weight_threshold=single_fail_weight_threshold,
            total_fail_weight_threshold=total_fail_weight_threshold,
        )

    return out


def failed_tickers(
    discovered_candidate_df: pd.DataFrame | None,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    report = build_ticker_map_report(
        discovered_candidate_df,
        universe_df=universe_df,
        universe_maps=universe_maps,
        run_materiality_gate=False,
    )
    if report.empty:
        return report.copy()
    return report.loc[report["is_failed"]].reset_index(drop=True)


def anomaly_tickers(
    discovered_candidate_df: pd.DataFrame | None,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    report = build_ticker_map_report(
        discovered_candidate_df,
        universe_df=universe_df,
        universe_maps=universe_maps,
        run_materiality_gate=False,
    )
    if report.empty:
        return report.copy()
    if "is_anomaly" not in report.columns:
        return report.iloc[0:0].copy()
    return report.loc[report["is_anomaly"]].reset_index(drop=True)


def materiality_gate_summary(
    discovered_candidate_df: pd.DataFrame | None,
    *,
    universe_df: pd.DataFrame | None = None,
    universe_maps: pd.DataFrame | Mapping[str, pd.DataFrame] | None = None,
) -> MaterialityGateResult:
    report = build_ticker_map_report(
        discovered_candidate_df,
        universe_df=universe_df,
        universe_maps=universe_maps,
        run_materiality_gate=False,
    )
    return summarise_materiality(report)