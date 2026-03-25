# src/engine/divpipe/pipeline/run_resolution.py

from __future__ import annotations

from pathlib import Path
from typing import Sequence

_VALID_REGIONS = {"EM", "DM"}


def known_etf_tags() -> set[str]:
    try:
        from providers.ishares_registry import get_registered_etfs

        return {str(x).strip().upper() for x in get_registered_etfs()}
    except Exception:
        return set()


def tokenise_tag_candidates(path: Path) -> list[str]:
    stem = path.stem.upper()
    tokens: list[str] = []
    current: list[str] = []

    for ch in stem:
        if ch.isalnum():
            current.append(ch)
            continue
        if current:
            tokens.append("".join(current))
            current = []

    if current:
        tokens.append("".join(current))

    return tokens


def infer_tag(path: Path) -> str:
    tokens = tokenise_tag_candidates(path)
    known = known_etf_tags()

    if known:
        hits = [token for token in tokens if token in known]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"Ambiguous tag inference for {path}: hits={hits}")

    generic_noise = {"HOLDINGS", "FULL", "MIN", "CSV", "DATA", "OUTPUT", "INPUT"}
    for token in tokens:
        if token not in generic_noise and not (len(token) == 8 and token.isdigit()):
            return token

    raise ValueError(f"Could not infer tag from holdings path: {path}. Pass --tags explicitly.")


def resolve_tags(
    holdings_paths: list[Path],
    explicit_tags: Sequence[str] | None,
    *,
    allow_inference: bool = True,
) -> list[str]:
    if explicit_tags is not None:
        tags = [str(tag).strip().upper() for tag in explicit_tags]
        if len(tags) != len(holdings_paths):
            raise ValueError(
                f"--tags length must match --holdings length: tags={len(tags)} holdings={len(holdings_paths)}"
            )
        if len(set(tags)) != len(tags):
            raise ValueError(f"--tags must be unique: {tags}")
        return tags

    if not allow_inference:
        raise ValueError("--tags is required unless --allow-tag-inference is explicitly set.")

    tags = [infer_tag(path) for path in holdings_paths]
    if len(set(tags)) != len(tags):
        raise ValueError(f"Inferred tags must be unique; pass --tags explicitly. inferred={tags}")
    return tags


def infer_universe_region(tag: str) -> str | None:
    tag_u = str(tag).strip().upper()

    try:
        from providers.ishares_registry import get_fund_spec

        fund_spec = get_fund_spec(tag_u)
        default_coverage = str(fund_spec.default_coverage).strip().upper()
        if default_coverage in _VALID_REGIONS:
            return default_coverage
    except Exception:
        pass

    return None


def resolve_regions(tags: Sequence[str], explicit_regions: Sequence[str] | None) -> list[str]:
    if explicit_regions is not None:
        regions = [str(region).strip().upper() for region in explicit_regions]
        if len(regions) != len(tags):
            raise ValueError(
                f"--regions length must match resolved tags length: regions={len(regions)} tags={len(tags)}"
            )

        bad = [region for region in regions if region not in _VALID_REGIONS]
        if bad:
            raise ValueError(f"--regions contains invalid values: {bad}. allowed={sorted(_VALID_REGIONS)}")

        return regions

    inferred_regions: list[str] = []
    missing_tags: list[str] = []

    for tag in tags:
        region = infer_universe_region(tag)
        if region is None:
            missing_tags.append(tag)
            continue
        inferred_regions.append(region)

    if missing_tags:
        raise ValueError(
            "Could not infer regions for tags "
            f"{missing_tags}. Pass --regions explicitly or register default_coverage for those tags."
        )

    return inferred_regions