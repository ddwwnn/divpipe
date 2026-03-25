# tests/test_latest_run_resolution.py

from __future__ import annotations

import os
import time
from pathlib import Path

from scripts.check_severity import resolve_run_root


def _touch_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    (p / ".keep").write_text("x", encoding="utf-8")


def test_resolve_run_root_prefers_latest_symlink(tmp_path: Path) -> None:
    runs_dir = tmp_path / "output" / "runs"
    runs_dir.mkdir(parents=True)

    a = runs_dir / "divpipe__A"
    b = runs_dir / "divpipe__B"
    _touch_dir(a)
    _touch_dir(b)

    # make B newer, but latest -> A should win
    time.sleep(0.02)
    os.utime(b, None)

    latest = runs_dir / "latest"
    latest.symlink_to(a, target_is_directory=True)

    got = resolve_run_root(runs_dir, run_root_arg="")
    assert got.resolve() == a.resolve()


def test_resolve_run_root_falls_back_to_newest_mtime_when_no_latest(tmp_path: Path) -> None:
    runs_dir = tmp_path / "output" / "runs"
    runs_dir.mkdir(parents=True)

    old = runs_dir / "divpipe__OLD"
    new = runs_dir / "divpipe__NEW"
    _touch_dir(old)
    time.sleep(0.02)
    _touch_dir(new)

    got = resolve_run_root(runs_dir, run_root_arg="")
    assert got.resolve() == new.resolve()


def test_resolve_run_root_honours_explicit_arg(tmp_path: Path) -> None:
    runs_dir = tmp_path / "output" / "runs"
    runs_dir.mkdir(parents=True)

    explicit = tmp_path / "somewhere" / "explicit_run"
    _touch_dir(explicit)

    got = resolve_run_root(runs_dir, run_root_arg=str(explicit))
    assert got.resolve() == explicit.resolve()