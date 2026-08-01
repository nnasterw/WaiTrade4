from __future__ import annotations

from pathlib import Path

from wt4.运行单实例能力探测 import (
    创建输入,
    生成三风险参数副本,
    生成参数文件名,
    核验SOCKS5代理前置,
    核验离线代理隔离前置,
)
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.运行单实例能力探测 import 默认Wine前缀, 默认Tester


def test_单实例入口默认使用仓库隔离_wine_前缀() -> None:
    assert "runtime/MT5并发能力/隔离实例/甲-wine前缀" in str(默认Wine前缀)
    assert 默认Tester == 默认Wine前缀 / "drive_c/Program Files/MetaTrader 5 Tester"


def test_仅将历史六点五风险参数降为三(tmp_path: Path) -> None:
    来源 = tmp_path / "历史.set"
    来源.write_text("参数A=1\nInpRiskPercent=6.5\n参数B=2\n", encoding="utf-8")
    目标 = tmp_path / "运行" / "risk3.set"

    哈希 = 生成三风险参数副本(来源, 目标)

    assert 目标.read_text(encoding="utf-8") == "参数A=1\nInpRiskPercent=3.0\n参数B=2\n"
    assert len(哈希) == 64


def test_拒绝非预期历史风险版本(tmp_path: Path) -> None:
    来源 = tmp_path / "历史.set"
    来源.write_text("InpRiskPercent=5.0\n", encoding="utf-8")

    try:
        生成三风险参数副本(来源, tmp_path / "risk3.set")
    except ValueError as 异常:
        assert "6.5%" in str(异常)
    else:
        raise AssertionError("应拒绝非预期的历史参数")


def test_运行参数副本拒绝覆盖并由实验输入派生唯一名称(tmp_path: Path) -> None:
    来源 = tmp_path / "历史.set"
    来源.write_text("InpRiskPercent=6.5\n", encoding="utf-8")
    名称 = 生成参数文件名("a" * 64, "2025.02.01", "2025.03.01", 600, "fromdate-v1")

    assert 名称 == "v11btc-r234-risk3-20250201-20250301-t600-fromdate-v1-aaaaaaaaaaaa.set"
    生成三风险参数副本(来源, tmp_path / 名称)
    try:
        生成三风险参数副本(来源, tmp_path / 名称)
    except ValueError as 异常:
        assert "拒绝覆盖" in str(异常)
    else:
        raise AssertionError("应拒绝覆盖既有运行参数副本")


def test_实验身份纳入运行超时这一单变量(tmp_path: Path) -> None:
    终端 = tmp_path / "Tester"
    ex5 = 终端 / "MQL5/Experts/WaiTrade2/WaiTrade_OB.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"ea")
    配置 = MT5短窗口探测配置(
        终端, r"WaiTrade2\WaiTrade_OB", "risk3.set", "BTCUSDm", "M1",
        "2026.05.12", "2026.05.13", 300, 2000, "277656700", "Exness-MT5Trial5",
    )

    assert 创建输入("a" * 64, 配置, 600).身份 != 创建输入("a" * 64, 配置, 900).身份
    assert 创建输入("a" * 64, 配置, 600, "fromdate-v1").身份 != 创建输入("a" * 64, 配置, 600, "parallel-v1").身份
    assert 创建输入("a" * 64, 配置, 600, 代理前置探测={"通过": True, "阶段": "CONNECT"}).身份 != 创建输入("a" * 64, 配置, 600).身份


def test_代理前置失败时拒绝启动而不允许直连(monkeypatch) -> None:
    monkeypatch.setattr(
        "wt4.运行单实例能力探测.通过SOCKS5探测端点",
        lambda *_: {"通过": False, "阶段": "CONNECT"},
    )

    try:
        核验SOCKS5代理前置()
    except ValueError as 异常:
        assert "拒绝启动 MT5" in str(异常)
    else:
        raise AssertionError("SOCKS5 前置失败时不得启动或降级直连")


def test_离线代理隔离只接受明确拒绝连接的非7897环回地址(monkeypatch) -> None:
    class _拒绝连接:
        def __enter__(self):
            raise ConnectionRefusedError("refused")

        def __exit__(self, *_):
            return None

    monkeypatch.setattr("wt4.运行单实例能力探测.socket.create_connection", lambda *_args, **_kwargs: _拒绝连接())

    assert 核验离线代理隔离前置("127.0.0.1:1") == {
        "模式": "离线代理隔离", "代理地址": "127.0.0.1:1", "代理监听": False,
    }

    for 地址 in ("127.0.0.1:7897", "203.0.113.7:1", "::1:1"):
        try:
            核验离线代理隔离前置(地址)
        except ValueError:
            pass
        else:
            raise AssertionError("离线隔离不得接受7897或非环回地址")


def test_离线代理隔离遇到非拒绝网络异常时拒绝启动(monkeypatch) -> None:
    def _网络异常(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr("wt4.运行单实例能力探测.socket.create_connection", _网络异常)

    try:
        核验离线代理隔离前置("127.0.0.1:1")
    except ValueError as 异常:
        assert "无法确认拒绝连接" in str(异常)
    else:
        raise AssertionError("非明确拒绝连接时不得启动离线隔离实验")
