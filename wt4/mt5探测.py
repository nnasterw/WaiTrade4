from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path


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


def 生成MT5探测配置(配置: MT5短窗口探测配置, 暂存目录: Path) -> Path:
    """生成一次性 INI；报告只允许落在实验暂存目录。"""
    if not 暂存目录.is_dir():
        raise ValueError(f"实验暂存目录不存在: {暂存目录}")
    if not (配置.终端目录 / "terminal64.exe").is_file():
        raise ValueError(f"MT5 终端不存在: {配置.终端目录}")
    if not 配置.代理地址:
        raise ValueError("MT5 探测必须显式指定代理")
    if not 配置.登录账号 or not 配置.服务器:
        raise ValueError("MT5 探测必须显式指定登录账号和服务器")
    if 配置.初始资金 != 300:
        raise ValueError("首期 MT5 探测初始资金必须为 300 美元")

    报告路径 = _mac路径转WineZ盘(暂存目录 / "报告.html")
    内容 = f"""; wt4 单实例能力探测。不可作为策略验收结论。
[Common]
Login={配置.登录账号}
Server={配置.服务器}
ProxyEnable=1
ProxyType=0
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
Report={报告路径}
"""
    路径 = 暂存目录 / "mt5-探测.ini"
    路径.write_text(内容, encoding="utf-8")
    return 路径


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
