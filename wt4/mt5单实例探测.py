from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import re
import socket
import struct
from typing import Mapping

from wt4.experiment import 实验输入
from wt4.mt5执行 import MT5回测配置, 隔离MT5执行器
from wt4.mt5探测 import MT5短窗口探测配置, 共享状态快照, 生成MT5探测配置
from wt4.编排 import 执行结果


def 解析MT5连接端点(日志证据: str) -> tuple[str, ...]:
    """从本轮 MT5 日志提取服务器连接端点，供代理前置核验。"""
    模式 = (
        r"(?:connected|connecting|connection)\s+(?:to|with)\s+(?:server\s+)?([A-Za-z0-9.-]+):(\d{1,5})",
        r"server\s+([A-Za-z0-9.-]+):(\d{1,5})",
    )
    端点: set[str] = set()
    for 表达式 in 模式:
        for 主机, 端口文本 in re.findall(表达式, 日志证据, flags=re.IGNORECASE):
            端口 = int(端口文本)
            if 0 < 端口 < 65536:
                端点.add(f"{主机.lower()}:{端口}")
    return tuple(sorted(端点))


def 通过SOCKS5探测端点(代理地址: str, 主机: str, 端口: int, 超时秒数: float = 5) -> dict[str, object]:
    """仅经 SOCKS5 建立到指定端点的 TCP CONNECT；不允许直连降级。"""
    if 超时秒数 <= 0 or not 0 < 端口 < 65536:
        raise ValueError("SOCKS5 探测参数无效")
    try:
        代理主机, 代理端口文本 = 代理地址.rsplit(":", 1)
        代理端口 = int(代理端口文本)
    except (ValueError, AttributeError) as 异常:
        raise ValueError(f"SOCKS5 代理地址无效: {代理地址}") from 异常
    if not 代理主机 or not 0 < 代理端口 < 65536:
        raise ValueError(f"SOCKS5 代理地址无效: {代理地址}")
    try:
        with socket.create_connection((代理主机, 代理端口), timeout=超时秒数) as 连接:
            连接.settimeout(超时秒数)
            连接.sendall(b"\x05\x01\x00")
            协商 = _接收完整(连接, 2)
            if 协商 != b"\x05\x00":
                return {"通过": False, "阶段": "认证协商", "响应": 协商.hex()}
            主机字节 = 主机.encode("idna")
            if not 1 <= len(主机字节) <= 255:
                raise ValueError("SOCKS5 目标主机无效")
            连接.sendall(b"\x05\x01\x00\x03" + bytes([len(主机字节)]) + 主机字节 + struct.pack(">H", 端口))
            头 = _接收完整(连接, 4)
            if len(头) != 4 or 头[0] != 5 or 头[1] != 0:
                return {"通过": False, "阶段": "CONNECT", "响应": 头.hex()}
            地址长度 = {1: 4, 4: 16}.get(头[3])
            if 头[3] == 3:
                地址长度 = _接收完整(连接, 1)[0]
            if 地址长度 is None:
                return {"通过": False, "阶段": "CONNECT地址类型", "响应": 头.hex()}
            _接收完整(连接, 地址长度 + 2)
            return {"通过": True, "阶段": "CONNECT"}
    except OSError as 异常:
        return {"通过": False, "阶段": "网络异常", "原因": str(异常)}


def 批量通过SOCKS5探测端点(
    代理地址: str,
    端点列表: tuple[str, ...],
    超时秒数: float = 5,
    最大端点数: int = 16,
) -> dict[str, object]:
    """逐个经 SOCKS5 探测日志已明确记录的非环回端点。

    每个探测复用单端点 SOCKS5 实现，绝不直连降级。Tester Agent 的
    环回端点不能代表 MT5 交易服务器，必须拒绝，避免虚假网络结论。
    """
    if 最大端点数 < 1:
        raise ValueError("SOCKS5 批量探测最大端点数必须为正")
    去重端点 = tuple(sorted(set(端点列表)))
    if len(去重端点) > 最大端点数:
        raise ValueError(f"SOCKS5 批量探测端点过多: {len(去重端点)} > {最大端点数}")

    结果: list[dict[str, object]] = []
    for 端点 in 去重端点:
        try:
            主机, 端口文本 = 端点.rsplit(":", 1)
            端口 = int(端口文本)
        except (ValueError, AttributeError) as 异常:
            raise ValueError(f"SOCKS5 探测端点格式无效: {端点}") from 异常
        if not 主机 or 主机.startswith("127.") or 主机 == "localhost":
            raise ValueError(f"SOCKS5 探测拒绝环回端点: {端点}")
        探测 = 通过SOCKS5探测端点(代理地址, 主机, 端口, 超时秒数)
        结果.append({"端点": 端点, **探测})
    return {
        "端点总数": len(结果),
        "全部通过": bool(结果) and all(项["通过"] is True for 项 in 结果),
        "结果": 结果,
    }


def _接收完整(连接: socket.socket, 长度: int) -> bytes:
    内容 = bytearray()
    while len(内容) < 长度:
        片段 = 连接.recv(长度 - len(内容))
        if not 片段:
            raise OSError("SOCKS5 响应提前结束")
        内容.extend(片段)
    return bytes(内容)


def 解析MT5代理同步诊断(日志证据: str) -> dict[str, object]:
    """从本轮日志区分 SOCKS5 已接入与 MT5 交易服务器是否真正同步。

    SOCKS5 CONNECT 仅证明代理能建立一个 TCP 隧道，不能替代 MT5 完成
    授权、访问点选择与终端同步。该诊断只提取日志已经明确写出的事实，
    不根据代理地址推测远端真实端点。
    """
    代理匹配 = list(re.finditer(r"(?im)^.*?\b(\d{2}:\d{2}:\d{2}\.\d{3})\tProxy\tconnecting through SOCKS5 proxy\s+([^\s]+)", 日志证据))
    未同步匹配 = list(re.finditer(r"(?im)^.*?\b(\d{2}:\d{2}:\d{2}\.\d{3})\tTester\tnot synchronized with trade server", 日志证据))
    授权匹配 = list(re.finditer(r"(?im)authorized on\s+([^\s]+)\s+through Access Point #(\d+)", 日志证据))
    已同步 = bool(re.search(r"(?im)terminal synchronized with", 日志证据))

    代理地址 = 代理匹配[-1].group(2) if 代理匹配 else None
    已授权服务器 = sorted({匹配.group(1) for 匹配 in 授权匹配})
    访问点 = sorted({int(匹配.group(2)) for 匹配 in 授权匹配})
    延迟: float | None = None
    if 代理匹配 and 未同步匹配:
        代理时间 = _解析MT5日志时刻(代理匹配[-1].group(1))
        首个未同步时间 = _解析MT5日志时刻(未同步匹配[0].group(1))
        if 首个未同步时间 >= 代理时间:
            延迟 = round(首个未同步时间 - 代理时间, 3)

    if 已同步:
        结论 = "MT5交易服务器已同步"
    elif 代理地址 and 未同步匹配:
        结论 = "SOCKS5已连接但MT5交易服务器未同步"
    elif 代理地址:
        结论 = "SOCKS5已连接，等待MT5同步证据"
    else:
        结论 = "未发现SOCKS5连接证据"
    return {
        "结论": 结论,
        "代理地址": 代理地址,
        "已授权服务器": 已授权服务器,
        "访问点": 访问点,
        "代理至未同步秒数": 延迟,
    }


def _解析MT5日志时刻(时刻: str) -> float:
    时, 分, 秒 = 时刻.split(":")
    return int(时) * 3600 + int(分) * 60 + float(秒)


def 解析MT5生命周期(日志证据: str) -> dict[str, object]:
    """只接受本轮新增日志中的完整 Tester 生命周期，避免旧日志误判成功。"""
    小写日志 = 日志证据.lower()
    失败标记 = tuple(
        标记
        for 标记 in (
            "tester didn't start",
            "terminal cannot load config",
            "tester automatical testing failed",
        )
        if 标记 in 小写日志
    )
    已启动 = bool(re.search(r"tester\s+automatical testing started", 小写日志))
    已成功 = bool(re.search(r'tester\s+last test passed with result "successfully finished"', 小写日志))
    已退出 = bool(re.search(r"terminal\s+exit with code 0", 小写日志))
    历史数据不可用 = tuple(
        标记
        for 标记 in (
            "history check timeout",
            "preliminary downloading of history ticks canceled",
            "no history data, stop testing",
        )
        if 标记 in 小写日志
    )
    代理连接 = tuple(
        标记
        for 标记 in (
            "connecting through socks5 proxy",
        )
        if 标记 in 小写日志
    )
    交易服务器未同步 = tuple(
        标记
        for 标记 in (
            "not synchronized with trade server",
            "terminal is not synchronized with the trade server before start automatical testing",
        )
        if 标记 in 小写日志
    )
    return {
        "已启动": 已启动,
        "已成功": 已成功,
        "已退出": 已退出,
        "失败标记": list(失败标记),
        "历史数据不可用标记": list(历史数据不可用),
        "代理连接标记": list(代理连接),
        "交易服务器未同步标记": list(交易服务器未同步),
        "完整": 已启动 and 已成功 and 已退出 and not 失败标记 and not 交易服务器未同步,
    }


def 解析MT5实际测试区间(日志证据: str) -> tuple[str, str] | None:
    """从本轮 Agent 日志提取 Tester 实际执行区间，不能只信任 INI。"""
    匹配 = re.search(
        r"testing .*? from (\d{4}\.\d{2}\.\d{2}) 00:00 to (\d{4}\.\d{2}\.\d{2}) 00:00 started",
        日志证据.lower(),
    )
    return (匹配.group(1), 匹配.group(2)) if 匹配 else None


class 单实例MT5探测执行器:
    """对专用 Tester 做一次短窗口、串行且可审计的能力探测。"""

    def __init__(
        self,
        探测配置: MT5短窗口探测配置,
        Wine命令: Path,
        Wine前缀: Path,
        超时秒数: int,
    ) -> None:
        if not Wine命令.is_file():
            raise ValueError(f"Wine 命令不存在: {Wine命令}")
        if not Wine前缀.is_dir():
            raise ValueError(f"Wine 前缀不存在: {Wine前缀}")
        if 超时秒数 <= 0:
            raise ValueError("探测超时必须为正")
        self.探测配置 = 探测配置
        self.Wine命令 = Wine命令
        self.Wine前缀 = Wine前缀
        self.超时秒数 = 超时秒数

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        运行配置 = 生成MT5探测配置(self.探测配置, 暂存目录)
        报告名称 = self._配置报告名称(运行配置)
        受监控目录 = self._受监控目录()
        运行前 = 共享状态快照.创建(受监控目录)
        运行前日志 = self._日志字节快照()
        (暂存目录 / "共享状态-运行前.json").write_text(
            json.dumps(运行前.文件, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
        参数证据, 实际参数路径 = self._准备参数输入(暂存目录)

        命令 = (
            str(self.Wine命令),
            r"C:\Program Files\MetaTrader 5 Tester\terminal64.exe",
            f"/config:{self._mac路径转WineZ盘(运行配置)}",
        )
        结果 = 隔离MT5执行器(
            MT5回测配置(
                命令=命令,
                超时秒数=self.超时秒数,
                # MT5 将 Report 写到共享终端根目录；待进程退出后再按唯一
                # 报告名收集进本轮暂存目录，因此此处只能核验同步执行日志。
                预期工件=("执行日志.txt",),
                环境变量={"WINEPREFIX": str(self.Wine前缀)},
            )
        ).执行(输入, 暂存目录)
        报告证据 = self._收集MT5报告(报告名称, 暂存目录)

        运行后 = 共享状态快照.创建(受监控目录)
        差异 = 运行前.比较(运行后)
        (暂存目录 / "共享状态差异.json").write_text(
            json.dumps(差异, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
        日志证据 = self._保留本次日志证据(暂存目录, 运行前日志)
        日志文本 = (暂存目录 / 日志证据).read_text(encoding="utf-8")
        生命周期 = 解析MT5生命周期(日志文本)
        代理同步诊断 = 解析MT5代理同步诊断(日志文本)
        实际测试区间 = 解析MT5实际测试区间(日志文本)
        工件 = dict(结果.工件)
        结果数据 = {
            **结果.结果,
            "共享状态差异": 差异,
            "MT5生命周期": 生命周期,
            "MT5代理同步诊断": 代理同步诊断,
            "MT5实际测试区间": 实际测试区间,
            "参数输入证据哈希": self._参数文件哈希(参数证据, 暂存目录),
            "MT5实际参数路径": str(实际参数路径) if 实际参数路径 else None,
        }
        if not 报告证据:
            return 执行结果(
                结果.状态.执行无效,
                {},
                {**结果数据, "原因": "缺少 MT5 工件", "缺失": ["报告.html"]},
            )
        for 名称 in ("mt5-探测.ini", "共享状态-运行前.json", "共享状态差异.json", 日志证据, *参数证据, *报告证据):
            路径 = 暂存目录 / 名称
            工件[名称] = 隔离MT5执行器._哈希(路径)
        if 生命周期["历史数据不可用标记"]:
            return 执行结果(
                结果.状态.数据无效,
                {},
                {**结果数据, "原因": "MT5 历史数据不可用"},
            )
        期望测试区间 = (self.探测配置.开始日, self.探测配置.结束日)
        if 实际测试区间 != 期望测试区间:
            return 执行结果(
                结果.状态.执行无效,
                {},
                {
                    **结果数据,
                    "原因": "MT5 日期参数未按声明区间生效",
                    "期望测试区间": 期望测试区间,
                },
            )
        if 结果.状态.value == "已归档" and not 生命周期["完整"]:
            return 执行结果(
                结果.状态.执行无效,
                {},
                {**结果数据, "原因": "MT5 生命周期证据不完整"},
            )
        return 执行结果(结果.状态, 工件, 结果数据)

    @staticmethod
    def _配置报告名称(运行配置: Path) -> str:
        for 行 in 运行配置.read_text(encoding="utf-8").splitlines():
            if 行.startswith("Report="):
                名称 = 行.removeprefix("Report=")
                if re.fullmatch(r"wt4-[A-Za-z0-9_-]+", 名称):
                    return 名称
        raise ValueError("MT5 探测配置缺少安全的 Report 名称")

    def _收集MT5报告(self, 报告名称: str, 暂存目录: Path) -> tuple[str, ...]:
        """将 MT5 实际输出目录中的唯一 HTML 报告封存到本轮暂存目录。"""
        候选 = [
            路径 for 路径 in self.探测配置.终端目录.glob(f"{报告名称}.*")
            if 路径.is_file() and not 路径.is_symlink() and 路径.suffix.lower() in {".htm", ".html"}
        ]
        if len(候选) > 1:
            raise ValueError(f"MT5 输出了多个同名报告，拒绝选择: {候选}")
        if not 候选:
            return ()
        目标 = 暂存目录 / "报告.html"
        if 目标.exists():
            raise ValueError("报告封存目标已存在")
        目标.write_bytes(候选[0].read_bytes())
        return (目标.name,)

    def _准备参数输入(self, 暂存目录: Path) -> tuple[tuple[str, ...], Path | None]:
        """封存并以唯一名称写入 Tester 的实际 ExpertParameters 查找目录。

        MT5 的 ``ExpertParameters`` 只接受文件名，会从 Tester 的
        ``MQL5/Profiles/Tester`` 读取。因此仅在暂存目录复制参数并不能
        证明实际加载；这里拒绝覆盖既有文件，并把目标目录纳入状态快照。
        """
        来源 = self.探测配置.参数文件路径
        if 来源 is None:
            return (), None
        if Path(self.探测配置.参数文件).name != self.探测配置.参数文件:
            raise ValueError("ExpertParameters 必须是无目录的唯一文件名")
        if 来源.name != self.探测配置.参数文件:
            raise ValueError("声明参数文件名必须与 ExpertParameters 完全一致")
        目标目录 = 暂存目录 / "mt5-input"
        目标目录.mkdir()
        目标 = 目标目录 / 来源.name
        目标.write_bytes(来源.read_bytes())

        实际目录 = self.探测配置.终端目录 / "MQL5/Profiles/Tester"
        实际目录.mkdir(parents=True, exist_ok=True)
        实际路径 = 实际目录 / 来源.name
        if 实际路径.exists():
            raise ValueError(f"拒绝覆盖 Tester 既有参数文件: {实际路径}")
        实际路径.write_bytes(来源.read_bytes())
        return (目标.relative_to(暂存目录).as_posix(),), 实际路径

    @staticmethod
    def _参数文件哈希(参数证据: tuple[str, ...], 暂存目录: Path) -> str | None:
        if not 参数证据:
            return None
        return sha256((暂存目录 / 参数证据[0]).read_bytes()).hexdigest()

    def _受监控目录(self) -> list[Path]:
        根目录 = self.探测配置.终端目录
        return [
            根目录 / "logs",
            根目录 / "Tester" / "cache",
            根目录 / "Tester" / "logs",
            根目录 / "Tester" / "Agent-127.0.0.1-3000" / "logs",
            根目录 / "reports",
            根目录 / "MQL5" / "Profiles" / "Tester",
        ]

    @staticmethod
    def _mac路径转WineZ盘(路径: Path) -> str:
        return "Z:\\" + str(路径.resolve()).lstrip("/").replace("/", "\\")

    def _日志字节快照(self) -> dict[str, bytes]:
        """按受监控根目录保留日志字节，供执行后仅提取本轮新增片段。"""
        日志: dict[str, bytes] = {}
        for 根目录 in self._受监控目录():
            if "logs" not in 根目录.parts:
                continue
            根标识 = 根目录.relative_to(self.探测配置.终端目录).as_posix()
            for 路径 in sorted(根目录.rglob("*.log")):
                if 路径.is_file() and not 路径.is_symlink():
                    日志[f"{根标识}/{路径.relative_to(根目录).as_posix()}"] = 路径.read_bytes()
        return 日志

    def _保留本次日志证据(self, 暂存目录: Path, 运行前日志: Mapping[str, bytes]) -> str:
        """封存主/Tester/Agent 日志的新增字节；旧日志不能充当本轮成功证据。"""
        运行后日志 = self._日志字节快照()
        证据路径 = 暂存目录 / "MT5日志证据.txt"
        内容: list[str] = []
        for 标识, 当前字节 in sorted(运行后日志.items()):
            原字节 = 运行前日志.get(标识)
            if 原字节 == 当前字节:
                continue
            if 原字节 is None:
                变化类型, 新增字节 = "新增文件", 当前字节
            elif 当前字节.startswith(原字节):
                变化类型, 新增字节 = "追加片段", 当前字节[len(原字节):]
            else:
                变化类型, 新增字节 = "轮转或重写后的完整文件", 当前字节
            内容.append(f"--- {标识} ({变化类型}) ---\n")
            内容.append(self._解码MT5日志(新增字节))
            if not 内容[-1].endswith("\n"):
                内容.append("\n")
        证据路径.write_text("".join(内容), encoding="utf-8")
        return 证据路径.name

    @staticmethod
    def _解码MT5日志(内容: bytes) -> str:
        try:
            return 内容.decode("utf-16le")
        except UnicodeDecodeError:
            return 内容.decode("utf-8", errors="replace")
