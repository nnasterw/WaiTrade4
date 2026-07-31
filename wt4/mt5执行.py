from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import subprocess
from typing import Sequence

from wt4.experiment import 实验输入
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
        try:
            进程 = subprocess.run(
                self.配置.命令,
                cwd=暂存目录,
                capture_output=True,
                text=True,
                timeout=self.配置.超时秒数,
                check=False,
            )
        except subprocess.TimeoutExpired as 异常:
            日志.write_text(self._超时日志(异常), encoding="utf-8")
            return 执行结果(实验状态.执行无效, {}, {"原因": "MT5 执行超时"})

        日志.write_text(
            f"返回码={进程.returncode}\n--- stdout ---\n{进程.stdout}\n--- stderr ---\n{进程.stderr}",
            encoding="utf-8",
        )
        if 进程.returncode != 0:
            return 执行结果(实验状态.执行无效, {}, {"原因": f"MT5 返回码 {进程.returncode}"})

        工件 = {日志.name: self._哈希(日志)}
        缺失: list[str] = []
        for 相对路径 in self.配置.预期工件:
            文件 = self._受限工件路径(暂存目录, 相对路径)
            if not 文件.is_file() or 文件.is_symlink():
                缺失.append(相对路径)
            else:
                工件[相对路径] = self._哈希(文件)
        if 缺失:
            return 执行结果(实验状态.执行无效, {}, {"原因": "缺少 MT5 工件", "缺失": 缺失})
        return 执行结果(实验状态.已归档, 工件, {"MT5返回码": 进程.returncode})

    @staticmethod
    def _受限工件路径(暂存目录: Path, 相对路径: str) -> Path:
        路径 = Path(相对路径)
        if 路径.is_absolute() or ".." in 路径.parts:
            raise ValueError(f"MT5 工件路径越界: {相对路径}")
        return 暂存目录 / 路径

    @staticmethod
    def _哈希(路径: Path) -> str:
        return sha256(路径.read_bytes()).hexdigest()

    @staticmethod
    def _超时日志(异常: subprocess.TimeoutExpired) -> str:
        标准输出 = 异常.stdout or ""
        标准错误 = 异常.stderr or ""
        if isinstance(标准输出, bytes):
            标准输出 = 标准输出.decode(errors="replace")
        if isinstance(标准错误, bytes):
            标准错误 = 标准错误.decode(errors="replace")
        return f"超时命令={异常.cmd}\n--- stdout ---\n{标准输出}\n--- stderr ---\n{标准错误}"
