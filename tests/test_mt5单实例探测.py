from __future__ import annotations

import json
from pathlib import Path

from wt4.experiment import 实验输入
from wt4.mt5单实例探测 import (
    单实例MT5探测执行器,
    解析MT5实际测试区间,
    解析MT5代理同步诊断,
    解析MT5生命周期,
    解析MT5连接端点,
    通过SOCKS5探测端点,
)
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.编排 import 实验状态


def _输入() -> 实验输入:
    return 实验输入("abc", "def", {}, "ticks", "cost", "contract", "5", 4, "2026.05.01", "2026.05.02", "能力探测")


def _配置与目录(tmp_path: Path) -> tuple[MT5短窗口探测配置, Path, Path, Path]:
    终端 = tmp_path / "MetaTrader 5 Tester"
    for 相对目录 in ("logs", "Tester/cache", "Tester/logs", "Tester/Agent-127.0.0.1-3000/logs", "reports", "MQL5/Profiles/Tester"):
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
    assert 结果.结果["MT5生命周期"]["交易服务器未同步标记"] == []
    assert 结果.结果["MT5代理同步诊断"]["结论"] == "未发现SOCKS5连接证据"


def test_报告缺失时仍返回代理和交易服务器同步诊断(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    日志 = 配置.终端目录 / "logs" / "本轮.log"
    日志.write_text(
        "Proxy\tconnecting through SOCKS5 proxy 127.0.0.1:7897\n"
        "Tester\tnot synchronized with trade server\n",
        encoding="utf-16le",
    )

    结果 = 单实例MT5探测执行器(配置, wine, 前缀, 5).执行(_输入(), 暂存)

    # 该测试直接调用前日志已存在，不能将旧日志误当本轮日志；由下一步的
    # 专门桩测试验证新增日志的诊断内容。
    assert 结果.状态 is 实验状态.执行无效
    assert "MT5生命周期" in 结果.结果


def test_生命周期只接受本轮完整成功标记() -> None:
    完整日志 = """
Tester automatical testing started
Tester last test passed with result "successfully finished" in 0:00:01
Terminal exit with code 0
"""
    assert 解析MT5生命周期(完整日志)["完整"] is True
    assert 解析MT5生命周期('Tester last test passed with result "successfully finished"')["完整"] is False
    assert 解析MT5生命周期("Terminal cannot load config Z:\\bad.ini")["失败标记"] == ["terminal cannot load config"]


def test_生命周期接受_mt5_制表符分隔日志并标记历史数据失败() -> None:
    日志 = """
NJ\t0\t17:35:25.249\tTester\tautomatical testing started
DD\t0\t17:35:25.360\tTester\tBTCUSDm: preliminary downloading of history ticks started
HG\t0\t17:37:19.519\tTester\tBTCUSDm: preliminary downloading of history ticks canceled
NL\t3\t17:37:19.520\tTester\tno history data, stop testing
OK\t0\t17:37:21.344\tTerminal\texit with code 0
"""
    生命周期 = 解析MT5生命周期(日志)

    assert 生命周期["已启动"] is True
    assert 生命周期["已退出"] is True
    assert 生命周期["完整"] is False
    assert 生命周期["历史数据不可用标记"] == [
        "preliminary downloading of history ticks canceled",
        "no history data, stop testing",
    ]


def test_生命周期标记代理连接后仍未完成交易服务器同步() -> None:
    日志 = """
Proxy\tconnecting through SOCKS5 proxy 127.0.0.1:7897
Tester\tnot synchronized with trade server
Tester\tterminal is not synchronized with the trade server before start automatical testing [1]
Tester\tautomatical testing started
"""

    生命周期 = 解析MT5生命周期(日志)

    assert 生命周期["代理连接标记"] == ["connecting through socks5 proxy"]
    assert 生命周期["交易服务器未同步标记"] == [
        "not synchronized with trade server",
        "terminal is not synchronized with the trade server before start automatical testing",
    ]
    assert 生命周期["完整"] is False


def test_代理同步诊断区分_socks5_connect_与_mt5_服务器未同步() -> None:
    日志 = """
DG\t0\t20:23:44.439\tProxy\tconnecting through SOCKS5 proxy 127.0.0.1:7897
MO\t2\t20:24:25.568\tTester\tnot synchronized with trade server
PE\t2\t20:24:25.810\tTester\tterminal is not synchronized with the trade server before start automatical testing [1]
"""

    诊断 = 解析MT5代理同步诊断(日志)

    assert 诊断 == {
        "结论": "SOCKS5已连接但MT5交易服务器未同步",
        "代理地址": "127.0.0.1:7897",
        "已授权服务器": [],
        "访问点": [],
        "代理至未同步秒数": 41.129,
    }


def test_代理同步诊断接受已授权且已同步的成功链路() -> None:
    日志 = """
Network\t'277656700': authorized on Exness-MT5Trial5 through Access Point #5 (ping: 84.17 ms, build 5830)
Network\t'277656700': terminal synchronized with Exness Technologies Ltd: 0 positions
"""

    assert 解析MT5代理同步诊断(日志) == {
        "结论": "MT5交易服务器已同步",
        "代理地址": None,
        "已授权服务器": ["Exness-MT5Trial5"],
        "访问点": [5],
        "代理至未同步秒数": None,
    }


def test_从_agent_日志提取实际测试区间而不是信任_ini() -> None:
    日志 = "Tester\tBTCUSDm,M1: testing of Experts\\WaiTrade2\\WaiTrade_OB.ex5 from 2025.02.01 00:00 to 2025.03.01 00:00 started"

    assert 解析MT5实际测试区间(日志) == ("2025.02.01", "2025.03.01")
    assert 解析MT5实际测试区间("Tester\tno test started") is None


def test_从本轮日志提取实际交易服务器端点() -> None:
    日志 = "Network connecting to server mt5.exness.com:443\nconnected with server 1.2.3.4:444"

    assert 解析MT5连接端点(日志) == ("1.2.3.4:444", "mt5.exness.com:443")


def test_socks5探测连接失败仍不会直连(monkeypatch) -> None:
    class _失败连接:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def settimeout(self, _):
            return None

        def sendall(self, _):
            return None

        def recv(self, _):
            raise OSError("代理拒绝")

    monkeypatch.setattr("wt4.mt5单实例探测.socket.create_connection", lambda *_args, **_kwargs: _失败连接())

    结果 = 通过SOCKS5探测端点("127.0.0.1:7897", "mt5.exness.com", 443)

    assert 结果["通过"] is False
    assert 结果["阶段"] == "网络异常"


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


def test_探测会封存并写入实际加载目录的显式参数文件(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    参数来源 = tmp_path / "WaiTrade_OB.set"
    参数来源.write_text("InpRiskPercent=3.0", encoding="utf-8")
    配置 = MT5短窗口探测配置(
        配置.终端目录, 配置.专家顾问, 配置.参数文件, 配置.品种, 配置.周期,
        配置.开始日, 配置.结束日, 配置.初始资金, 配置.杠杆, 配置.登录账号, 配置.服务器,
        参数文件路径=参数来源,
    )

    执行器 = 单实例MT5探测执行器(配置, wine, 前缀, 5)
    参数证据, 实际路径 = 执行器._准备参数输入(暂存)

    assert 参数证据 == ("mt5-input/WaiTrade_OB.set",)
    assert (暂存 / 参数证据[0]).read_text(encoding="utf-8") == "InpRiskPercent=3.0"
    assert 执行器._参数文件哈希(参数证据, 暂存)
    assert 实际路径 == 配置.终端目录 / "MQL5/Profiles/Tester/WaiTrade_OB.set"
    assert 实际路径.read_text(encoding="utf-8") == "InpRiskPercent=3.0"


def test_参数写入拒绝覆盖既有_tester_文件(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    参数来源 = tmp_path / "WaiTrade_OB.set"
    参数来源.write_text("InpRiskPercent=3.0", encoding="utf-8")
    (配置.终端目录 / "MQL5/Profiles/Tester/WaiTrade_OB.set").write_text("old", encoding="utf-8")
    配置 = MT5短窗口探测配置(
        配置.终端目录, 配置.专家顾问, "WaiTrade_OB.set", 配置.品种, 配置.周期,
        配置.开始日, 配置.结束日, 配置.初始资金, 配置.杠杆, 配置.登录账号, 配置.服务器,
        参数文件路径=参数来源,
    )

    try:
        单实例MT5探测执行器(配置, wine, 前缀, 5)._准备参数输入(暂存)
    except ValueError as 异常:
        assert "拒绝覆盖" in str(异常)
    else:
        raise AssertionError("应拒绝覆盖 Tester 参数文件")


def test_报告从_mt5终端根目录封存到本轮暂存目录(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    执行器 = 单实例MT5探测执行器(配置, wine, 前缀, 5)
    名称 = "wt4-abc123"
    来源 = 配置.终端目录 / f"{名称}.htm"
    来源.write_bytes(b"report")

    证据 = 执行器._收集MT5报告(名称, 暂存)

    assert 证据 == ("报告.html",)
    assert (暂存 / "报告.html").read_bytes() == b"report"
