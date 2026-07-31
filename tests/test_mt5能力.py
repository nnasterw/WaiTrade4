from __future__ import annotations

import pytest
from pathlib import Path

from wt4.mt5能力 import 测试实例配置, 校验实例隔离


def test_两个实例必须没有共享可变目录(tmp_path) -> None:
    左 = 测试实例配置("甲", tmp_path / "a/terminal", tmp_path / "a/data", tmp_path / "a/prefix", tmp_path / "a/output")
    右 = 测试实例配置("乙", tmp_path / "b/terminal", tmp_path / "b/data", tmp_path / "b/prefix", tmp_path / "b/output")
    校验实例隔离([左, 右])


def test_共享缓存父目录时拒绝并发测试(tmp_path) -> None:
    左 = 测试实例配置("甲", tmp_path / "a/terminal", tmp_path / "共享/data", tmp_path / "a/prefix", tmp_path / "a/output")
    右 = 测试实例配置("乙", tmp_path / "b/terminal", tmp_path / "共享/data", tmp_path / "b/prefix", tmp_path / "b/output")
    with pytest.raises(ValueError, match="共享"):
        校验实例隔离([左, 右])

from wt4.mt5能力 import 能力证据, 判定调度方式


def test_目录嵌套同样不是隔离() -> None:
    甲 = 测试实例配置("甲", Path("/tmp/甲/终端"), Path("/tmp/共享"), Path("/tmp/甲/前缀"), Path("/tmp/甲/输出"))
    乙 = 测试实例配置("乙", Path("/tmp/乙/终端"), Path("/tmp/共享/Tester"), Path("/tmp/乙/前缀"), Path("/tmp/乙/输出"))
    with pytest.raises(ValueError, match="共享"):
        校验实例隔离([甲, 乙])


def test_所有能力证据通过才开放两并发() -> None:
    证据 = 能力证据(True, True, True, True, True, True)
    assert 判定调度方式(证据) == "两实例并行"


def test_缺少任意证据时保持串行() -> None:
    证据 = 能力证据(True, True, True, False, True, True)
    assert 判定调度方式(证据) == "中央单实例串行"
