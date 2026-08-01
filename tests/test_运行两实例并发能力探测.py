from __future__ import annotations

from pathlib import Path

import pytest

from wt4.运行两实例并发能力探测 import _确认专属Wine前缀未被占用


def test_发现本轮专属_wine_前缀服务时拒绝启动(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "wt4.运行两实例并发能力探测.MT5后台进程._查询Wine服务",
        lambda 前缀: {123} if 前缀 == tmp_path / "甲" else set(),
    )
    with pytest.raises(RuntimeError, match="专属 Wine 前缀"):
        _确认专属Wine前缀未被占用(tmp_path / "甲", tmp_path / "乙")


def test_共享_wine_进程不阻塞未占用的专属前缀(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "wt4.运行两实例并发能力探测.MT5后台进程._查询Wine服务",
        lambda _: set(),
    )
    _确认专属Wine前缀未被占用(tmp_path / "甲", tmp_path / "乙")
