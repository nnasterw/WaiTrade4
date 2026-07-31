from __future__ import annotations

import json
from pathlib import Path

from wt4.experiment import 实验输入
from wt4.mt5单实例探测 import (
    单实例MT5探测执行器,
    解析MihomoTCP时间窗口候选,
    解析MT5实际测试区间,
    解析MT5代理同步诊断,
    解析MT5生命周期,
    核验MT5严格SOCKS5链路,
    解析MT5连接端点,
    批量通过SOCKS5探测端点,
    通过SOCKS5探测TLS端点,
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


def test_探测会将mihomo同窗口目标明确标为关联候选(tmp_path) -> None:
    配置, wine, 前缀, 暂存 = _配置与目录(tmp_path)
    Mihomo日志 = tmp_path / "mihomo.log"
    Mihomo日志.write_text(
        "[2026-07-31 20:58:22.000] INFO [TCP] 127.0.0.1:50001 --> mt5.exness.com:443\n",
        encoding="utf-8",
    )
    执行器 = 单实例MT5探测执行器(配置, wine, 前缀, 5, Mihomo日志)

    候选 = 执行器._收集Mihomo时间窗口候选("2026-07-31 20:58:22", "2026-07-31 21:00:52")

    assert 候选 == {
        "关联方式": "时间窗口关联候选",
        "开始时刻": "2026-07-31 20:58:22",
        "结束时刻": "2026-07-31 21:00:52",
        "目标总数": 1,
        "目标": [{"端点": "mt5.exness.com:443", "首次观测时刻": "2026-07-31 20:58:22.000", "次数": 1}],
    }


def test_生命周期只接受本轮完整成功标记() -> None:
    完整日志 = """
Tester automatical testing started
Tester last test passed with result "successfully finished" in 0:00:01
Terminal exit with code 0
"""
    assert 解析MT5生命周期(完整日志)["完整"] is True
    assert 解析MT5生命周期('Tester last test passed with result "successfully finished"')["完整"] is False
    assert 解析MT5生命周期("Terminal cannot load config Z:\\bad.ini")["失败标记"] == ["terminal cannot load config"]


def test_严格_socks5_链路必须匹配代理并包含授权和同步() -> None:
    完整日志 = """
DG\t0\t20:23:44.439\tProxy\tconnecting through SOCKS5 proxy 127.0.0.1:7897
MO\t0\t20:23:45.000\tNetwork\tauthorized on Exness-MT5Trial5 through Access Point #5
MO\t0\t20:23:46.000\tNetwork\tterminal synchronized with Exness Technologies Ltd
"""

    assert 核验MT5严格SOCKS5链路(完整日志, "127.0.0.1:7897") == []
    assert "不匹配" in 核验MT5严格SOCKS5链路(完整日志, "127.0.0.1:1")[0]
    缺少授权 = 核验MT5严格SOCKS5链路("DG\t0\t20:23:44.439\tProxy\tconnecting through SOCKS5 proxy 127.0.0.1:7897", "127.0.0.1:7897")
    assert any("授权" in 原因 for 原因 in 缺少授权)


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


def test_mihomo时间窗口只保留本轮环回来源的非环回目标() -> None:
    日志 = """
[2026-07-31 20:51:24.999] INFO [TCP] 127.0.0.1:50000 --> chatgpt.com:443
[2026-07-31 20:51:25.000] INFO [TCP] 127.0.0.1:50001 --> mt5.exness.com:443
[2026-07-31 20:51:26.500] INFO [TCP] 127.0.0.1:50002 --> 203.29.60.245:443
[2026-07-31 20:51:27.000] INFO [TCP] 127.0.0.1:50003 --> 203.29.60.245:443
[2026-07-31 20:51:28.000] INFO [TCP] 127.0.0.1:50004 --> localhost:3000
[2026-07-31 20:51:29.000] INFO [TCP] 10.0.0.2:50005 --> other.example:443
[2026-07-31 20:54:26.000] INFO [TCP] 127.0.0.1:50006 --> later.example:443
"""

    候选 = 解析MihomoTCP时间窗口候选(日志, "2026-07-31 20:51:25", "2026-07-31 20:54:25")

    assert 候选 == {
        "关联方式": "时间窗口关联候选",
        "开始时刻": "2026-07-31 20:51:25",
        "结束时刻": "2026-07-31 20:54:25",
        "目标总数": 2,
        "目标": [
            {"端点": "203.29.60.245:443", "首次观测时刻": "2026-07-31 20:51:26.500", "次数": 2},
            {"端点": "mt5.exness.com:443", "首次观测时刻": "2026-07-31 20:51:25.000", "次数": 1},
        ],
    }


def test_mihomo时间窗口要求完整且正向的边界() -> None:
    try:
        解析MihomoTCP时间窗口候选("", "2026-07-31 20:54:25", "2026-07-31 20:51:25")
    except ValueError as 异常:
        assert "结束时刻" in str(异常)
    else:
        raise AssertionError("应拒绝倒置的时间窗口")


def test_socks5探测连接失败仍不会直连(monkeypatch) -> None:
    class _失败连接:
        def close(self):
            return None

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


def test_socks5_tls探测通过代理隧道并携带指定_sni(monkeypatch) -> None:
    调用: dict[str, object] = {}

    class _TLS连接:
        version = lambda self: "TLSv1.3"
        cipher = lambda self: ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class _上下文:
        def wrap_socket(self, 连接, *, server_hostname):
            调用["连接"] = 连接
            调用["server_hostname"] = server_hostname
            return _TLS连接()

    class _隧道:
        def close(self):
            return None

    隧道 = _隧道()
    monkeypatch.setattr("wt4.mt5单实例探测._建立SOCKS5通道", lambda *_: 隧道)
    monkeypatch.setattr("wt4.mt5单实例探测.ssl.create_default_context", lambda: _上下文())

    结果 = 通过SOCKS5探测TLS端点("127.0.0.1:7897", "203.29.60.245", 443, "mt5.exness.com")

    assert 调用 == {"连接": 隧道, "server_hostname": "mt5.exness.com"}
    assert 结果 == {"通过": True, "阶段": "TLS握手", "TLS版本": "TLSv1.3", "密码套件": "TLS_AES_256_GCM_SHA384"}


def test_socks5_tls探测握手失败不会改走直连(monkeypatch) -> None:
    class _上下文:
        def wrap_socket(self, *_args, **_kwargs):
            raise OSError("TLS handshake rejected")

    class _隧道:
        def close(self):
            return None

    monkeypatch.setattr("wt4.mt5单实例探测._建立SOCKS5通道", lambda *_: _隧道())
    monkeypatch.setattr("wt4.mt5单实例探测.ssl.create_default_context", lambda: _上下文())

    结果 = 通过SOCKS5探测TLS端点("127.0.0.1:7897", "mt5.exness.com", 443)

    assert 结果["通过"] is False
    assert 结果["阶段"] == "TLS握手"


def test_批量_socks5_探测去重并逐端点保留结果(monkeypatch) -> None:
    调用: list[tuple[str, str, int, float]] = []

    def 探测(代理地址: str, 主机: str, 端口: int, 超时秒数: float):
        调用.append((代理地址, 主机, 端口, 超时秒数))
        return {"通过": 主机 == "mt5.exness.com", "阶段": "CONNECT"}

    monkeypatch.setattr("wt4.mt5单实例探测.通过SOCKS5探测端点", 探测)

    结果 = 批量通过SOCKS5探测端点(
        "127.0.0.1:7897",
        ("trade.example.com:444", "mt5.exness.com:443", "mt5.exness.com:443"),
        3,
    )

    assert 调用 == [
        ("127.0.0.1:7897", "mt5.exness.com", 443, 3),
        ("127.0.0.1:7897", "trade.example.com", 444, 3),
    ]
    assert 结果 == {
        "端点总数": 2,
        "全部通过": False,
        "结果": [
            {"端点": "mt5.exness.com:443", "通过": True, "阶段": "CONNECT"},
            {"端点": "trade.example.com:444", "通过": False, "阶段": "CONNECT"},
        ],
    }


def test_批量_socks5_探测拒绝环回端点(monkeypatch) -> None:
    monkeypatch.setattr("wt4.mt5单实例探测.通过SOCKS5探测端点", lambda *_: (_ for _ in ()).throw(AssertionError()))

    try:
        批量通过SOCKS5探测端点("127.0.0.1:7897", ("127.0.0.1:3005",))
    except ValueError as 异常:
        assert "环回" in str(异常)
    else:
        raise AssertionError("应拒绝 Tester Agent 环回端点")


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
