# src/providers/ishares_registry.py

from __future__ import annotations

from dataclasses import dataclass

ISHARES_BASE_URL = "https://www.ishares.com/us/products"


@dataclass(frozen=True)
class ISharesFundSpec:
    symbol: str
    product_path: str
    default_coverage: str
    region_tag: str = "Global"

    @property
    def product_url(self) -> str:
        return f"{ISHARES_BASE_URL}/{self.product_path}"


ISHARES_REGISTRY: dict[str, ISharesFundSpec] = {
    "EEM": ISharesFundSpec(
        symbol="EEM",
        product_path="239637/ishares-msci-emerging-markets-etf",
        default_coverage="EM",
        region_tag="Emerging Markets",
    ),
    "EFA": ISharesFundSpec(
        symbol="EFA",
        product_path="239623/ishares-msci-eafe-etf",
        default_coverage="DM",
        region_tag="Developed Markets",
    ),
}


def get_registered_etfs() -> list[str]:
    return sorted(ISHARES_REGISTRY.keys())


def get_fund_spec(symbol: str) -> ISharesFundSpec:
    key = str(symbol).strip().upper()
    try:
        return ISHARES_REGISTRY[key]
    except KeyError as exc:
        valid = ", ".join(get_registered_etfs())
        raise ValueError(f"Unknown ETF: {symbol!r}. Valid ETFs: {valid}") from exc