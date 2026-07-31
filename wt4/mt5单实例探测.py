from __future__ import annotations

import json
from pathlib import Path

from wt4.experiment import 实验输入
from wt4.mt5执行 import MT5回测配置, 隔离MT5执行器
from wt4.mt5探测 import MT5短窗口探测配置, 共享状态快照, 生成MT5探测配置
from wt4.编排 import 执行结果


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
        主日志证据 = self._保留本次主日志证据(暂存目录, 差异)
        工件 = dict(结果.工件)
        for 名称 in ("mt5-探测.ini", "共享状态-运行前.json", "共享状态差异.json", 主日志证据):
            路径 = 暂存目录 / 名称
            工件[名称] = 隔离MT5执行器._哈希(路径)
        return 执行结果(结果.状态, 工件, {**结果.结果, "共享状态差异": 差异})

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

    def _保留本次主日志证据(self, 暂存目录: Path, 差异: dict[str, list[str]]) -> str:
        """将发生变化的主日志复制到实验暂存，避免共享日志轮转后丢失证据。"""
        主日志变化 = [
            相对路径
            for 相对路径 in [*差异["新增"], *差异["修改"]]
            if 相对路径.startswith("logs/")
        ]
        证据路径 = 暂存目录 / "MT5主日志证据.txt"
        内容: list[str] = []
        for 相对路径 in 主日志变化:
            源文件 = self.探测配置.终端目录 / 相对路径
            if 源文件.is_file() and not 源文件.is_symlink():
                内容.append(f"--- {相对路径} ---\n")
                内容.append(源文件.read_text(encoding="utf-16le", errors="replace"))
        证据路径.write_text("".join(内容), encoding="utf-8")
        return 证据路径.name
