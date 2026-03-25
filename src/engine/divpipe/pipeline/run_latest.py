# src/engine/divpipe/pipeline/run_latest.py

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)


def write_latest_pointer_file(runs_dir: Path, out_root_abs: Path) -> None:
    latest_txt = runs_dir / "latest.txt"
    latest_txt.write_text(str(out_root_abs), encoding="utf-8")


def update_latest_symlink(out_root: Path) -> tuple[bool, bool]:
    out_root_abs = out_root.resolve()
    runs_dir = out_root_abs.parent
    latest = runs_dir / "latest"
    tmp = runs_dir / ".latest_tmp"
    symlink_updated = False
    latest_txt_written = False

    if not runs_dir.exists() or not runs_dir.is_dir():
        logger.warning("runs dir not found; skip latest pointer update: %s", runs_dir)
        try:
            write_latest_pointer_file(runs_dir, out_root_abs)
            latest_txt_written = True
        except Exception as exc:
            logger.warning("failed to write latest.txt fallback after missing runs dir: %s", exc)
        return symlink_updated, latest_txt_written

    if out_root_abs.parent != runs_dir:
        logger.warning(
            "out_root not under runs dir; skip latest pointer update: out_root=%s runs_dir=%s",
            out_root_abs,
            runs_dir,
        )
        try:
            write_latest_pointer_file(runs_dir, out_root_abs)
            latest_txt_written = True
        except Exception as exc:
            logger.warning("failed to write latest.txt fallback after path mismatch: %s", exc)
        return symlink_updated, latest_txt_written

    try:
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
    except Exception:
        pass

    try:
        tmp.symlink_to(out_root_abs)

        try:
            if latest.exists() or latest.is_symlink():
                latest.unlink()
        except Exception:
            pass

        os.replace(tmp, latest)
        symlink_updated = True
    except OSError as exc:
        logger.warning("latest symlink update failed; continuing with latest.txt fallback: %s", exc)
        try:
            if tmp.exists() or tmp.is_symlink():
                tmp.unlink()
        except Exception:
            pass

    try:
        write_latest_pointer_file(runs_dir, out_root_abs)
        latest_txt_written = True
    except Exception as exc:
        logger.warning("failed to write latest.txt: %s", exc)

    return symlink_updated, latest_txt_written


def should_publish_latest(results: Sequence[object], *, publish_on_partial_failure: bool) -> bool:
    failed_count = sum(1 for result in results if getattr(result, "failed", False))
    if failed_count == 0:
        return True
    if publish_on_partial_failure:
        return True
    return False