# src/engine/divpipe/schema/columns.py

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class ColType(Enum):
    STRING = auto()
    DATE = auto()
    NUMERIC = auto()
    ID = auto()
    BOOL = auto()


@dataclass(frozen=True)
class ColumnSpec:
    dtype: ColType
    in_canonical: bool = False
    overlap_required: bool = False
    overlap_string: bool = False
    overlap_date: bool = False
    overlap_numeric: bool = False
    stage1_div_required: bool = False
    aliases: tuple[str, ...] = field(default_factory=tuple)

    strip: bool = True
    upper: bool = False
    remove_spaces: bool = False
    coerce_int: bool = False


def _spec(
    dtype: ColType,
    *,
    in_canonical: bool = False,
    overlap_required: bool = False,
    overlap_string: bool = False,
    overlap_date: bool = False,
    overlap_numeric: bool = False,
    stage1_div_required: bool = False,
    aliases: tuple[str, ...] = (),
    strip: bool = True,
    upper: bool = False,
    remove_spaces: bool = False,
    coerce_int: bool = False,
) -> ColumnSpec:
    return ColumnSpec(
        dtype=dtype,
        in_canonical=in_canonical,
        overlap_required=overlap_required,
        overlap_string=overlap_string,
        overlap_date=overlap_date,
        overlap_numeric=overlap_numeric,
        stage1_div_required=stage1_div_required,
        aliases=aliases,
        strip=strip,
        upper=upper,
        remove_spaces=remove_spaces,
        coerce_int=coerce_int,
    )


def _norm_key(s: str) -> str:
    return (
        str(s)
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


COLUMN_SPECS: dict[str, ColumnSpec] = {
    "economic_event_id": _spec(ColType.ID, in_canonical=True),
    "vendor_event_id": _spec(
        ColType.ID,
        in_canonical=True,
        overlap_string=True,
        aliases=("Vendor Event Id", "vendor_event_id"),
    ),
    "source": _spec(
        ColType.STRING,
        in_canonical=True,
        overlap_string=True,
        stage1_div_required=True,
        aliases=("Source",),
    ),
    "source_event_key": _spec(
        ColType.ID,
        in_canonical=True,
        overlap_string=True,
        stage1_div_required=True,
        aliases=("Source Event Key",),
    ),
    "underlying": _spec(
        ColType.STRING,
        in_canonical=True,
        overlap_string=True,
        stage1_div_required=True,
        aliases=("Underlying", "Ticker"),
    ),
    "isin": _spec(
        ColType.STRING,
        in_canonical=True,
        overlap_required=True,
        overlap_string=True,
        stage1_div_required=True,
        aliases=("ISIN", "Isin"),
        upper=True,
        remove_spaces=True,
    ),
    "market": _spec(
        ColType.STRING,
        in_canonical=True,
        stage1_div_required=True,
    ),
    "currency": _spec(
        ColType.STRING,
        in_canonical=True,
        stage1_div_required=True,
        upper=True,
    ),
    "yfinance_ticker": _spec(
        ColType.STRING,
        in_canonical=True,
        upper=True,
    ),
    "action_type": _spec(
        ColType.STRING,
        in_canonical=True,
        stage1_div_required=True,
    ),
    "period_type": _spec(
        ColType.STRING,
        in_canonical=True,
    ),
    "share_class": _spec(
        ColType.STRING,
        in_canonical=True,
    ),
    "status": _spec(
        ColType.STRING,
        in_canonical=True,
        overlap_string=True,
        stage1_div_required=True,
        aliases=("Status",),
    ),
    "declared_date": _spec(
        ColType.DATE,
        in_canonical=True,
        overlap_date=True,
        aliases=("Declaration", "Declared"),
    ),
    "ex_date": _spec(
        ColType.DATE,
        in_canonical=True,
        overlap_required=True,
        overlap_date=True,
        stage1_div_required=True,
        aliases=("Ex", "Ex Date", "ex"),
    ),
    "record_date": _spec(
        ColType.DATE,
        in_canonical=True,
        overlap_date=True,
        aliases=("Record", "Record Date"),
    ),
    "pay_date": _spec(
        ColType.DATE,
        in_canonical=True,
        overlap_date=True,
        aliases=("Pay", "Pay Date", "pay"),
    ),
    "amount": _spec(
        ColType.NUMERIC,
        in_canonical=True,
        overlap_required=True,
        overlap_numeric=True,
        stage1_div_required=True,
        aliases=("Div Amount", "Dividend Amount", "Amount"),
    ),
    "amount_type": _spec(
        ColType.STRING,
        in_canonical=True,
        stage1_div_required=True,
    ),
    "amount_ccy": _spec(
        ColType.STRING,
        in_canonical=True,
        stage1_div_required=True,
        aliases=("Amount CCY", "amount_ccy"),
        upper=True,
    ),
    "confidence": _spec(
        ColType.NUMERIC,
        in_canonical=True,
        stage1_div_required=True,
        coerce_int=True,
    ),
    "evidence_json": _spec(
        ColType.STRING,
        in_canonical=True,
        stage1_div_required=True,
    ),
    "asof_date": _spec(
        ColType.DATE,
        in_canonical=True,
        stage1_div_required=True,
    ),
    "ingest_ts": _spec(
        ColType.STRING,
        in_canonical=True,
    ),
    "div_ccy": _spec(
        ColType.STRING,
        overlap_required=True,
        overlap_string=True,
        aliases=("div_ccy", "Div CCY", "Dividend Currency"),
        upper=True,
    ),
    "div_type": _spec(
        ColType.STRING,
        overlap_string=True,
        aliases=("Div Type", "Type"),
    ),
    "note": _spec(
        ColType.STRING,
        overlap_string=True,
        aliases=("Note",),
    ),
    # ticker-resolution / discovered-candidate generic fields
    "preverified_exists_any": _spec(
        ColType.BOOL,
        aliases=("exists_any",),
    ),
    "preverified_exists_ticker": _spec(
        ColType.STRING,
        upper=True,
        aliases=("preverified_ticker",),
    ),
    # legacy compatibility only
    "exists_ns": _spec(
        ColType.BOOL,
        aliases=("exists_ns",),
    ),
    "exists_bo": _spec(
        ColType.BOOL,
        aliases=("exists_bo",),
    ),
}


class SchemaRegistry:
    def __init__(self, specs: dict[str, ColumnSpec]) -> None:
        self._specs = specs
        self.canon_columns = [
            name
            for name, spec in specs.items()
            if spec.in_canonical
        ]
        self.overlap_required = [
            name
            for name, spec in specs.items()
            if spec.overlap_required
        ]

    def get_by_type(self, *dtypes: ColType, in_canonical: bool = True) -> list[str]:
        return [
            name
            for name, spec in self._specs.items()
            if spec.dtype in dtypes and (not in_canonical or spec.in_canonical)
        ]

    def filter_by_attr(self, attr_name: str) -> list[str]:
        return [
            name
            for name, spec in self._specs.items()
            if bool(getattr(spec, attr_name, False))
        ]


REGISTRY = SchemaRegistry(COLUMN_SPECS)

CANON_COLUMNS = REGISTRY.canon_columns
CANON_DATE_COLS = REGISTRY.get_by_type(ColType.DATE)
CANON_NUMERIC_COLS = REGISTRY.get_by_type(ColType.NUMERIC)
CANON_ID_COLS = REGISTRY.get_by_type(ColType.ID)
CANON_STRING_COLS = REGISTRY.get_by_type(ColType.STRING, ColType.ID)
CANON_BOOL_COLS = REGISTRY.get_by_type(ColType.BOOL)

OVERLAP_REQ_MIN = REGISTRY.overlap_required
OVERLAP_DATE_COLS = REGISTRY.filter_by_attr("overlap_date")
OVERLAP_STR_COLS = REGISTRY.filter_by_attr("overlap_string")
OVERLAP_NUM_COLS = REGISTRY.filter_by_attr("overlap_numeric")
STAGE1_DIVIDENDS_REQUIRED_COLUMNS = REGISTRY.filter_by_attr("stage1_div_required")

OVERLAP_OPTIONAL_COLUMNS = [
    "isin",
    "underlying_ccy",
    "status",
    "anchor_date",
    "declared_date",
    "holdings_tag",
    "holdings_file",
    "action_type",
    "share_class",
    "yfinance_ticker",
]

INPUT_HOLDINGS_REQUIRED_COLUMNS = [
    "underlying",
    "weight",
    "underlying_ccy",
]

STAGE1_ERRORS_REQUIRED_COLUMNS = [
    "source",
    "underlying",
    "underlying_ccy",
    "isin",
    "error",
    "candidates",
    "candidates_json",
    "candidate_count",
    "start",
    "end",
]

STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS = [
    "source",
    "underlying",
    "underlying_ccy",
    "isin",
    "status",
    "exists_ticker",
    "candidates",
    "candidates_json",
    "candidate_count",
    "start",
    "end",
]

DISCOVERED_CANDIDATE_REQUIRED_COLUMNS = [
    "source",
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
    "preverified_exists_any",
    "preverified_exists_ticker",
    "start",
    "end",
    "guess_source",
    "canonical_exchange",
    "isin_prefix",
    "prefix_exchange_consistent",
]

DISCOVERED_CANDIDATE_LEGACY_COLUMNS = [
    "exists_ns",
    "exists_bo",
]

NO_DIV_COLUMNS = list(STAGE1_NO_DIVIDENDS_REQUIRED_COLUMNS)


def build_default_column_map() -> dict[str, str]:
    out: dict[str, str] = {}

    for canonical, spec in COLUMN_SPECS.items():
        alias_candidates = (canonical, *spec.aliases)
        for alias in alias_candidates:
            key = _norm_key(alias)
            prev = out.get(key)
            if prev is not None and prev != canonical:
                raise ValueError(
                    f"Alias collision after normalisation: key={key!r} "
                    f"maps to both {prev!r} and {canonical!r}"
                )
            out[key] = canonical

    return out


DEFAULT_COLUMN_MAP = build_default_column_map()