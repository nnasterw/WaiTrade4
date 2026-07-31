from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from wt4.mt5探测 import MT5短窗口探测配置, 共享状态快照, 生成MT5探测配置


def _配置(tmp_path: Path) -> MT5短窗口探测配置:
    return MT5短窗口探测配置(
        终端目录=tmp_path / "MetaTrader 5 Tester",
        专家顾问=r"WaiTrade\WaiTrade_OB",
        参数文件="WaiTrade_OB.set",
        品种="BTCUSDm",
        周期="M5",
        开始日="2026.05.01",
        结束日="2026.05.02",
        初始资金=300,
        杠杆=2000,
        登录账号="277656700",
        服务器="Exness-MT5Trial5",
    )


def test_探测配置强制真实点和代理且报告写入本次暂存目录(tmp_path) -> None:
    配置 = _配置(tmp_path)
    配置.终端目录.mkdir()
    (配置.终端目录 / "terminal64.exe").write_bytes(b"")
    暂存目录 = tmp_path / "暂存"
    暂存目录.mkdir()

    路径 = 生成MT5探测配置(配置, 暂存目录)

    内容 = 路径.read_text(encoding="utf-8")
    assert "ProxyEnable=1" in 内容
    assert "Login=277656700" in 内容
    assert "Server=Exness-MT5Trial5" in 内容
    assert "ProxyAddress=127.0.0.1:7897" in 内容
    assert "Model=4" in 内容
    assert "Deposit=300" in 内容
    assert "Report=Z:\\" in 内容
    assert "报告.html" in 内容
    assert "ShutdownTerminal=1" in 内容


def test_探测配置拒绝缺失登录账号或服务器(tmp_path) -> None:
    配置 = _配置(tmp_path)
    配置.终端目录.mkdir()
    (配置.终端目录 / "terminal64.exe").write_bytes(b"")
    暂存目录 = tmp_path / "暂存"
    暂存目录.mkdir()

    for 字段 in ("登录账号", "服务器"):
        缺失登录配置 = replace(配置, **{字段: ""})
        try:
            生成MT5探测配置(缺失登录配置, 暂存目录)
        except ValueError as 异常:
            assert "登录账号和服务器" in str(异常)
        else:
            raise AssertionError("应拒绝缺失 MT5 登录信息")


def test_探测配置拒绝不存在的显式参数文件(tmp_path) -> None:
    配置 = replace(_配置(tmp_path), 参数文件路径=tmp_path / "不存在.set")
    配置.终端目录.mkdir()
    (配置.终端目录 / "terminal64.exe").write_bytes(b"")
    暂存目录 = tmp_path / "暂存"
    暂存目录.mkdir()

    try:
        生成MT5探测配置(配置, 暂存目录)
    except ValueError as 异常:
        assert "参数文件不存在" in str(异常)
    else:
        raise AssertionError("应拒绝不存在的显式参数文件")


def test_共享状态快照能识别新增修改和删除(tmp_path) -> None:
    受监控 = tmp_path / "Tester"
    受监控.mkdir()
    文件 = 受监控 / "cache.bin"
    文件.write_bytes(b"old")

    前 = 共享状态快照.创建([受监控])
    文件.write_bytes(b"new")
    (受监控 / "new.log").write_text("new", encoding="utf-8")
    后 = 共享状态快照.创建([受监控])

    差异 = 前.比较(后)
    assert 差异["新增"] == ["Tester/new.log"]
    assert 差异["修改"] == ["Tester/cache.bin"]
    assert 差异["删除"] == []


def test_共享状态快照拒绝不存在的目录(tmp_path) -> None:
    try:
        共享状态快照.创建([tmp_path / "不存在"])
    except ValueError as 异常:
        assert "不存在" in str(异常)
    else:
        raise AssertionError("应拒绝不存在的受监控目录")
