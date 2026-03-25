# src/engine/divpipe/pipeline/ticker_resolution_cache.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from .ticker_resolution_canonical import normalise_ticker_resolution_df

_OVERRIDE_BASE_COLUMNS = [
    "underlying",
    "underlying_ccy",
    "chosen_ticker",
    "reason",
    "method",
    "isin",
    "exists_ns",
    "exists_bo",
]

_CACHE_COLUMNS = [
    "underlying",
    "underlying_ccy",
    "isin",
    "chosen_ticker",
    "reason",
    "method",
    "exists_ns",
    "exists_bo",
    "resolution_status",
    "candidate_market",
    "resolution_source",
    "first_seen_asof",
    "last_seen_asof",
    "last_validated_run_id",
]

_NULL_LIKE = {"", "NA", "NAN", "NONE", "<NA>", "-"}
_FALSE_LIKE = {"", "NA", "NAN", "NONE", "<NA>", "-", "FALSE", "F", "NO", "N", "0"}
_TRUE_LIKE = {"TRUE", "T", "YES", "Y", "1"}

_LEGACY_EXISTS_NS_ALIASES = ("exists_ns",)
_LEGACY_EXISTS_BO_ALIASES = ("exists_bo",)


def _empty_frame(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


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


def _clean_date_yyyymmdd(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        return ""

    return parsed.strftime("%Y%m%d")


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


def _first_present_value(src: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in src:
            return src.get(name)
    return None


def _resolve_preverified_exists_ticker(src: Mapping[str, Any]) -> str:
    direct = _clean_text(src.get("preverified_exists_ticker"), upper=True)
    if direct:
        return direct

    legacy_ns = _parse_bool_like(_first_present_value(src, _LEGACY_EXISTS_NS_ALIASES))
    legacy_bo = _parse_bool_like(_first_present_value(src, _LEGACY_EXISTS_BO_ALIASES))
    if not (legacy_ns or legacy_bo):
        return ""

    exists_ticker = _clean_text(src.get("exists_ticker"), upper=True)
    if exists_ticker:
        return exists_ticker

    chosen_ticker = _clean_text(src.get("chosen_ticker"), upper=True)
    if chosen_ticker:
        return chosen_ticker

    return ""


def _derive_legacy_exists_flags(
    src: Mapping[str, Any],
) -> tuple[bool, bool]:
    has_legacy_ns = any(name in src for name in _LEGACY_EXISTS_NS_ALIASES)
    has_legacy_bo = any(name in src for name in _LEGACY_EXISTS_BO_ALIASES)

    if has_legacy_ns or has_legacy_bo:
        exists_ns = _parse_bool_like(_first_present_value(src, _LEGACY_EXISTS_NS_ALIASES))
        exists_bo = _parse_bool_like(_first_present_value(src, _LEGACY_EXISTS_BO_ALIASES))
        return exists_ns, exists_bo

    preverified_ticker = _resolve_preverified_exists_ticker(src)
    if not preverified_ticker:
        return False, False

    return preverified_ticker.endswith(".NS"), preverified_ticker.endswith(".BO")


def _resolution_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(record.get("underlying", "")),
        str(record.get("underlying_ccy", "")),
    )


def _is_valid_resolution_record(record: Mapping[str, Any]) -> bool:
    return (
        str(record.get("underlying", "")) != ""
        and str(record.get("underlying_ccy", "")) != ""
        and str(record.get("chosen_ticker", "")) != ""
    )


def _normalise_override_record(src: Mapping[str, Any]) -> dict[str, object]:
    exists_ns, exists_bo = _derive_legacy_exists_flags(src)

    return {
        "underlying": _clean_text(src.get("underlying"), upper=True),
        "underlying_ccy": _clean_text(src.get("underlying_ccy"), upper=True),
        "chosen_ticker": _clean_text(src.get("chosen_ticker"), upper=True),
        "reason": _clean_text(src.get("reason")),
        "method": _clean_text(src.get("method")),
        "isin": _clean_isin(src.get("isin")),
        "exists_ns": exists_ns,
        "exists_bo": exists_bo,
    }


def _normalise_cache_record(src: Mapping[str, Any]) -> dict[str, object]:
    exists_ns, exists_bo = _derive_legacy_exists_flags(src)

    return {
        "underlying": _clean_text(src.get("underlying"), upper=True),
        "underlying_ccy": _clean_text(src.get("underlying_ccy"), upper=True),
        "isin": _clean_isin(src.get("isin")),
        "chosen_ticker": _clean_text(src.get("chosen_ticker"), upper=True),
        "reason": _clean_text(src.get("reason")),
        "method": _clean_text(src.get("method")),
        "exists_ns": exists_ns,
        "exists_bo": exists_bo,
        "resolution_status": _clean_text(src.get("resolution_status"), upper=True),
        "candidate_market": _clean_text(src.get("candidate_market"), upper=True),
        "resolution_source": _clean_text(src.get("resolution_source")),
        "first_seen_asof": _clean_date_yyyymmdd(src.get("first_seen_asof")),
        "last_seen_asof": _clean_date_yyyymmdd(src.get("last_seen_asof")),
        "last_validated_run_id": _clean_text(src.get("last_validated_run_id")),
    }


def _records_to_frame(records: list[dict[str, object]], columns: Sequence[str]) -> pd.DataFrame:
    if not records:
        return _empty_frame(columns)

    return pd.DataFrame.from_records(records, columns=list(columns))


def load_override_table(path: Path | str) -> pd.DataFrame:
    file_path = Path(path)
    if not str(path).strip() or not file_path.exists():
        return _empty_frame(_OVERRIDE_BASE_COLUMNS)

    df = pd.read_csv(file_path, encoding="utf-8-sig")
    out: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for record in df.to_dict("records"):
        normalised = _normalise_override_record(record)
        if not _is_valid_resolution_record(normalised):
            continue

        key = _resolution_key(normalised)
        if key in seen:
            continue

        seen.add(key)
        out.append(normalised)

    return _records_to_frame(out, _OVERRIDE_BASE_COLUMNS)


def load_resolution_cache(path: Path | str) -> pd.DataFrame:
    file_path = Path(path)
    if not str(path).strip() or not file_path.exists():
        return _empty_frame(_CACHE_COLUMNS)

    df = pd.read_csv(file_path, encoding="utf-8-sig")
    latest_by_key: dict[tuple[str, str], dict[str, object]] = {}

    for record in df.to_dict("records"):
        normalised = _normalise_cache_record(record)
        if not _is_valid_resolution_record(normalised):
            continue

        latest_by_key[_resolution_key(normalised)] = normalised

    out = list(latest_by_key.values())
    return _records_to_frame(out, _CACHE_COLUMNS)


def build_effective_chosen_map(
    *,
    override_path: Path | str,
    cache_path: Path | str,
) -> pd.DataFrame:
    overrides_df = load_override_table(override_path)
    cache_df = load_resolution_cache(cache_path)

    effective: dict[tuple[str, str], dict[str, object]] = {}

    for record in cache_df.to_dict("records"):
        as_override = _normalise_override_record(
            {
                "underlying": record.get("underlying", ""),
                "underlying_ccy": record.get("underlying_ccy", ""),
                "chosen_ticker": record.get("chosen_ticker", ""),
                "reason": record.get("reason", "") or "cache",
                "method": record.get("method", "") or "cache",
                "isin": record.get("isin", ""),
                "exists_ns": record.get("exists_ns", False),
                "exists_bo": record.get("exists_bo", False),
            }
        )
        if _is_valid_resolution_record(as_override):
            effective[_resolution_key(as_override)] = as_override

    for record in overrides_df.to_dict("records"):
        normalised = _normalise_override_record(record)
        if _is_valid_resolution_record(normalised):
            effective[_resolution_key(normalised)] = normalised

    out = list(effective.values())
    out.sort(key=lambda record: (str(record["underlying"]), str(record["underlying_ccy"])))

    return _records_to_frame(out, _OVERRIDE_BASE_COLUMNS)


def write_effective_chosen_map(
    *,
    override_path: Path | str,
    cache_path: Path | str,
    out_path: Path | str,
) -> pd.DataFrame:
    out = build_effective_chosen_map(
        override_path=override_path,
        cache_path=cache_path,
    )
    file_path = Path(out_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(file_path, index=False, encoding="utf-8-sig")
    return out


def _normalise_status_values(values: Iterable[str]) -> set[str]:
    out: set[str] = set()

    for value in values:
        cleaned = _clean_text(value, upper=True)
        if cleaned:
            out.add(cleaned)

    return out


def build_cache_updates_from_discovered_candidates(
    discovered_candidate_df: pd.DataFrame,
    *,
    asof_date: str,
    run_id: str,
    accepted_statuses: Iterable[str] = ("div_found", "verified_exists_but_no_dividends"),
) -> pd.DataFrame:
    if discovered_candidate_df is None or discovered_candidate_df.empty:
        return _empty_frame(_CACHE_COLUMNS)

    accepted = _normalise_status_values(accepted_statuses)
    df = normalise_ticker_resolution_df(discovered_candidate_df)
    df = df.loc[df["resolution_status"].isin(accepted)].copy()

    if df.empty:
        return _empty_frame(_CACHE_COLUMNS)

    clean_asof = _clean_date_yyyymmdd(asof_date)
    clean_run_id = _clean_text(run_id)

    updates: dict[tuple[str, str], dict[str, object]] = {}

    for record in df.to_dict("records"):
        preverified_exists_ticker = _clean_text(record.get("preverified_exists_ticker"), upper=True)
        exists_ns = preverified_exists_ticker.endswith(".NS")
        exists_bo = preverified_exists_ticker.endswith(".BO")

        normalised = _normalise_cache_record(
            {
                "underlying": record.get("underlying", ""),
                "underlying_ccy": record.get("underlying_ccy", ""),
                "isin": record.get("isin", ""),
                "chosen_ticker": record.get("chosen_ticker", ""),
                "reason": record.get("resolution_reason", ""),
                "method": record.get("resolution_method", ""),
                "exists_ns": exists_ns,
                "exists_bo": exists_bo,
                "resolution_status": record.get("resolution_status", ""),
                "candidate_market": record.get("candidate_market", ""),
                "resolution_source": record.get("resolution_source", ""),
                "first_seen_asof": clean_asof,
                "last_seen_asof": clean_asof,
                "last_validated_run_id": clean_run_id,
            }
        )

        if not _is_valid_resolution_record(normalised):
            continue

        updates[_resolution_key(normalised)] = normalised

    out = list(updates.values())
    out.sort(key=lambda record: (str(record["underlying"]), str(record["underlying_ccy"])))

    return _records_to_frame(out, _CACHE_COLUMNS)


def upsert_resolution_cache(
    *,
    cache_path: Path | str,
    discovered_candidate_df: pd.DataFrame,
    asof_date: str,
    run_id: str,
    accepted_statuses: Iterable[str] = ("div_found",),
) -> pd.DataFrame:
    existing_df = load_resolution_cache(cache_path)
    updates_df = build_cache_updates_from_discovered_candidates(
        discovered_candidate_df=discovered_candidate_df,
        asof_date=asof_date,
        run_id=run_id,
        accepted_statuses=accepted_statuses,
    )

    if existing_df.empty and updates_df.empty:
        out = _empty_frame(_CACHE_COLUMNS)
    elif updates_df.empty:
        out = existing_df.copy()
    elif existing_df.empty:
        out = updates_df.copy()
    else:
        merged: dict[tuple[str, str], dict[str, object]] = {
            _resolution_key(record): dict(record)
            for record in existing_df.to_dict("records")
        }

        for update_record in updates_df.to_dict("records"):
            key = _resolution_key(update_record)
            old = merged.get(key)

            new_record = dict(update_record)
            if old is not None:
                new_record["first_seen_asof"] = (
                    _clean_date_yyyymmdd(old.get("first_seen_asof", ""))
                    or _clean_date_yyyymmdd(new_record.get("first_seen_asof", ""))
                )

            merged[key] = _normalise_cache_record(new_record)

        out_records = [
            record
            for record in merged.values()
            if _is_valid_resolution_record(record)
        ]
        out_records.sort(key=lambda record: (str(record["underlying"]), str(record["underlying_ccy"])))
        out = _records_to_frame(out_records, _CACHE_COLUMNS)

    out = out.reindex(columns=_CACHE_COLUMNS).reset_index(drop=True)

    file_path = Path(cache_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(file_path, index=False, encoding="utf-8-sig")
    return out