"""
Tests for the spirit-box set_thresholds / get_live_stats tools (core/mcp_server.py).

Run:  uv run --with pytest --with numpy --with "mcp[cli]" pytest core/tests/test_mcp_thresholds.py -v

set_thresholds is run on a copy of the real core/config.toml, so the real file is never touched.
No hub is reachable at the test URL, so nothing running is affected.
"""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

mcp = pytest.importorskip("core.mcp_server")

REAL = Path(__file__).resolve().parents[1] / "config.toml"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    copy = tmp_path / "config.toml"
    shutil.copyfile(REAL, copy)
    monkeypatch.setattr(mcp, "_CONFIG", copy)
    monkeypatch.setattr(mcp, "_HUB_URL", "http://127.0.0.1:9")   # nothing listens there
    return copy


def comments(text: str) -> list[str]:
    return [line.split("#", 1)[1] for line in text.splitlines() if "#" in line]


def test_comments_and_layout_survive(cfg):
    before = cfg.read_text(encoding="utf-8")
    r = mcp.set_thresholds({"motion_threshold": 0.2, "fall_still_secs": 12})
    assert r["status"] == "ok", r
    after = cfg.read_text(encoding="utf-8")
    assert comments(after) == comments(before), "a comment was lost or changed"
    assert len(after.splitlines()) == len(before.splitlines())
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert len(changed) == 2, changed            # only the two value lines changed


def test_values_written_and_typed(cfg):
    mcp.set_thresholds({"motion_threshold": 0.2, "fall_links_min": 3.0, "fall_still_secs": 12})
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["zones"]["motion_threshold"] == 0.2
    assert data["state"]["fall_links_min"] == 3 and isinstance(data["state"]["fall_links_min"], int)
    assert data["state"]["fall_still_secs"] == 12.0 and isinstance(data["state"]["fall_still_secs"], float)


def test_round_trip_restores_the_file_exactly(cfg):
    # compare bytes, not text: a text comparison hides changed line endings
    original = cfg.read_bytes()
    old = tomllib.loads(original.decode("utf-8"))
    mcp.set_thresholds({"motion_threshold": 0.25, "empty_secs": 90})
    mcp.set_thresholds({"motion_threshold": old["zones"]["motion_threshold"],
                        "empty_secs": old["state"]["empty_secs"]})
    assert cfg.read_bytes() == original


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_line_endings_kept(cfg, newline):
    lines = REAL.read_bytes().replace(b"\r\n", b"\n").split(b"\n")
    cfg.write_bytes(newline.join(lines))
    mcp.set_thresholds({"motion_threshold": 0.2})
    data = cfg.read_bytes()
    other = b"\r\n" if newline == b"\n" else b"\n"
    if newline == b"\n":
        assert b"\r\n" not in data
    else:
        assert data.count(b"\r\n") == data.count(b"\n")
    assert other not in data or newline == b"\r\n"


@pytest.mark.parametrize("bad", [
    {"no_such_key": 1},
    {"motion_threshold": "high"},
    {"motion_threshold": -0.1},
    {"motion_threshold": True},
    {"fall_links_min": 2.5},
    {"window": 100},              # [pipeline] is not tunable through MCP
])
def test_bad_input_rejected_and_file_untouched(cfg, bad):
    before = cfg.read_text(encoding="utf-8")
    r = mcp.set_thresholds(bad)
    assert r["status"] == "error", r
    assert cfg.read_text(encoding="utf-8") == before


def test_reports_when_no_hub_is_running(cfg):
    r = mcp.set_thresholds({"motion_threshold": 0.18})
    assert "no hub reachable" in r["running_hub"]


def test_live_stats_falls_back_without_a_hub(monkeypatch):
    monkeypatch.setattr(mcp, "_HUB_URL", "http://127.0.0.1:9")
    s = mcp.get_live_stats()
    assert s["source"].startswith("last replay()")
    assert "values" not in s and "raw" not in s
