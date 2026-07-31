from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from wt4.experiment import 实验输入
from wt4.mt5执行 import MT5回测配置, 隔离MT5执行器
from wt4.mt5探测 import MT5短窗口探测配置, 共享状态快照, 生成MT5探测配置
from wt4.编排 import 执行结果


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
    已启动 = "tester automatical testing started" in 小写日志
    已成功 = 'tester last test passed with result "successfully finished"' in 小写日志
    已退出 = "terminal exit with code 0" in 小写日志
    return {
        "已启动": 已启动,
        "已成功": 已成功,
        "已退出": 已退出,
        "失败标记": list(失败标记),
        "完整": 已启动 and 已成功 and 已退出 and not 失败标记,
    }


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
        受监控目录 = self._受监控目录()
        运行前 = 共享状态快照.创建(受监控目录)
        运行前日志 = self._日志字节快照()
        (暂存目录 / "共享状态-运行前.json").write_text(
            json.dumps(运行前.文件, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )

        命令 = (
            str(self.Wine命令),
            r"C:\Program Files\MetaTrader 5 Tester\terminal64.exe",
            f"/config:{self._mac路径转WineZ盘(运行配置)}",
        )
        结果 = 隔离MT5执行器(
            MT5回测配置(
                命令=命令,
                超时秒数=self.超时秒数,
                预期工件=("报告.html",),
                环境变量={"WINEPREFIX": str(self.Wine前缀)},
            )
        ).执行(输入, 暂存目录)

        运行后 = 共享状态快照.创建(受监控目录)
        差异 = 运行前.比较(运行后)
        (暂存目录 / "共享状态差异.json").write_text(
            json.dumps(差异, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
        日志证据 = self._保留本次日志证据(暂存目录, 运行前日志)
        生命周期 = 解析MT5生命周期((暂存目录 / 日志证据).read_text(encoding="utf-8"))
        工件 = dict(结果.工件)
        for 名称 in ("mt5-探测.ini", "共享状态-运行前.json", "共享状态差异.json", 日志证据):
            路径 = 暂存目录 / 名称
            工件[名称] = 隔离MT5执行器._哈希(路径)
        结果数据 = {**结果.结果, "共享状态差异": 差异, "MT5生命周期": 生命周期}
        if 结果.状态.value == "已归档" and not 生命周期["完整"]:
            return 执行结果(
                结果.状态.执行无效,
                {},
                {**结果数据, "原因": "MT5 生命周期证据不完整"},
            )
        return 执行结果(结果.状态, 工件, 结果数据)

    def _受监控目录(self) -> list[Path]:
        根目录 = self.探测配置.终端目录
        return [
            根目录 / "logs",
            根目录 / "Tester" / "cache",
            根目录 / "Tester" / "logs",
            根目录 / "Tester" / "Agent-127.0.0.1-3000" / "logs",
            根目录 / "reports",
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
