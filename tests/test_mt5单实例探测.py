from __future__ import annotations

import json
from pathlib import Path

from wt4.experiment import 实验输入
from wt4.mt5单实例探测 import 单实例MT5探测执行器, 解析MT5生命周期
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.编排 import 实验状态


def _输入() -> 实验输入:
    return 实验输入("abc", "def", {}, "ticks", "cost", "contract", "5", 4, "2026.05.01", "2026.05.02", "能力探测")


def _配置与目录(tmp_path: Path) -> tuple[MT5短窗口探测配置, Path, Path, Path]:
    终端 = tmp_path / "MetaTrader 5 Tester"
    for 相对目录 in ("logs", "Tester/cache", "Tester/logs", "Tester/Agent-127.0.0.1-3000/logs", "reports"):
        (终端 / 相对目录).mkdir(parents=True)
    (终端 / "terminal64.exe").write_bytes(b"")
    wine = tmp_path / "wine"
    wine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wine.chmod(0o755)
    前缀 = tmp_path / "prefix"
    前缀.mkdir()
    暂存 = tmp_path / "暂存"
    暂存.mkdir()
    配置 = MT5短窗口探测配置(
        终端, r"WaiTrade\WaiTrade_OB", "WaiTrade_OB.set", "BTCUSDm", "M5",
        "2026.05.01", "2026.05.02", 300, 2000, "277656700", "Exness-MT5Trial5",
    )
    return 配置, wine, 前缀, 暂存


def test_探测会保留共享状态前后证据即使报告缺失(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)

    结果 = 单实例MT5探测执行器(配置, wine, 前缀, 5).执行(_输入(), 暂存)

    assert 结果.状态 is 实验状态.执行无效
    assert (暂存 / "mt5-探测.ini").is_file()
    assert (暂存 / "共享状态-运行前.json").is_file()
    assert (暂存 / "共享状态差异.json").is_file()
    assert (暂存 / "MT5日志证据.txt").read_text(encoding="utf-8") == ""
    assert json.loads((暂存 / "共享状态差异.json").read_text(encoding="utf-8")) == {"删除": [], "修改": [], "新增": []}


def test_生命周期只接受本轮完整成功标记() -> None:
    完整日志 = """
Tester automatical testing started
Tester last test passed with result "successfully finished" in 0:00:01
Terminal exit with code 0
"""
    assert 解析MT5生命周期(完整日志)["完整"] is True
    assert 解析MT5生命周期('Tester last test passed with result "successfully finished"')["完整"] is False
    assert 解析MT5生命周期("Terminal cannot load config Z:\\bad.ini")["失败标记"] == ["terminal cannot load config"]


def test_仅封存本轮新增日志并能识别完整生命周期(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    执行器 = 单实例MT5探测执行器(配置, wine, 前缀, 5)
    运行前日志 = 执行器._日志字节快照()
    (配置.终端目录 / "logs" / "本轮.log").write_text(
        'Tester automatical testing started\nTester last test passed with result "successfully finished"\nTerminal exit with code 0\n',
        encoding="utf-16le",
    )

    名称 = 执行器._保留本次日志证据(暂存, 运行前日志)
    证据 = (暂存 / 名称).read_text(encoding="utf-8")

    assert "本轮.log" in 证据
    assert 解析MT5生命周期(证据)["完整"] is True


def test_旧成功日志不构成本轮成功证据(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    (配置.终端目录 / "logs" / "旧.log").write_text(
        'Tester automatical testing started\nTester last test passed with result "successfully finished"\nTerminal exit with code 0\n',
        encoding="utf-16le",
    )
    执行器 = 单实例MT5探测执行器(配置, wine, 前缀, 5)
    运行前日志 = 执行器._日志字节快照()

    名称 = 执行器._保留本次日志证据(暂存, 运行前日志)
    证据 = (暂存 / 名称).read_text(encoding="utf-8")

    assert 证据 == ""
    assert 解析MT5生命周期(证据)["完整"] is False


def test_探测会封存显式参数文件及其哈希(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    参数来源 = tmp_path / "来源.set"
    参数来源.write_text("InpRiskPercent=3.0", encoding="utf-8")
    配置 = MT5短窗口探测配置(
        配置.终端目录, 配置.专家顾问, 配置.参数文件, 配置.品种, 配置.周期,
        配置.开始日, 配置.结束日, 配置.初始资金, 配置.杠杆, 配置.登录账号, 配置.服务器,
        参数文件路径=参数来源,
    )

    执行器 = 单实例MT5探测执行器(配置, wine, 前缀, 5)
    参数证据 = 执行器._复制参数文件(暂存)

    assert 参数证据 == ("mt5-input/来源.set",)
    assert (暂存 / 参数证据[0]).read_text(encoding="utf-8") == "InpRiskPercent=3.0"
    assert 执行器._参数文件哈希(参数证据, 暂存)
