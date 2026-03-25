# src/engine/divpipe/config/venue_policy_constants.py

from __future__ import annotations

POLICY_BUCKET_PASS = "pass"
POLICY_BUCKET_UNSUPPORTED = "unsupported"
POLICY_BUCKET_COVERAGE_LIMITED_REVIEW = "coverage_limited_review"
POLICY_BUCKET_CANDIDATE_AMBIGUITY_REVIEW = "candidate_ambiguity_review"
POLICY_BUCKET_VENUE_POLICY_REVIEW = "venue_policy_review"

POLICY_REASON_RU_LOCAL_UNSUPPORTED = "ru_local_venue_unsupported"
POLICY_REASON_UAE_SYMBOL_POLICY_GAP = "uae_symbol_policy_gap"
POLICY_REASON_PS_COVERAGE_LIMITED = "ps_coverage_limited"
POLICY_REASON_HK_SG_CROSS_LIST_AMBIGUITY = "hk_sg_cross_list_ambiguity"
POLICY_REASON_NS_BO_DUAL_LIST_AMBIGUITY = "ns_bo_dual_list_ambiguity"

RU_COUNTRY_TOKENS = (
    "RUSSIAN FEDERATION",
    "RUSSIA",
)

UAE_COUNTRY_TOKENS = (
    "UNITED ARAB EMIRATES",
    "UAE",
)

PH_COUNTRY_TOKENS = (
    "PHILIPPINES",
    "PHILIPPINE",
)

RU_LOCAL_SUFFIXES = (
    ".ME",
)

RU_CLEARLY_NON_LOCAL_SUFFIXES = (
    ".L",
    ".US",
    ".N",
    ".O",
    ".K",
)

UAE_SUFFIXES = (
    ".AD",
    ".AB",
    ".DU",
)

PH_SUFFIXES = (
    ".PS",
)

HK_SUFFIXES = (
    ".HK",
)

SG_SUFFIXES = (
    ".SG",
)

NS_SUFFIXES = (
    ".NS",
)

BO_SUFFIXES = (
    ".BO",
)

UAE_EXCHANGE_TOKENS = (
    "ABU DHABI",
    "ADX",
    "DUBAI",
    "DFM",
)

NO_DIV_POLICY_STATUSES = (
    "verified_exists_but_no_dividends",
    "candidate_unverified",
    "ticker_not_found",
)