# src/providers/ishares_provider.py

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import requests

from providers.ishares_registry import get_fund_spec, get_registered_etfs

logger = logging.getLogger(__name__)

_JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "X-Requested-With": "XMLHttpRequest",
}
_HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_HOLDINGS_JSON_URL_PATTERNS = (
    re.compile(
        r'(?P<url>/us/products/\d+/[^"\']+/\d+\.ajax\?tab=all(?:&amp;|&)fileType=json)',
        re.IGNORECASE,
    ),
    re.compile(
        r'(?P<url>/us/products/\d+/[^"\']+/\d+\.ajax\?fileType=json(?:&amp;|&)tab=all)',
        re.IGNORECASE,
    ),
)

_ASOF_PATTERNS = (
    re.compile(r"\bas of\s+([A-Z][a-z]{2} \d{1,2}, \d{4})\b"),
    re.compile(r"\bAs of\s+([A-Z][a-z]{2} \d{1,2}, \d{4})\b"),
    re.compile(r'"asOfDate"\s*:\s*"([A-Z][a-z]{2} \d{1,2}, \d{4})"'),
    re.compile(r'"asOfDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"'),
)

_JSON_DATE_FORMATS = (
    "%b %d, %Y",
    "%Y-%m-%d",
)


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--etf",
        required=True,
        nargs="+",
        choices=get_registered_etfs(),
        help="ETF symbols registered in src/providers/ishares_registry.py",
    )
    ap.add_argument(
        "--out",
        default="data/raw/ishares",
        type=str,
        help="Directory for canonical raw JSON snapshots used by normalise",
    )
    ap.add_argument(
        "--emit-csv-cache",
        action="store_true",
        help="Also emit legacy CSV cache alongside JSON for manual inspection/backward compatibility",
    )
    ap.add_argument(
        "--csv-out",
        default="data/raw/ishares_csv",
        type=str,
        help="Directory for optional legacy CSV cache when --emit-csv-cache is enabled",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="divpipe ishares download")
    add_arguments(p)
    return p


def register_parser(subparsers) -> None:
    p = subparsers.add_parser("download", help="Download raw holdings from iShares JSON ajax endpoint")
    add_arguments(p)
    p.set_defaults(func=main_logic)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = build_parser()
    return p.parse_args(list(argv) if argv is not None else None)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception as exc:
            logger.warning("Failed to clean up temp file: %s (target=%s): %s", tmp_name, path, exc)


def _parse_json_asof_date(raw_date: str) -> str:
    text = str(raw_date).strip()
    for fmt in _JSON_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise ValueError(f"[CRITICAL] Unexpected iShares as-of date format: {raw_date!r}")


def _normalise_discovered_url(url_text: str) -> str:
    return url_text.replace("&amp;", "&")


def _discover_holdings_json_url_and_asof(product_url: str, *, timeout: float = 15.0) -> tuple[str, str]:
    resp = requests.get(product_url, timeout=timeout, headers=_HTML_HEADERS)
    resp.raise_for_status()
    html_text = resp.text

    json_url: str | None = None
    for pattern in _HOLDINGS_JSON_URL_PATTERNS:
        match = pattern.search(html_text)
        if match:
            relative_url = _normalise_discovered_url(match.group("url"))
            json_url = f"https://www.ishares.com{relative_url}"
            break

    if not json_url:
        raise ValueError(f"[CRITICAL] Could not discover holdings JSON url from HTML: {product_url}")

    raw_date: str | None = None
    for pattern in _ASOF_PATTERNS:
        match = pattern.search(html_text)
        if match:
            raw_date = match.group(1)
            break

    if not raw_date:
        raise ValueError(f"[CRITICAL] Could not discover as-of date from HTML: {product_url}")

    asof_yyyymmdd = _parse_json_asof_date(raw_date)
    return json_url, asof_yyyymmdd


def _load_ishares_json_with_bom(resp: requests.Response, *, symbol: str, json_url: str) -> dict[str, Any]:
    payload = resp.content

    try:
        decoded_text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Failed to decode iShares payload as utf-8-sig: symbol={symbol} url={json_url}"
        ) from exc

    stripped = decoded_text.lstrip()
    if not stripped:
        raise ValueError(
            f"Empty iShares payload: symbol={symbol} url={json_url} "
            f"status={resp.status_code} content_type={resp.headers.get('content-type', '')}"
        )

    if stripped[0] not in "{[":
        preview = stripped[:200].replace("\n", " ").replace("\r", " ")
        raise ValueError(
            f"Non-JSON iShares payload: symbol={symbol} url={json_url} "
            f"status={resp.status_code} content_type={resp.headers.get('content-type', '')} "
            f"preview={preview!r}"
        )

    try:
        data = json.loads(decoded_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to decode iShares JSON payload: symbol={symbol} url={json_url}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"[CRITICAL] iShares JSON root is not an object: symbol={symbol} url={json_url}"
        )

    aa_data = data.get("aaData")
    if not isinstance(aa_data, list):
        raise ValueError(
            f"[CRITICAL] iShares JSON missing aaData list: symbol={symbol} url={json_url}"
        )

    return data


def _extract_raw_value(x: Any) -> Any:
    if isinstance(x, dict):
        if "raw" in x:
            return x["raw"]
        if "display" in x:
            return x["display"]
        return ""
    return x


def _clean_text(x: Any) -> str:
    val = _extract_raw_value(x)
    if val is None:
        return ""
    return str(val).strip()


def _clean_float(x: Any) -> str:
    val = _extract_raw_value(x)

    if val is None:
        return ""

    if isinstance(val, (int, float)):
        return str(float(val))

    text = str(val).strip().replace(",", "").replace("$", "")
    if not text:
        return ""

    try:
        return str(float(text))
    except ValueError:
        return ""


def _row_get(row: list[Any], idx: int) -> Any:
    if 0 <= idx < len(row):
        return row[idx]
    return ""


def _aa_data_to_csv_bytes(
    *,
    aa_data: list[list[Any]],
    symbol: str,
    asof_yyyymmdd: str,
) -> bytes:
    header = [
        "Ticker",
        "Name",
        "Sector",
        "Asset Class",
        "Market Value",
        "Weight (%)",
        "Notional Value",
        "Quantity",
        "CUSIP",
        "ISIN",
        "SEDOL",
        "Price",
        "Location",
        "Exchange",
        "Currency",
        "FX Rate",
        "Accrual Date",
    ]

    rows: list[list[str]] = []
    for row in aa_data:
        padded = list(row) + [""] * max(0, 17 - len(row))

        rows.append(
            [
                _clean_text(_row_get(padded, 0)),
                _clean_text(_row_get(padded, 1)),
                _clean_text(_row_get(padded, 2)),
                _clean_text(_row_get(padded, 3)),
                _clean_float(_row_get(padded, 4)),
                _clean_float(_row_get(padded, 5)),
                _clean_float(_row_get(padded, 6)),
                _clean_float(_row_get(padded, 7)),
                _clean_text(_row_get(padded, 8)),
                _clean_text(_row_get(padded, 9)),
                _clean_text(_row_get(padded, 10)),
                _clean_float(_row_get(padded, 11)),
                _clean_text(_row_get(padded, 12)),
                _clean_text(_row_get(padded, 13)),
                _clean_text(_row_get(padded, 14)),
                _clean_float(_row_get(padded, 15)),
                _clean_text(_row_get(padded, 16)),
            ]
        )

    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([f"iShares holdings for {symbol}"])
    writer.writerow([f"Fund Holdings as of,{datetime.strptime(asof_yyyymmdd, '%Y%m%d').strftime('%b %d, %Y')}"])
    writer.writerow([])
    writer.writerow(header)
    writer.writerows(rows)

    return buf.getvalue().encode("utf-8-sig")


def _latest_raw_version_path(bucket: Path, *, suffix: str) -> Path | None:
    if not bucket.exists():
        return None

    items = list(bucket.glob(f"raw_*{suffix}"))
    if not items:
        return None

    def key(path: Path) -> int:
        m = re.match(rf"raw_(\d+){re.escape(suffix)}$", path.name)
        return int(m.group(1)) if m else -1

    return max(items, key=key)


def _next_raw_version_path(bucket: Path, *, suffix: str) -> Path:
    last = _latest_raw_version_path(bucket, suffix=suffix)
    if last is None:
        return bucket / f"raw_1{suffix}"

    m = re.match(rf"raw_(\d+){re.escape(suffix)}$", last.name)
    next_n = int(m.group(1)) + 1 if m else 1
    return bucket / f"raw_{next_n}{suffix}"


def _write_versioned_payload(
    *,
    payload: bytes,
    asof_yyyymmdd: str,
    symbol_u: str,
    versions_root: Path,
    suffix: str,
) -> None:
    bucket = versions_root / symbol_u / asof_yyyymmdd
    bucket.mkdir(parents=True, exist_ok=True)

    payload_hash = _sha256_bytes(payload)
    last = _latest_raw_version_path(bucket, suffix=suffix)

    if last is None:
        _atomic_write_bytes(_next_raw_version_path(bucket, suffix=suffix), payload)
        return

    last_hash = _sha256_bytes(last.read_bytes())
    if last_hash != payload_hash:
        _atomic_write_bytes(_next_raw_version_path(bucket, suffix=suffix), payload)


def download_holdings_json_and_optional_csv(
    symbol: str,
    out_dir: Path,
    *,
    emit_csv_cache: bool = False,
    csv_out_dir: Path | None = None,
    json_versions_root: Path = Path("data/raw_versions/ishares_json"),
    csv_versions_root: Path = Path("data/raw_versions/ishares_csv"),
) -> Path:
    fund = get_fund_spec(symbol)
    symbol_u = fund.symbol.upper()

    out_dir.mkdir(parents=True, exist_ok=True)
    json_versions_root.mkdir(parents=True, exist_ok=True)

    if emit_csv_cache:
        if csv_out_dir is None:
            raise ValueError("csv_out_dir must be provided when emit_csv_cache=True")
        csv_out_dir.mkdir(parents=True, exist_ok=True)
        csv_versions_root.mkdir(parents=True, exist_ok=True)

    json_url, asof_yyyymmdd_html = _discover_holdings_json_url_and_asof(fund.product_url)

    resp = requests.get(json_url, timeout=30, headers=_JSON_HEADERS)
    resp.raise_for_status()

    data = _load_ishares_json_with_bom(resp, symbol=symbol_u, json_url=json_url)
    json_payload = resp.content

    raw_json_date = data.get("asOfDate")
    if raw_json_date:
        asof_yyyymmdd_json = _parse_json_asof_date(str(raw_json_date))
        if asof_yyyymmdd_json != asof_yyyymmdd_html:
            raise ValueError(
                "[CRITICAL] HTML/JSON as-of mismatch: "
                f"symbol={symbol_u} html={asof_yyyymmdd_html} json={asof_yyyymmdd_json} url={json_url}"
            )

    _write_versioned_payload(
        payload=json_payload,
        asof_yyyymmdd=asof_yyyymmdd_html,
        symbol_u=symbol_u,
        versions_root=json_versions_root,
        suffix=".json",
    )

    json_cache_path = out_dir / f"{asof_yyyymmdd_html}_{symbol_u}.json"
    _atomic_write_bytes(json_cache_path, json_payload)

    if emit_csv_cache:
        aa_data = data["aaData"]
        csv_payload = _aa_data_to_csv_bytes(
            aa_data=aa_data,
            symbol=symbol_u,
            asof_yyyymmdd=asof_yyyymmdd_html,
        )

        _write_versioned_payload(
            payload=csv_payload,
            asof_yyyymmdd=asof_yyyymmdd_html,
            symbol_u=symbol_u,
            versions_root=csv_versions_root,
            suffix=".csv",
        )

        csv_cache_path = csv_out_dir / f"{asof_yyyymmdd_html}_{symbol_u}.csv"
        _atomic_write_bytes(csv_cache_path, csv_payload)

        logger.info(
            "Downloaded iShares holdings: symbol=%s asof=%s json_url=%s json_path=%s csv_path=%s",
            symbol_u,
            asof_yyyymmdd_html,
            json_url,
            json_cache_path,
            csv_cache_path,
        )
    else:
        logger.info(
            "Downloaded iShares holdings: symbol=%s asof=%s json_url=%s json_path=%s",
            symbol_u,
            asof_yyyymmdd_html,
            json_url,
            json_cache_path,
        )

    return json_cache_path


def main_logic(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    csv_out_dir = Path(args.csv_out) if bool(args.emit_csv_cache) else None

    for etf in args.etf:
        out_path = download_holdings_json_and_optional_csv(
            etf,
            out_dir=out_dir,
            emit_csv_cache=bool(args.emit_csv_cache),
            csv_out_dir=csv_out_dir,
        )
        print(str(out_path))


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    main_logic(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()