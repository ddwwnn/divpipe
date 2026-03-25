# src/engine/divpipe/utils/ticker_map.py

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


@dataclass(frozen=True)
class TickerGuess:
    market: str
    yfinance_ticker: str
    canonical_exchange: str = ""
    guess_source: str = ""
    isin_prefix: str = ""
    prefix_exchange_consistent: bool = True


@dataclass(frozen=True)
class ExchangeRule:
    match_type: str
    match_value: str
    canonical_exchange: str
    suffixes: tuple[str, ...]
    priority: int
    is_active: bool
    note: str


@dataclass(frozen=True)
class ExchangeRulesIndex:
    exact_map: dict[str, ExchangeRule]
    contains_rules: tuple[ExchangeRule, ...]


_CONFIG_PATH = Path("data/config/exchange_map.csv")

_NULL_LIKE = {"", "NA", "NAN", "NONE", "<NA>", "-"}
_ALLOWED_UNDERLYING = re.compile(r"^[0-9A-Za-z.\-_=*]+$")
_LOCAL_SUFFIX_RE = re.compile(r"^([0-9A-Za-z*]+)\.([A-Za-z]{1,4})$")
_STRICT_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Conservative hard bound for obviously broken input.
_MAX_UNDERLYING_LEN = 64

_YF_SUFFIXES = {
    "HK",
    "KS",
    "KQ",
    "T",
    "TW",
    "TWO",
    "NS",
    "BO",
    "SS",
    "SZ",
    "SA",
    "JO",
    "SR",
    "PS",
    "IS",
    "BK",
    "JK",
    "KL",
    "SI",
    "QA",
    "KW",
    "BD",
    "AD",
    "DU",
    "WA",
    "PR",
    "SN",
    "AX",
    "L",
    "PA",
    "DE",
    "SW",
    "AT",
    "AS",
    "MI",
    "MC",
    "HE",
    "VI",
    "LS",
    "IR",
    "BR",
    "CO",
    "OL",
    "NZ",
    "TA",
    "ST",
    "",
}

# Exchange missing / fuzzy fallback only.
_COUNTRY_TO_SUFFIXES: dict[str, tuple[str, ...]] = {
    "AUSTRALIA": ("AX",),
    "AUSTRIA": ("VI",),
    "BELGIUM": ("BR",),
    "BRAZIL": ("SA",),
    "CHILE": ("SN",),
    "CHINA": ("HK", "SS", "SZ"),
    "CZECH REPUBLIC": ("PR",),
    "DENMARK": ("CO",),
    "FINLAND": ("HE",),
    "FRANCE": ("PA",),
    "GERMANY": ("DE",),
    "GREECE": ("AT",),
    "HONG KONG": ("HK",),
    "HUNGARY": ("BD",),
    "INDIA": ("NS", "BO"),
    "INDONESIA": ("JK",),
    "IRELAND": ("IR",),
    "ISRAEL": ("TA",),
    "ITALY": ("MI",),
    "JAPAN": ("T",),
    "KOREA (SOUTH)": ("KS", "KQ"),
    "KUWAIT": ("KW",),
    "MALAYSIA": ("KL",),
    "MEXICO": ("MX",),
    "NETHERLANDS": ("AS",),
    "NEW ZEALAND": ("NZ",),
    "NORWAY": ("OL",),
    "PHILIPPINES": ("PS",),
    "POLAND": ("WA",),
    "PORTUGAL": ("LS",),
    "QATAR": ("QA",),
    "SAUDI ARABIA": ("SR",),
    "SINGAPORE": ("SI",),
    "SOUTH AFRICA": ("JO",),
    "SPAIN": ("MC",),
    "SWEDEN": ("ST",),
    "SWITZERLAND": ("SW",),
    "TAIWAN": ("TW", "TWO"),
    "THAILAND": ("BK",),
    "TURKEY": ("IS",),
    "UNITED ARAB EMIRATES": ("AD", "DU"),
    "UNITED KINGDOM": ("L",),
}

# True last-resort fallback only.
_CCY_TO_SUFFIXES: dict[str, tuple[str, ...]] = {
    "BRL": ("SA",),
    "HKD": ("HK",),
    "KRW": ("KS", "KQ"),
    "TWD": ("TW", "TWO"),
    "JPY": ("T",),
    "INR": ("NS", "BO"),
    "CNY": ("SS", "SZ"),
    "SAR": ("SR",),
    "THB": ("BK",),
    "IDR": ("JK",),
    "MYR": ("KL",),
    "SGD": ("SI",),
    "QAR": ("QA",),
    "KWD": ("KW",),
    "MXN": ("MX",),
    "PHP": ("PS",),
    "HUF": ("BD",),
    "PLN": ("WA",),
    "TRY": ("IS",),
    "ZAR": ("JO",),
}

# Validation only. Never direct suffix mapping.
_PREFIX_VENUE_HINTS: dict[str, frozenset[str]] = {
    "AE": frozenset({"ABU_DHABI_SECURITIES_EXCHANGE", "DUBAI_FINANCIAL_MARKET"}),
    "AT": frozenset({"WIENER_BOERSE"}),
    "AU": frozenset({"AUSTRALIAN_SECURITIES_EXCHANGE"}),
    "BE": frozenset({"EURONEXT_BRUSSELS"}),
    "BM": frozenset({"HONG_KONG_EXCHANGE", "US_NYSE", "US_NASDAQ", "SINGAPORE_EXCHANGE", "EURONEXT_AMSTERDAM"}),
    "BR": frozenset({"BRAZIL_B3"}),
    "CH": frozenset({"SIX_SWISS_EXCHANGE"}),
    "CL": frozenset({"SANTIAGO_STOCK_EXCHANGE"}),
    "CN": frozenset({"SHANGHAI_STOCK_EXCHANGE", "SHENZHEN_STOCK_EXCHANGE", "HONG_KONG_EXCHANGE"}),
    "CZ": frozenset({"PRAGUE_STOCK_EXCHANGE"}),
    "DE": frozenset({"XETRA"}),
    "DK": frozenset({"OMX_COPENHAGEN"}),
    "ES": frozenset({"BOLSA_DE_MADRID", "EURONEXT_LISBON"}),
    "FI": frozenset({"NASDAQ_HELSINKI"}),
    "FR": frozenset({"EURONEXT_PARIS"}),
    "GB": frozenset({"LONDON_STOCK_EXCHANGE", "US_NASDAQ", "US_NYSE", "NASDAQ_NORDIC"}),
    "GR": frozenset({"ATHENS_EXCHANGE"}),
    "HK": frozenset({"HONG_KONG_EXCHANGE"}),
    "HU": frozenset({"BUDAPEST_STOCK_EXCHANGE"}),
    "ID": frozenset({"INDONESIA_STOCK_EXCHANGE"}),
    "IE": frozenset({"IRISH_STOCK_EXCHANGE"}),
    "IL": frozenset({"TEL_AVIV_STOCK_EXCHANGE", "US_NASDAQ", "US_NYSE"}),
    "IN": frozenset({"NSE_INDIA", "BSE_INDIA"}),
    "IT": frozenset({"BORSA_ITALIANA"}),
    "JE": frozenset({"LONDON_STOCK_EXCHANGE", "EURONEXT_AMSTERDAM"}),
    "JP": frozenset({"TOKYO_STOCK_EXCHANGE"}),
    "KR": frozenset({"KOREA_STOCK_EXCHANGE", "KOREA_KOSDAQ"}),
    "KW": frozenset({"KUWAIT_STOCK_EXCHANGE"}),
    "KY": frozenset({"HONG_KONG_EXCHANGE", "US_NASDAQ", "US_NYSE"}),
    "LU": frozenset({"EURONEXT_PARIS", "BORSA_ITALIANA", "EURONEXT_AMSTERDAM", "JOHANNESBURG_STOCK_EXCHANGE", "US_NYSE"}),
    "MX": frozenset({"BOLSA_MEXICANA_DE_VALORES"}),
    "MY": frozenset({"BURSA_MALAYSIA"}),
    "NL": frozenset({"EURONEXT_AMSTERDAM", "BORSA_ITALIANA", "EURONEXT_PARIS", "US_NASDAQ", "US_NYSE", "BOLSA_DE_MADRID"}),
    "NO": frozenset({"OSLO_BORS"}),
    "NZ": frozenset({"NEW_ZEALAND_EXCHANGE", "AUSTRALIAN_SECURITIES_EXCHANGE"}),
    "PH": frozenset({"PHILIPPINE_STOCK_EXCHANGE"}),
    "PL": frozenset({"WARSAW_STOCK_EXCHANGE"}),
    "PT": frozenset({"EURONEXT_LISBON"}),
    "QA": frozenset({"QATAR_EXCHANGE"}),
    "RU": frozenset({"STANDARD_CLASSICA_FORTS", "LONDON_STOCK_EXCHANGE"}),
    "SA": frozenset({"SAUDI_STOCK_EXCHANGE"}),
    "SE": frozenset({"NASDAQ_NORDIC", "US_NYSE"}),
    "SG": frozenset({"SINGAPORE_EXCHANGE", "HONG_KONG_EXCHANGE"}),
    "TH": frozenset({"THAILAND_STOCK_EXCHANGE"}),
    "TR": frozenset({"ISTANBUL_STOCK_EXCHANGE"}),
    "TW": frozenset({"TAIWAN_STOCK_EXCHANGE", "TAIWAN_OTC"}),
    "US": frozenset({"US_NASDAQ", "US_NYSE", "LONDON_STOCK_EXCHANGE", "HONG_KONG_EXCHANGE", "STANDARD_CLASSICA_FORTS"}),
    "ZA": frozenset({"JOHANNESBURG_STOCK_EXCHANGE"}),
}


def _clean_text(x: Any, *, upper: bool = False) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.upper() in _NULL_LIKE:
        return ""
    return s.upper() if upper else s


def _normalise_country_name(country: str | None) -> str:
    s = _clean_text(country, upper=True)
    return " ".join(s.split())


def _normalise_exchange_name(exchange: str | None) -> str:
    s = _clean_text(exchange, upper=True)
    if not s:
        return ""
    s = " ".join(s.split())
    s = s.replace("&", "AND")
    s = s.replace("CO.", "COMPANY")
    s = s.replace("LTD", "LTD.")
    s = s.replace("  ", " ")
    return s


def _is_strict_valid_isin(isin: str | None) -> bool:
    s = _clean_text(isin, upper=True).replace(" ", "")
    return bool(_STRICT_ISIN_RE.fullmatch(s))


def _extract_soft_isin_prefix(isin: str | None) -> str:
    s = _clean_text(isin, upper=True).replace(" ", "")
    if len(s) < 2:
        return ""
    prefix = s[:2]
    return prefix if prefix.isalpha() else ""


def _strict_isin_prefix(isin: str | None) -> str:
    s = _clean_text(isin, upper=True).replace(" ", "")
    if not _is_strict_valid_isin(s):
        return ""
    return s[:2]


def _zfill_numeric(x: str, n: int) -> str:
    s = str(x).strip()
    return s.zfill(n) if re.fullmatch(r"\d+", s) else s


def _looks_like_yfinance_ticker(u: str) -> bool:
    u = str(u).strip()
    parts = u.split(".")
    if len(parts) != 2:
        return False
    base, suf = parts[0], parts[1].upper()
    return bool(base) and (suf in _YF_SUFFIXES)


def _strip_local_suffix(u: str) -> str:
    s = str(u).strip()
    if _looks_like_yfinance_ticker(s):
        return s
    m = _LOCAL_SUFFIX_RE.fullmatch(s)
    if not m:
        return s
    return m.group(1)


def _parse_suffixes(raw: str) -> tuple[str, ...]:
    parts = [_clean_text(x, upper=True) for x in str(raw or "").split("|")]
    out = tuple(x for x in parts if x in _YF_SUFFIXES)
    return out


def _validate_exchange_rule_row(raw: dict[str, str], row_num: int) -> ExchangeRule:
    match_type = _clean_text(raw.get("match_type", ""), upper=True)
    if match_type not in {"EXACT", "CONTAINS"}:
        raise ValueError(f"exchange_map.csv row {row_num}: invalid match_type={match_type!r}")

    match_value = _normalise_exchange_name(raw.get("match_value", ""))
    if not match_value:
        raise ValueError(f"exchange_map.csv row {row_num}: blank match_value")

    canonical_exchange = _clean_text(raw.get("canonical_exchange", ""), upper=True)
    if not canonical_exchange:
        raise ValueError(f"exchange_map.csv row {row_num}: blank canonical_exchange")

    priority_raw = _clean_text(raw.get("priority", ""))
    if not priority_raw.isdigit():
        raise ValueError(f"exchange_map.csv row {row_num}: invalid priority={priority_raw!r}")
    priority = int(priority_raw)

    is_active_raw = _clean_text(raw.get("is_active", "1"), upper=True)
    if is_active_raw in {"0", "FALSE", "N", "NO"}:
        is_active = False
    elif is_active_raw in {"1", "TRUE", "Y", "YES", ""}:
        is_active = True
    else:
        raise ValueError(f"exchange_map.csv row {row_num}: invalid is_active={is_active_raw!r}")

    suffixes = _parse_suffixes(raw.get("suffixes", ""))
    note = _clean_text(raw.get("note", ""))

    return ExchangeRule(
        match_type=match_type,
        match_value=match_value,
        canonical_exchange=canonical_exchange,
        suffixes=suffixes,
        priority=priority,
        is_active=is_active,
        note=note,
    )


@lru_cache(maxsize=1)
def _load_exchange_rules_index() -> ExchangeRulesIndex:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"exchange mapping config not found: {_CONFIG_PATH}")

    rules: list[ExchangeRule] = []
    with _CONFIG_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"match_type", "match_value", "canonical_exchange", "suffixes", "priority", "is_active", "note"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"exchange_map.csv missing required columns: {sorted(missing)}")

        for row_num, raw in enumerate(reader, start=2):
            rule = _validate_exchange_rule_row(raw, row_num)
            if rule.is_active:
                rules.append(rule)

    exact_map: dict[str, ExchangeRule] = {}
    contains_rules: list[ExchangeRule] = []

    for rule in sorted(rules, key=lambda r: (r.priority, r.match_type, r.match_value)):
        if rule.match_type == "EXACT":
            if rule.match_value in exact_map:
                raise ValueError(f"duplicate EXACT exchange rule for {rule.match_value!r}")
            exact_map[rule.match_value] = rule
        else:
            contains_rules.append(rule)

    return ExchangeRulesIndex(
        exact_map=exact_map,
        contains_rules=tuple(contains_rules),
    )


def _match_exchange_rule(exchange: str | None) -> tuple[str, tuple[str, ...]]:
    ex = _normalise_exchange_name(exchange)
    if not ex:
        return "", tuple()

    idx = _load_exchange_rules_index()

    exact = idx.exact_map.get(ex)
    if exact is not None:
        return exact.canonical_exchange, exact.suffixes

    for rule in idx.contains_rules:
        if rule.match_value in ex:
            return rule.canonical_exchange, rule.suffixes

    return "", tuple()


def _suffixes_from_country(country: str | None) -> tuple[str, ...]:
    return _COUNTRY_TO_SUFFIXES.get(_normalise_country_name(country), tuple())


def _suffixes_from_ccy(ccy: str | None) -> tuple[str, ...]:
    return _CCY_TO_SUFFIXES.get(_clean_text(ccy, upper=True), tuple())


def _is_unsupported_jurisdiction(country: str | None, exchange: str | None, isin: str | None) -> bool:
    c = _normalise_country_name(country)
    ex = _normalise_exchange_name(exchange)
    prefix = _extract_soft_isin_prefix(isin)

    if c == "RUSSIAN FEDERATION":
        return True
    if ex in {"STANDARD-CLASSICA-FORTS", "STANDARD CLASSICA-FORTS"}:
        return True
    if prefix == "RU":
        return True

    return False


def _identity_formatter(u: str) -> str:
    return u


_SUFFIX_FORMATTERS: dict[str, Callable[[str], str]] = {
    "HK": lambda u: _zfill_numeric(u, 4),
    "KS": lambda u: _zfill_numeric(u, 6),
    "KQ": lambda u: _zfill_numeric(u, 6),
    "TW": lambda u: _zfill_numeric(u, 4),
    "TWO": lambda u: _zfill_numeric(u, 4),
    "T": lambda u: _zfill_numeric(u, 4),
    "SS": lambda u: _zfill_numeric(u, 6),
    "SZ": lambda u: _zfill_numeric(u, 6),
    "SR": lambda u: _zfill_numeric(u, 4),
}


def _base_underlying_for_suffix(underlying: str, suffix: str) -> str:
    u = _strip_local_suffix(underlying)
    suf = _clean_text(suffix, upper=True)
    formatter = _SUFFIX_FORMATTERS.get(suf, _identity_formatter)
    return formatter(u)


def _build_ticker_from_suffix(underlying: str, suffix: str) -> str:
    base = _base_underlying_for_suffix(underlying, suffix)
    if not base:
        return ""
    if suffix == "":
        return base
    return f"{base}.{suffix}"


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = _clean_text(item)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _validate_prefix_vs_exchange(isin_prefix: str, canonical_exchange: str) -> bool:
    if not isin_prefix or not canonical_exchange:
        return True

    allowed = _PREFIX_VENUE_HINTS.get(isin_prefix)
    if allowed is None:
        return True
    if not allowed:
        return True

    return canonical_exchange in allowed


def _make_guesses(
    *,
    underlying: str,
    suffixes: tuple[str, ...],
    canonical_exchange: str,
    guess_source: str,
    isin_prefix: str,
    prefix_exchange_consistent: bool,
) -> list[TickerGuess]:
    out: list[TickerGuess] = []
    for suffix in suffixes:
        ticker = _build_ticker_from_suffix(underlying, suffix)
        if not ticker:
            continue
        market = ticker.split(".")[-1] if "." in ticker else "US"
        out.append(
            TickerGuess(
                market=market,
                yfinance_ticker=ticker,
                canonical_exchange=canonical_exchange,
                guess_source=guess_source,
                isin_prefix=isin_prefix,
                prefix_exchange_consistent=prefix_exchange_consistent,
            )
        )
    return out


def guess_yfinance_tickers(
    underlying: str,
    ccy: str,
    *,
    country: Optional[str] = None,
    exchange: Optional[str] = None,
    isin: Optional[str] = None,
    universe_region: str = "EM",
) -> list[TickerGuess]:
    del universe_region  # kept for call compatibility

    u_raw = str(underlying).strip()

    if not u_raw:
        return []

    if len(u_raw) > _MAX_UNDERLYING_LEN:
        return []

    if not _ALLOWED_UNDERLYING.fullmatch(u_raw):
        return []

    if _looks_like_yfinance_ticker(u_raw):
        return [
            TickerGuess(
                market="ASIS",
                yfinance_ticker=u_raw,
                canonical_exchange="",
                guess_source="asis",
                isin_prefix=_extract_soft_isin_prefix(isin),
                prefix_exchange_consistent=True,
            )
        ]

    if _is_unsupported_jurisdiction(country=country, exchange=exchange, isin=isin):
        return []

    canonical_exchange, ex_suffixes = _match_exchange_rule(exchange)
    country_suffixes = _suffixes_from_country(country)
    ccy_suffixes = _suffixes_from_ccy(ccy)
    isin_prefix = _extract_soft_isin_prefix(isin)

    if ex_suffixes:
        return _make_guesses(
            underlying=u_raw,
            suffixes=ex_suffixes,
            canonical_exchange=canonical_exchange,
            guess_source="exchange_rule",
            isin_prefix=isin_prefix,
            prefix_exchange_consistent=_validate_prefix_vs_exchange(isin_prefix, canonical_exchange),
        )

    if country_suffixes:
        return _make_guesses(
            underlying=u_raw,
            suffixes=country_suffixes,
            canonical_exchange="",
            guess_source="country_fallback",
            isin_prefix=isin_prefix,
            prefix_exchange_consistent=True,
        )

    if ccy_suffixes:
        return _make_guesses(
            underlying=u_raw,
            suffixes=ccy_suffixes,
            canonical_exchange="",
            guess_source="ccy_fallback",
            isin_prefix=isin_prefix,
            prefix_exchange_consistent=True,
        )

    return []