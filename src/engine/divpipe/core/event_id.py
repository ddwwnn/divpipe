# src/engine/divpipe/core/event_id.py

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any


def _sha256_hex_n(s: str, n_hex: int = 32) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:n_hex]


def _normalise_text_part(x: str | None) -> str:
    return str(x or "").strip().upper()


def _validate_non_negative_int(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


def _validate_non_negative_float(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


def _validate_unit_interval(name: str, value: float) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{name} must be between 0 and 1 inclusive")


def _normalise_source_priority(source_priority: dict[str, int]) -> dict[str, int]:
    cleaned: dict[str, int] = {}

    for key, value in source_priority.items():
        key_norm = _normalise_text_part(key)
        if not key_norm:
            raise ValueError("source_priority key must not be blank")
        if not isinstance(value, int):
            raise ValueError("source_priority value must be int")
        cleaned[key_norm] = value

    return cleaned


def make_economic_event_id(key: str) -> str:
    key_norm = str(key or "").strip()
    return f"eco_{_sha256_hex_n(key_norm, 32)}"


def make_observation_id(
    provider: str,
    provider_event_id: str | None,
    row_fallback: str,
    asof_date_iso: str,
) -> str:
    """
    Observation id is snapshot-specific at date granularity.
    """
    provider_norm = _normalise_text_part(provider)
    provider_event_id_norm = str(provider_event_id or "").strip()
    row_fallback_norm = str(row_fallback or "").strip()
    asof_date_norm = str(asof_date_iso or "").strip()

    raw = f"{provider_norm}|{provider_event_id_norm}|{row_fallback_norm}|{asof_date_norm}"
    return f"obs_{_sha256_hex_n(raw, 32)}"


@dataclass(frozen=True)
class LinkPolicy:
    # Core linking thresholds
    max_day_shift: int = 5
    max_amount_rel_move: float = 0.20

    # Missing / zero amount handling
    max_day_shift_when_amount_missing: int = 1
    allow_zero_amount_link: bool = False
    min_absolute_diff_ignore: float = 0.001
    min_amount_denominator: float = 1e-9

    # Stable tie / canonicalisation behaviour
    stable_amount_decimals: int = 8
    source_priority: dict[str, int] = field(default_factory=dict)

    # Vendor-event guardrails
    vendor_group_max_anchor_spread_days: int = 30
    vendor_group_max_amount_rel_spread: float = 0.10

    def __post_init__(self) -> None:
        _validate_non_negative_int("max_day_shift", self.max_day_shift)
        _validate_non_negative_int(
            "max_day_shift_when_amount_missing",
            self.max_day_shift_when_amount_missing,
        )
        _validate_unit_interval("max_amount_rel_move", self.max_amount_rel_move)
        _validate_non_negative_float(
            "min_absolute_diff_ignore",
            self.min_absolute_diff_ignore,
        )
        _validate_non_negative_float(
            "min_amount_denominator",
            self.min_amount_denominator,
        )
        _validate_non_negative_int(
            "stable_amount_decimals",
            self.stable_amount_decimals,
        )
        _validate_non_negative_int(
            "vendor_group_max_anchor_spread_days",
            self.vendor_group_max_anchor_spread_days,
        )
        _validate_non_negative_float(
            "vendor_group_max_amount_rel_spread",
            self.vendor_group_max_amount_rel_spread,
        )

        object.__setattr__(
            self,
            "source_priority",
            _normalise_source_priority(self.source_priority),
        )


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        value = float(x)
        if math.isnan(value):
            return None
        return value
    except (TypeError, ValueError):
        return None


def should_link_events(
    a_ex: date,
    a_amt: float | None,
    b_ex: date,
    b_amt: float | None,
    policy: LinkPolicy,
) -> tuple[bool, str]:
    day_shift = abs((a_ex - b_ex).days)
    if day_shift > policy.max_day_shift:
        return False, f"day_shift={day_shift}>max"

    if a_amt is None or b_amt is None:
        if day_shift <= policy.max_day_shift_when_amount_missing:
            return True, f"day_shift={day_shift}, amount_missing"
        return (
            False,
            f"day_shift={day_shift}>missing_amount_max({policy.max_day_shift_when_amount_missing})",
        )

    if a_amt == 0.0 or b_amt == 0.0:
        if not policy.allow_zero_amount_link:
            return False, "zero_amount_block"
        if day_shift <= policy.max_day_shift_when_amount_missing:
            return True, f"day_shift={day_shift}, zero_amount_allowed"
        return (
            False,
            f"day_shift={day_shift}>zero_amount_max({policy.max_day_shift_when_amount_missing})",
        )

    abs_diff = abs(a_amt - b_amt)
    if abs_diff <= policy.min_absolute_diff_ignore:
        return (
            True,
            f"day_shift={day_shift}, abs_diff={abs_diff:.12g}<=min_abs({policy.min_absolute_diff_ignore:.12g})",
        )

    denom = max(abs(a_amt), abs(b_amt))
    if denom <= policy.min_amount_denominator:
        return (
            True,
            f"small_amount_denom={denom:.12g}<=min({policy.min_amount_denominator:.12g})",
        )

    rel = abs_diff / denom
    if rel <= policy.max_amount_rel_move:
        return (
            True,
            f"day_shift={day_shift}, rel_move={rel:.12g}<=max_rel({policy.max_amount_rel_move:.12g})",
        )

    return (
        False,
        f"rel_move={rel:.12g}>max_rel({policy.max_amount_rel_move:.12g})",
    )