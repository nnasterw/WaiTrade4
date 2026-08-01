from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import tempfile


@dataclass(frozen=True)
class MT5短窗口探测配置:
    """仅用于验证本机 Tester 的运行边界，不构成候选策略验收输入。"""

    终端目录: Path
    专家顾问: str
    参数文件: str
    品种: str
    周期: str
    开始日: str
    结束日: str
    初始资金: int
    杠杆: int
    登录账号: str
    服务器: str
    代理地址: str = "127.0.0.1:7897"
    # 本机 MT5 日志已实锤 ProxyType=1 才会显示 SOCKS5；0 显示 NONE，
    # 因而禁止将通用枚举猜测或历史直连成功误作 SOCKS5 证据。
    代理类型: int = 1
    参数文件路径: Path | None = None


def 生成MT5探测配置(配置: MT5短窗口探测配置, 暂存目录: Path) -> Path:
    """生成一次性 INI；报告只允许落在实验暂存目录。"""
    if not 暂存目录.is_dir():
        raise ValueError(f"实验暂存目录不存在: {暂存目录}")
    if not (配置.终端目录 / "terminal64.exe").is_file():
        raise ValueError(f"MT5 终端不存在: {配置.终端目录}")
    if not 配置.代理地址:
        raise ValueError("MT5 探测必须显式指定代理")
    if 配置.代理类型 != 1:
        raise ValueError("MT5 探测仅允许 SOCKS5 代理，禁止 NONE/HTTP 直连回退")
    if not 配置.登录账号 or not 配置.服务器:
        raise ValueError("MT5 探测必须显式指定登录账号和服务器")
    if 配置.初始资金 != 300:
        raise ValueError("首期 MT5 探测初始资金必须为 300 美元")
    if 配置.参数文件路径 is not None and not 配置.参数文件路径.is_file():
        raise ValueError(f"MT5 探测参数文件不存在: {配置.参数文件路径}")

    # 不能只用暂存目录末级名称：并发实验中的「甲」会在串行和并行轮次
    # 重名，导致同一 Tester 根目录复用报告输出。
    报告名称 = "wt4-" + sha256(str(暂存目录.resolve()).encode("utf-8")).hexdigest()[:16]
    内容 = f"""; wt4 单实例能力探测。不可作为策略验收结论。
[Common]
Login={配置.登录账号}
Server={配置.服务器}
ProxyEnable=1
ProxyType={配置.代理类型}
ProxyAddress={配置.代理地址}

[Tester]
Expert={配置.专家顾问}
ExpertParameters={配置.参数文件}
Symbol={配置.品种}
Period={配置.周期}
Model=4
Optimization=0
FromDate={配置.开始日}
ToDate={配置.结束日}
Deposit={配置.初始资金}
Currency=USD
Leverage={配置.杠杆}
ExecutionMode=0
ShutdownTerminal=1
Report={报告名称}
"""
    路径 = 暂存目录 / "mt5-探测.ini"
    路径.write_text(内容, encoding="utf-8")
    return 路径


def 写入MT5持久SOCKS5配置(配置: MT5短窗口探测配置) -> Path:
    """把代理写入 Tester 实际读取的 ``config/common.ini``。

    macOS/Wine 版 Tester 会保留自己的 UTF-16 ``common.ini``；单次
    ``/config:`` 文件中的 ``[Common]`` 不能可靠覆盖它。必须在启动前
    同时写入此持久配置，且只允许 SOCKS5。
    """
    路径 = 配置.终端目录 / "config" / "common.ini"
    return _写入单个MT5持久SOCKS5配置(配置, 路径)


def 定位MT5持久代理配置组(终端目录: Path) -> tuple[Path, ...]:
    """定位本次 Tester 会话可能读取的全部 ``common.ini``。

    Wine 下 ``Program Files/MetaTrader 5 Tester/config`` 和当前用户的
    ``AppData/Roaming/MetaQuotes/Terminal/<实例>/config`` 会同时存在。
    仅写前者会留下 Roaming 配置中的 ``ProxyEnable=0``，使一次受控失败
    无法区分为 SOCKS5 链路问题还是配置覆盖。因此两者必须一致；不修改
    同一 Wine 前缀内其他安装目录的普通 MT5 配置。
    """
    根配置 = 终端目录 / "config" / "common.ini"
    if not 根配置.is_file():
        raise ValueError(f"MT5 持久代理配置不存在: {根配置}")

    try:
        前缀 = 终端目录.parents[1]
    except IndexError as 异常:
        raise ValueError(f"无法从 Tester 目录定位 Wine 前缀: {终端目录}") from 异常
    # 单元测试或非 Wine 调用方只具有 Tester 根配置时，不能猜测其
    # Roaming 目录；此时仍安全地只写已经显式给出的根配置。
    if 前缀.name != "drive_c":
        return (根配置,)
    Wine前缀 = 前缀.parent
    Roaming根目录 = Wine前缀 / "drive_c/users"
    Roaming配置 = sorted(
        路径
        for 路径 in Roaming根目录.glob(
            "*/AppData/Roaming/MetaQuotes/Terminal/*/config/common.ini"
        )
        if 路径.is_file() and not 路径.is_symlink()
    )
    return tuple([根配置, *Roaming配置])


def 写入MT5持久SOCKS5配置组(配置: MT5短窗口探测配置) -> tuple[Path, ...]:
    """将 Tester 根目录及 Roaming 会话配置统一写为 SOCKS5。"""
    路径组 = 定位MT5持久代理配置组(配置.终端目录)
    已写入: list[Path] = []
    for 路径 in 路径组:
        已写入.append(_写入单个MT5持久SOCKS5配置(配置, 路径))
    return tuple(已写入)


def _写入单个MT5持久SOCKS5配置(配置: MT5短窗口探测配置, 路径: Path) -> Path:
    """原子改写一个已经定位的 ``common.ini``。"""
    if 配置.代理类型 != 1 or not 配置.代理地址:
        raise ValueError("MT5 持久代理配置仅允许显式 SOCKS5 地址")
    if not 路径.is_file():
        raise ValueError(f"MT5 持久代理配置不存在: {路径}")
    原始内容 = 路径.read_bytes()
    try:
        内容 = 原始内容.decode("utf-16")
        编码 = "utf-16"
    except UnicodeDecodeError as 异常:
        raise ValueError(f"MT5 持久代理配置不是 UTF-16: {路径}") from 异常

    for 键, 值 in (("ProxyEnable", "1"), ("ProxyType", "1"), ("ProxyAddress", 配置.代理地址)):
        内容, 替换数 = re.subn(rf"(?m)^{键}=.*$", f"{键}={值}", 内容)
        if 替换数 != 1:
            raise ValueError(f"MT5 持久代理配置字段异常: {键}={替换数}")

    临时文件 = None
    try:
        with tempfile.NamedTemporaryFile(dir=路径.parent, delete=False) as 文件:
            临时文件 = Path(文件.name)
            文件.write(内容.encode(编码))
        临时文件.replace(路径)
    finally:
        if 临时文件 is not None and 临时文件.exists():
            临时文件.unlink()
    return 路径


def 核验MT5持久SOCKS5配置(配置路径: Path, 期望代理地址: str) -> list[str]:
    """读取 MT5 实际持久配置，不允许以启动 INI 代替。"""
    if not 配置路径.is_file():
        return ["MT5 持久代理配置缺失"]
    try:
        内容 = 配置路径.read_bytes().decode("utf-16")
    except UnicodeDecodeError:
        return ["MT5 持久代理配置编码无效"]
    字段 = dict(re.findall(r"(?m)^(ProxyEnable|ProxyType|ProxyAddress)=(.*)$", 内容))
    失败: list[str] = []
    if 字段.get("ProxyEnable") != "1":
        失败.append("MT5 持久代理未启用")
    if 字段.get("ProxyType") != "1":
        失败.append("MT5 持久代理不是 SOCKS5")
    if 字段.get("ProxyAddress") != 期望代理地址:
        失败.append("MT5 持久代理地址不匹配")
    return 失败


def _mac路径转WineZ盘(路径: Path) -> str:
    绝对路径 = 路径.resolve()
    return "Z:\\" + str(绝对路径).lstrip("/").replace("/", "\\")


@dataclass(frozen=True)
class 共享状态快照:
    文件: dict[str, str]

    @classmethod
    def 创建(cls, 目录列表: list[Path]) -> "共享状态快照":
        if not 目录列表:
            raise ValueError("至少需要一个受监控目录")
        文件: dict[str, str] = {}
        共同根目录 = Path(os.path.commonpath([str(目录) for 目录 in 目录列表]))
        for 根目录 in 目录列表:
            if not 根目录.is_dir():
                raise ValueError(f"受监控目录不存在: {根目录}")
            根标识 = 根目录.relative_to(共同根目录).as_posix()
            if 根标识 == ".":
                根标识 = 根目录.name
            for 路径 in sorted(根目录.rglob("*")):
                if 路径.is_file() and not 路径.is_symlink():
                    相对路径 = f"{根标识}/{路径.relative_to(根目录).as_posix()}"
                    if 相对路径 in 文件:
                        raise ValueError(f"受监控目录名称冲突: {相对路径}")
                    文件[相对路径] = sha256(路径.read_bytes()).hexdigest()
        return cls(文件)

    def 比较(self, 后: "共享状态快照") -> dict[str, list[str]]:
        前键 = set(self.文件)
        后键 = set(后.文件)
        return {
            "新增": sorted(后键 - 前键),
            "删除": sorted(前键 - 后键),
            "修改": sorted(键 for 键 in 前键 & 后键 if self.文件[键] != 后.文件[键]),
        }
