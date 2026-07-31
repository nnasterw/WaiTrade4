from __future__ import annotations

import pytest
from pathlib import Path

from wt4.mt5能力 import 测试实例配置, 校验实例隔离


def _实例(名称, 根目录):
    return 测试实例配置(
        名称, 根目录 / "terminal", 根目录 / "data", 根目录 / "prefix", 根目录 / "output",
        根目录 / "temp", 根目录 / "config", 根目录 / "cache",
    )


def test_两个实例必须没有共享可变目录(tmp_path) -> None:
    左 = _实例("甲", tmp_path / "a")
    右 = _实例("乙", tmp_path / "b")
    校验实例隔离([左, 右])


def test_共享缓存父目录时拒绝并发测试(tmp_path) -> None:
    左 = _实例("甲", tmp_path / "a")
    右 = _实例("乙", tmp_path / "b")
    左 = 测试实例配置(左.名称, 左.终端目录, tmp_path / "共享/data", 左.Wine前缀, 左.输出目录, 左.临时目录, 左.配置目录, 左.缓存目录)
    右 = 测试实例配置(右.名称, 右.终端目录, tmp_path / "共享/data", 右.Wine前缀, 右.输出目录, 右.临时目录, 右.配置目录, 右.缓存目录)
    with pytest.raises(ValueError, match="共享"):
        校验实例隔离([左, 右])

from wt4.mt5能力 import 能力证据, 判定调度方式


def test_目录嵌套同样不是隔离() -> None:
    甲 = _实例("甲", Path("/tmp/甲"))
    乙 = _实例("乙", Path("/tmp/乙"))
    甲 = 测试实例配置(甲.名称, 甲.终端目录, Path("/tmp/共享"), 甲.Wine前缀, 甲.输出目录, 甲.临时目录, 甲.配置目录, 甲.缓存目录)
    乙 = 测试实例配置(乙.名称, 乙.终端目录, Path("/tmp/共享/Tester"), 乙.Wine前缀, 乙.输出目录, 乙.临时目录, 乙.配置目录, 乙.缓存目录)
    with pytest.raises(ValueError, match="共享"):
        校验实例隔离([甲, 乙])


def test_所有能力证据通过才开放两并发() -> None:
    证据 = 能力证据(True, True, True, True, True, True)
    assert 判定调度方式(证据) == "两实例并行"


def test_缺少任意证据时保持串行() -> None:
    证据 = 能力证据(True, True, True, False, True, True)
    assert 判定调度方式(证据) == "中央单实例串行"


def test_空间不足时不允许准备隔离实例(monkeypatch, tmp_path) -> None:
    from wt4.mt5能力 import 评估隔离准备

    class _磁盘:
        free = 99

    monkeypatch.setattr("wt4.mt5能力.shutil.disk_usage", lambda _: _磁盘())
    评估 = 评估隔离准备(2, 100, tmp_path, 100)
    assert not 评估.可准备
    assert 评估.原因 == "磁盘空间不足，禁止创建隔离实例"


def test_盘点以完整wine前缀而非终端子目录评估空间(monkeypatch, tmp_path) -> None:
    from wt4.mt5能力 import 盘点本机MT5

    前缀 = tmp_path / "prefix"
    终端 = 前缀 / "drive_c/MT5"
    终端.mkdir(parents=True)
    (终端 / "terminal64.exe").write_bytes(b"terminal")
    (前缀 / "drive_c/windows").mkdir(parents=True)
    (前缀 / "drive_c/windows/system.bin").write_bytes(b"system-state")

    class _磁盘:
        free = 99

    monkeypatch.setattr("wt4.mt5能力.shutil.disk_usage", lambda _: _磁盘())
    盘点 = 盘点本机MT5([终端], 前缀, tmp_path, 100)

    assert 盘点.Wine前缀字节 == len(b"terminal") + len(b"system-state")
    assert not 盘点.双实例隔离可准备.可准备
