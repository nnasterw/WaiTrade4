from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
from time import monotonic, sleep
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

    def __init__(self, 进程: subprocess.Popen[object], 标准输出: Path, 标准错误: Path, Wine前缀: Path | None) -> None:
        self._进程 = 进程
        self.标准输出 = 标准输出
        self.标准错误 = 标准错误
        self._已启动时间 = datetime.now(timezone.utc).isoformat()
        self._进程组号 = os.getpgid(进程.pid) if os.name == "posix" else None
        self._Wine前缀 = Wine前缀
        self._自有Wine服务进程号: set[int] = set()
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
        Wine前缀文本 = 环境变量.get("WINEPREFIX")
        Wine前缀 = Path(Wine前缀文本).resolve() if Wine前缀文本 else None
        return cls(进程, 标准输出, 标准错误, Wine前缀)

    @staticmethod
    def _解码lsof路径(原始路径: bytes) -> Path | None:
        """解码 macOS lsof 对非 ASCII 路径使用的 ``\\xHH`` 转义。"""
        字节 = bytearray()
        下标 = 0
        while 下标 < len(原始路径):
            if 原始路径[下标 : 下标 + 2] == b"\\x":
                十六进制 = 原始路径[下标 + 2 : 下标 + 4]
                if len(十六进制) != 2:
                    return None
                try:
                    字节.append(int(十六进制, 16))
                except ValueError:
                    return None
                下标 += 4
            else:
                字节.append(原始路径[下标])
                下标 += 1
        try:
            return Path(bytes(字节).decode("utf-8")).resolve()
        except UnicodeDecodeError:
            return None

    @classmethod
    def _解析Wine服务进程(cls, 进程号: int, lsof输出: bytes, Wine前缀: Path) -> set[int]:
        """只接受 FD 4 精确指向受控 Prefix 的 wineserver。

        ``ps`` 会按当前 locale 损坏中文环境变量路径，故不能据
        ``WINEPREFIX`` 认领。Wine 的 server 则以 FD 4 打开 Prefix 根目录；
        这里先由调用者确认进程命令为 wineserver，再用该目录精确比对。
        """
        前缀 = Wine前缀.resolve()
        当前FD: bytes | None = None
        for 行 in lsof输出.splitlines():
            if 行.startswith(b"f"):
                当前FD = 行[1:]
            elif 当前FD == b"4" and 行.startswith(b"n"):
                路径 = cls._解码lsof路径(行[1:])
                return {进程号} if 路径 == 前缀 else set()
        return set()

    @staticmethod
    def _Wine服务候选进程号() -> set[int]:
        查询 = subprocess.run(["ps", "-axo", "pid=,command="], text=True, capture_output=True, check=False)
        if 查询.returncode != 0:
            raise RuntimeError(f"无法枚举 wineserver: {查询.stderr.strip()}")
        结果: set[int] = set()
        for 行 in 查询.stdout.splitlines():
            部分 = 行.strip().split(maxsplit=1)
            if len(部分) == 2 and 部分[0].isdigit() and "wineserver" in 部分[1]:
                结果.add(int(部分[0]))
        return 结果

    def 认领自有Wine服务(self) -> tuple[int, ...]:
        """登记本后台调用派生的 Prefix 专属 wineserver。

        调用方已在运行前拒绝任意既有 MT5/Wine 进程；因此此处仅能认领
        本次运行后、且环境变量精确指向本对象 Prefix 的服务进程。
        """
        if self._Wine前缀 is None or os.name != "posix":
            return ()
        self._自有Wine服务进程号.update(self._当前自有Wine服务())
        return tuple(sorted(self._自有Wine服务进程号))

    def _当前自有Wine服务(self) -> set[int]:
        if self._Wine前缀 is None or os.name != "posix":
            return set()
        结果: set[int] = set()
        for 进程号 in self._Wine服务候选进程号():
            查询 = subprocess.run(
                ["lsof", "-Fn", "-a", "-p", str(进程号), "-d", "4"],
                capture_output=True, check=False,
            )
            if 查询.returncode == 0:
                结果.update(self._解析Wine服务进程(进程号, 查询.stdout, self._Wine前缀))
        return 结果

    def 终止自有Wine服务(self, 超时秒数: float = 10) -> tuple[int, ...]:
        """仅回收已认领且仍绑定本对象 Prefix 的遗留 wineserver。"""
        if 超时秒数 <= 0:
            raise ValueError("Wine 服务清理超时必须为正")
        # wineserver 常在 terminal 退出后才创建；因此终止时以受控 Prefix
        # 精确匹配一次，将其认领为本对象的延迟派生进程。
        已认领 = set(self.认领自有Wine服务())
        if not 已认领:
            return ()
        # 再解析一次环境，防止 PID 已退出并被无关进程复用。
        当前 = self._当前自有Wine服务()
        待终止 = 已认领 & 当前
        for 进程号 in 待终止:
            try:
                os.kill(进程号, signal.SIGTERM)
            except ProcessLookupError:
                pass
        截止 = monotonic() + 超时秒数
        while monotonic() < 截止:
            存活 = self._当前自有Wine服务() & 待终止
            if not 存活:
                return tuple(sorted(待终止))
            sleep(0.1)
        存活 = self._当前自有Wine服务() & 待终止
        if 存活:
            raise RuntimeError(f"自有 wineserver 未在时限内退出: {sorted(存活)}")
        return tuple(sorted(待终止))

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
