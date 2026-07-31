from __future__ import annotations

from subprocess import CompletedProcess

import pytest

from wt4.运行两实例并发能力探测 import _确认无既有MT5进程


def test_发现既有_mt5_进程时拒绝启动(monkeypatch) -> None:
    monkeypatch.setattr(
        "wt4.运行两实例并发能力探测.subprocess.run",
        lambda *_, **__: CompletedProcess([], 0, "123 terminal64.exe", ""),
    )
    with pytest.raises(RuntimeError, match="既有"):
        _确认无既有MT5进程()


def test_无既有_mt5_进程时允许启动(monkeypatch) -> None:
    monkeypatch.setattr(
        "wt4.运行两实例并发能力探测.subprocess.run",
        lambda *_, **__: CompletedProcess([], 1, "", ""),
    )
    _确认无既有MT5进程()
