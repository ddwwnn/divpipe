# src/engine/divpipe/cli.py

from __future__ import annotations

import argparse
import logging
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="divpipe")
    ap.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    sub = ap.add_subparsers(dest="cmd", required=True)

    from providers import ishares_normaliser, ishares_provider

    from . import check_severity, debug_link, run_pipeline

    run_pipeline.register_parser(sub)
    check_severity.register_parser(sub)
    debug_link.register_parser(sub)

    ishares = sub.add_parser("ishares", help="iShares holdings utilities")
    ishares_sub = ishares.add_subparsers(dest="ishares_cmd", required=True)

    ishares_provider.register_parser(ishares_sub)
    ishares_normaliser.register_parser(ishares_sub)

    return ap


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )

    args.func(args)


if __name__ == "__main__":
    main()