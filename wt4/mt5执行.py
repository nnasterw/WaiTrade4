from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
from typing import Mapping

from wt4.experiment import 实验输入
from wt4.mt5后台 import MT5后台进程
from wt4.编排 import 实验状态, 执行结果


@dataclass(frozen=True)
class MT5回测配置:
    """单个隔离 MT5 实例的一次回测调用。

    所有相对工件路径都以本次实验暂存目录为根；执行器不触碰共享
    terminal、Tester cache 或其他实例的进程。
    """

    命令: tuple[str, ...]
    超时秒数: int
    预期工件: tuple[str, ...]
    环境变量: Mapping[str, str] | None = None


class 隔离MT5执行器:
    def __init__(self, 配置: MT5回测配置) -> None:
        if not 配置.命令:
            raise ValueError("MT5 命令不能为空")
        if 配置.超时秒数 <= 0:
            raise ValueError("MT5 超时必须为正")
        if not 配置.预期工件:
            raise ValueError("MT5 必须声明预期工件")
        self.配置 = 配置

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        日志 = 暂存目录 / "执行日志.txt"
        进程 = MT5后台进程.启动(self.配置.命令, 暂存目录, self._环境(), 暂存目录)
        启动快照 = 进程.快照()
        返回码 = 进程.等待(self.配置.超时秒数)
        if 返回码 is None:
            进程.终止自有进程组()
            返回码 = 进程.等待(5)
            Wine服务 = 进程.终止自有Wine服务()
            标准输出, 标准错误 = 进程.输出文本()
            日志.write_text(
                self._执行日志(返回码, 标准输出, 标准错误, 超时=True),
                encoding="utf-8",
            )
            return 执行结果(
                实验状态.执行无效,
                {},
                {"原因": "MT5 执行超时", "后台进程": self._后台证据(启动快照, 进程.快照()), "受限回收Wine服务进程号": list(Wine服务)},
            )
        标准输出, 标准错误 = 进程.输出文本()
        Wine服务 = 进程.终止自有Wine服务()

        日志.write_text(
            self._执行日志(返回码, 标准输出, 标准错误),
            encoding="utf-8",
        )
        if 返回码 != 0:
            return 执行结果(
                实验状态.执行无效,
                {},
                {"原因": f"MT5 返回码 {返回码}", "后台进程": self._后台证据(启动快照, 进程.快照()), "受限回收Wine服务进程号": list(Wine服务)},
            )

        工件 = {
            日志.name: self._哈希(日志),
            进程.标准输出.name: self._哈希(进程.标准输出),
            进程.标准错误.name: self._哈希(进程.标准错误),
        }
        缺失: list[str] = []
        for 相对路径 in self.配置.预期工件:
            文件 = self._受限工件路径(暂存目录, 相对路径)
            if not 文件.is_file() or 文件.is_symlink():
                缺失.append(相对路径)
            else:
                工件[相对路径] = self._哈希(文件)
        if 缺失:
            return 执行结果(
                实验状态.执行无效,
                {},
                {"原因": "缺少 MT5 工件", "缺失": 缺失, "后台进程": self._后台证据(启动快照, 进程.快照()), "受限回收Wine服务进程号": list(Wine服务)},
            )
        return 执行结果(
            实验状态.已归档,
            工件,
            {"MT5返回码": 返回码, "后台进程": self._后台证据(启动快照, 进程.快照()), "受限回收Wine服务进程号": list(Wine服务)},
        )

    @staticmethod
    def _后台证据(启动: object, 结束: object) -> dict[str, object]:
        return {
            "进程号": getattr(启动, "进程号"),
            "进程组号": getattr(启动, "进程组号"),
            "已启动时间": getattr(启动, "已启动时间"),
            "结束状态": getattr(结束, "状态"),
            "返回码": getattr(结束, "返回码"),
        }

    @staticmethod
    def _受限工件路径(暂存目录: Path, 相对路径: str) -> Path:
        路径 = Path(相对路径)
        if 路径.is_absolute() or ".." in 路径.parts:
            raise ValueError(f"MT5 工件路径越界: {相对路径}")
        return 暂存目录 / 路径

    def _环境(self) -> dict[str, str]:
        环境 = os.environ.copy()
        if self.配置.环境变量:
            环境.update(self.配置.环境变量)
        return 环境

    @staticmethod
    def _哈希(路径: Path) -> str:
        return sha256(路径.read_bytes()).hexdigest()

    @staticmethod
    def _执行日志(返回码: int | None, 标准输出: str, 标准错误: str, 超时: bool = False) -> str:
        前缀 = "执行超时\n" if 超时 else ""
        return f"{前缀}返回码={返回码}\n--- stdout ---\n{标准输出}\n--- stderr ---\n{标准错误}"
