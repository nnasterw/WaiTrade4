from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
from typing import Mapping


@dataclass(frozen=True)
class 后台进程快照:
    进程号: int
    进程组号: int | None
    已启动时间: str
    状态: str
    返回码: int | None


class MT5后台进程:
    """只管理本对象创建的独立进程组，不枚举或清理其他 MT5/Wine 进程。"""

    def __init__(self, 进程: subprocess.Popen[object], 标准输出: Path, 标准错误: Path) -> None:
        self._进程 = 进程
        self.标准输出 = 标准输出
        self.标准错误 = 标准错误
        self._已启动时间 = datetime.now(timezone.utc).isoformat()
        self._进程组号 = os.getpgid(进程.pid) if os.name == "posix" else None
        if self._进程组号 is not None and self._进程组号 != 进程.pid:
            raise RuntimeError("后台 MT5 未创建独立进程组")

    @classmethod
    def 启动(
        cls,
        命令: tuple[str, ...],
        工作目录: Path,
        环境变量: Mapping[str, str],
        工件目录: Path,
    ) -> MT5后台进程:
        if not 命令:
            raise ValueError("后台 MT5 命令不能为空")
        if not 工作目录.is_dir() or not 工件目录.is_dir():
            raise ValueError("后台 MT5 目录必须存在")
        标准输出 = 工件目录 / "后台-stdout.txt"
        标准错误 = 工件目录 / "后台-stderr.txt"
        if 标准输出.exists() or 标准错误.exists():
            raise ValueError("后台 MT5 日志工件已存在")
        with 标准输出.open("w", encoding="utf-8") as 输出, 标准错误.open("w", encoding="utf-8") as 错误:
            进程 = subprocess.Popen(
                命令,
                cwd=工作目录,
                env=dict(环境变量),
                stdout=输出,
                stderr=错误,
                text=True,
                start_new_session=os.name == "posix",
            )
        return cls(进程, 标准输出, 标准错误)

    def 快照(self) -> 后台进程快照:
        返回码 = self._进程.poll()
        return 后台进程快照(
            进程号=self._进程.pid,
            进程组号=self._进程组号,
            已启动时间=self._已启动时间,
            状态="运行中" if 返回码 is None else "已退出",
            返回码=返回码,
        )

    def 等待(self, 超时秒数: int) -> int | None:
        if 超时秒数 <= 0:
            raise ValueError("后台 MT5 等待超时必须为正")
        try:
            return self._进程.wait(timeout=超时秒数)
        except subprocess.TimeoutExpired:
            return None

    def 终止自有进程组(self) -> None:
        if self._进程.poll() is not None:
            return
        if os.name == "posix":
            assert self._进程组号 == self._进程.pid
            os.killpg(self._进程组号, signal.SIGTERM)
        else:
            self._进程.terminate()

    def 输出文本(self) -> tuple[str, str]:
        return (
            self.标准输出.read_text(encoding="utf-8", errors="replace"),
            self.标准错误.read_text(encoding="utf-8", errors="replace"),
        )
