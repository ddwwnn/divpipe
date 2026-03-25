# src/engine/divpipe/pipeline/ticker_resolution_canonical.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class FieldSpec:
    dtype: str
    cleaner: str
    aliases: tuple[str, ...] = ()
    upper: bool = False


_NULL_LIKE = {"", "NA", "NAN", "NONE", "<NA>", "-"}
_FALSE_LIKE = {"", "NA", "NAN", "NONE", "<NA>", "-", "FALSE", "F", "NO", "N", "0"}
_TRUE_LIKE = {"TRUE", "T", "YES", "Y", "1"}

STATUS_TICKER_NOT_FOUND = "TICKER_NOT_FOUND"
STATUS_UNSUPPORTED_VENDOR = "UNSUPPORTED_VENDOR"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_ERROR = "ERROR"
STATUS_CANDIDATE_UNVERIFIED = "CANDIDATE_UNVERIFIED"
STATUS_VERIFIED_EXISTS_BUT_NO_DIVIDENDS = "VERIFIED_EXISTS_BUT_NO_DIVIDENDS"

FAIL_STATUSES = {
    STATUS_TICKER_NOT_FOUND,
    STATUS_UNSUPPORTED_VENDOR,
    STATUS_AMBIGUOUS,
    STATUS_ERROR,
    STATUS_CANDIDATE_UNVERIFIED,
}

FAILURE_STATUSES = FAIL_STATUSES

LEGACY_EXISTS_NS_ALIASES = ("exists_ns",)
LEGACY_EXISTS_BO_ALIASES = ("exists_bo",)


FIELD_SPECS: dict[str, FieldSpec] = {
    "underlying": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("underlying",),
    ),
    "underlying_ccy": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("underlying_ccy", "ccy"),
        upper=True,
    ),
    "isin": FieldSpec(
        dtype="string",
        cleaner="isin",
        aliases=("isin",),
    ),
    "chosen_ticker": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("chosen_ticker",),
    ),
    "candidate_market": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("candidate_market",),
        upper=True,
    ),
    "candidate_origin": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("candidate_origin",),
    ),
    "resolution_status": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("resolution_status", "status"),
        upper=True,
    ),
    "resolution_reason": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("resolution_reason", "reason"),
    ),
    "resolution_method": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("resolution_method", "method"),
    ),
    "resolution_source": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("resolution_source",),
    ),
    "candidate_count": FieldSpec(
        dtype="int64",
        cleaner="int",
        aliases=("candidate_count",),
    ),
    "candidates_json": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("candidates_json",),
    ),
    "exists_ticker": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("exists_ticker",),
        upper=True,
    ),
    "preverified_exists_any": FieldSpec(
        dtype="bool",
        cleaner="derived",
        aliases=("preverified_exists_any", "exists_any"),
    ),
    "preverified_exists_ticker": FieldSpec(
        dtype="string",
        cleaner="derived",
        aliases=("preverified_exists_ticker", "preverified_ticker"),
        upper=True,
    ),
    "exists_probe_symbol": FieldSpec(
        dtype="string",
        cleaner="derived",
        upper=True,
    ),
    "exists_probe_result": FieldSpec(
        dtype="boolean",
        cleaner="derived",
    ),
    "review_reason": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("review_reason",),
    ),
    "holdings_tag": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("holdings_tag",),
    ),
    "holdings_file": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("holdings_file",),
    ),
    "source": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("source",),
    ),
    "start": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("start",),
    ),
    "end": FieldSpec(
        dtype="string",
        cleaner="text",
        aliases=("end",),
    ),
}

CANONICAL_COLUMNS = list(FIELD_SPECS.keys())
DTYPE_MAP: dict[str, str] = {field: spec.dtype for field, spec in FIELD_SPECS.items()}


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and value != value


def _clean_text(value: Any, *, upper: bool = False) -> str:
    if value is None or _is_nan(value):
        return ""

    text = str(value).strip()
    if text.upper() in _NULL_LIKE:
        return ""

    return text.upper() if upper else text


def _clean_isin(value: Any) -> str:
    return _clean_text(value, upper=True).replace(" ", "")


def _clean_int(value: Any) -> int:
    if value is None or _is_nan(value):
        return 0

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value) if value.is_integer() else 0

    text = str(value).strip()
    if text.upper() in _NULL_LIKE:
        return 0

    try:
        parsed = float(text)
    except (TypeError, ValueError):
        return 0

    return int(parsed) if parsed.is_integer() else 0


def _parse_bool_like(value: Any) -> bool:
    if value is None or _is_nan(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"invalid integer bool-like value: {value}")

    text = str(value).strip().upper()

    if text in _FALSE_LIKE:
        return False

    if text in _TRUE_LIKE:
        return True

    raise ValueError(f"invalid bool-like value: {value}")


def _first_present_value(src: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in src:
            return src.get(name)
    return None


def _resolve_preverified_exists_any(src: dict[str, Any]) -> bool:
    if "preverified_exists_any" in src:
        return _parse_bool_like(src.get("preverified_exists_any"))

    legacy_ns = _parse_bool_like(_first_present_value(src, LEGACY_EXISTS_NS_ALIASES))
    legacy_bo = _parse_bool_like(_first_present_value(src, LEGACY_EXISTS_BO_ALIASES))
    return bool(legacy_ns or legacy_bo)


def _resolve_preverified_exists_ticker(src: dict[str, Any]) -> str:
    direct = _clean_text(src.get("preverified_exists_ticker"), upper=True)
    if direct:
        return direct

    legacy_ns = _parse_bool_like(_first_present_value(src, LEGACY_EXISTS_NS_ALIASES))
    legacy_bo = _parse_bool_like(_first_present_value(src, LEGACY_EXISTS_BO_ALIASES))
    if not (legacy_ns or legacy_bo):
        return ""

    exists_ticker = _clean_text(src.get("exists_ticker"), upper=True)
    if exists_ticker:
        return exists_ticker

    chosen_ticker = _clean_text(src.get("chosen_ticker"), upper=True)
    if chosen_ticker:
        return chosen_ticker

    return ""


def _derive_exists_probe_symbol(
    *,
    preverified_exists_ticker: str,
    exists_ticker: str,
    chosen_ticker: str,
) -> str:
    if preverified_exists_ticker:
        return preverified_exists_ticker

    if exists_ticker and exists_ticker != "UNSUPPORTED_YF":
        return exists_ticker

    return chosen_ticker


def _derive_exists_probe_result(
    *,
    preverified_exists_any: bool,
    exists_ticker: str,
    chosen_ticker: str,
    resolution_status: str,
) -> bool | None:
    if preverified_exists_any:
        return True

    if exists_ticker == "UNSUPPORTED_YF":
        return False

    if exists_ticker:
        return True

    if resolution_status == STATUS_VERIFIED_EXISTS_BUT_NO_DIVIDENDS and chosen_ticker:
        return True

    if resolution_status in FAIL_STATUSES:
        return False

    return None


def _default_record() -> dict[str, Any]:
    out: dict[str, Any] = {}

    for field, spec in FIELD_SPECS.items():
        if spec.dtype == "int64":
            out[field] = 0
        elif spec.dtype == "bool":
            out[field] = False
        elif spec.dtype == "boolean":
            out[field] = None
        else:
            out[field] = ""

    return out


def _build_reverse_alias_map() -> dict[str, str]:
    out: dict[str, str] = {}

    for canonical, spec in FIELD_SPECS.items():
        for alias in spec.aliases:
            out[alias] = canonical

    return out


_REVERSE_ALIAS_MAP = _build_reverse_alias_map()


def _rename_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map: dict[str, str] = {}

    for col in df.columns:
        key = str(col)
        rename_map[key] = _REVERSE_ALIAS_MAP.get(key, key)

    out = df.rename(columns=rename_map).copy()

    if out.columns.duplicated().any():
        out = out.loc[:, ~out.columns.duplicated()].copy()

    return out


def _clean_text_field(value: Any, spec: FieldSpec) -> Any:
    return _clean_text(value, upper=spec.upper)


def _clean_isin_field(value: Any, spec: FieldSpec) -> Any:
    del spec
    return _clean_isin(value)


def _clean_int_field(value: Any, spec: FieldSpec) -> Any:
    del spec
    return _clean_int(value)


_CLEANERS: dict[str, Callable[[Any, FieldSpec], Any]] = {
    "text": _clean_text_field,
    "isin": _clean_isin_field,
    "int": _clean_int_field,
}


def _normalise_record(src: dict[str, Any]) -> dict[str, Any]:
    out = _default_record()

    for field, spec in FIELD_SPECS.items():
        cleaner = _CLEANERS.get(spec.cleaner)
        if cleaner is not None:
            out[field] = cleaner(src.get(field), spec)

    out["preverified_exists_any"] = _resolve_preverified_exists_any(src)
    out["preverified_exists_ticker"] = _resolve_preverified_exists_ticker(src)

    out["exists_probe_symbol"] = _derive_exists_probe_symbol(
        preverified_exists_ticker=out["preverified_exists_ticker"],
        exists_ticker=out["exists_ticker"],
        chosen_ticker=out["chosen_ticker"],
    )
    out["exists_probe_result"] = _derive_exists_probe_result(
        preverified_exists_any=out["preverified_exists_any"],
        exists_ticker=out["exists_ticker"],
        chosen_ticker=out["chosen_ticker"],
        resolution_status=out["resolution_status"],
    )

    return out


def empty_canonical_ticker_resolution_df() -> pd.DataFrame:
    out = pd.DataFrame(columns=CANONICAL_COLUMNS)
    for col in CANONICAL_COLUMNS:
        out[col] = pd.Series(dtype=DTYPE_MAP[col])
    return out


def normalise_ticker_resolution_df(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_canonical_ticker_resolution_df()

    src = _rename_alias_columns(df)
    records = src.to_dict("records")
    normalised_records = [_normalise_record(record) for record in records]

    out = pd.DataFrame.from_records(normalised_records, columns=CANONICAL_COLUMNS)
    out = out.astype(DTYPE_MAP)

    return out.copy()


def canonicalise_ticker_resolution_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [_normalise_record(record) for record in records]