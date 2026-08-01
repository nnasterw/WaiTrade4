from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
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

    def __init__(
        self,
        进程: subprocess.Popen[object],
        标准输出: Path,
        标准错误: Path,
        Wine前缀: Path | None,
        启动前Wine服务进程号: set[int],
    ) -> None:
        self._进程 = 进程
        self.标准输出 = 标准输出
        self.标准错误 = 标准错误
        self.归属记录 = 标准输出.parent / "后台-归属.json"
        self._已启动时间 = datetime.now(timezone.utc).isoformat()
        self._进程组号 = os.getpgid(进程.pid) if os.name == "posix" else None
        self._Wine前缀 = Wine前缀
        self._启动前Wine服务进程号 = 启动前Wine服务进程号
        self._自有Wine服务进程号: set[int] = set()
        if self._进程组号 is not None and self._进程组号 != 进程.pid:
            raise RuntimeError("后台 MT5 未创建独立进程组")
        self._写入归属记录("运行中")

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
        Wine前缀文本 = 环境变量.get("WINEPREFIX")
        Wine前缀 = Path(Wine前缀文本).resolve() if Wine前缀文本 else None
        启动前Wine服务进程号 = cls._查询Wine服务(Wine前缀) if Wine前缀 is not None and os.name == "posix" else set()
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
        return cls(进程, 标准输出, 标准错误, Wine前缀, 启动前Wine服务进程号)

    def _归属内容(self, 状态: str, *, 原因: str | None = None) -> dict[str, object]:
        """生成可由后继宿主验证的最小进程组归属证据。"""
        实验目录 = self.归属记录.parent.resolve()
        内容: dict[str, object] = {
            "版本": 1,
            "状态": 状态,
            "进程号": self._进程.pid,
            "进程组号": self._进程组号,
            "实验目录": str(实验目录),
            # 实验目录末级为不可变身份；它必须仍出现在进程命令行中，才允许
            # 新宿主操作该独立进程组。不能按 terminal/wine 进程名回收。
            "命令验证片段": 实验目录.name,
            "已启动时间": self._已启动时间,
        }
        if self._Wine前缀 is not None:
            内容["Wine前缀"] = str(self._Wine前缀)
        if 原因 is not None:
            内容["原因"] = 原因
        return 内容

    def _写入归属记录(self, 状态: str, *, 原因: str | None = None) -> None:
        if self.归属记录.exists():
            raise ValueError(f"后台 MT5 归属记录已存在: {self.归属记录}")
        临时 = self.归属记录.with_suffix(".json.tmp")
        临时.write_text(json.dumps(self._归属内容(状态, 原因=原因), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        临时.replace(self.归属记录)

    @staticmethod
    def _读取归属记录(归属记录: Path) -> dict[str, object] | None:
        if not 归属记录.is_file() or 归属记录.is_symlink():
            return None
        try:
            内容 = json.loads(归属记录.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(内容, dict) or 内容.get("版本") != 1:
            return None
        if not isinstance(内容.get("进程号"), int) or not isinstance(内容.get("进程组号"), int):
            return None
        if 内容["进程号"] != 内容["进程组号"]:
            return None
        实验目录 = 归属记录.parent.resolve()
        if 内容.get("实验目录") != str(实验目录):
            return None
        if 内容.get("命令验证片段") != 实验目录.name:
            return None
        Wine前缀 = 内容.get("Wine前缀")
        if Wine前缀 is not None:
            if not isinstance(Wine前缀, str):
                return None
            try:
                前缀路径 = Path(Wine前缀).resolve()
                运行根目录 = next(祖先 for 祖先 in 实验目录.parents if 祖先.name == "runtime")
                前缀路径.relative_to(运行根目录)
            except (OSError, StopIteration, ValueError):
                return None
            if not 前缀路径.is_dir():
                return None
        return 内容

    @staticmethod
    def _进程组成员(进程组号: int) -> list[tuple[int, str]]:
        查询 = subprocess.run(["ps", "-axo", "pid=,pgid=,stat=,command="], text=True, capture_output=True, check=False)
        if 查询.returncode != 0:
            return []
        成员: list[tuple[int, str]] = []
        for 行 in 查询.stdout.splitlines():
            匹配 = re.match(r"\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)", 行)
            if 匹配 and int(匹配.group(2)) == 进程组号 and not 匹配.group(3).startswith("Z"):
                成员.append((int(匹配.group(1)), 匹配.group(4)))
        return 成员

    @classmethod
    def 回收遗留自有进程组(cls, 归属记录: Path, 超时秒数: float = 10) -> bool:
        """仅凭归属记录精确回收宿主退出后遗留的独立进程组。

        必须同时满足：记录结构有效、PGID 等于原始组长 PID、该组仍有成员，
        且至少一个成员的命令行包含本轮实验身份。验证失败时绝不发送信号。
        """
        if os.name != "posix" or 超时秒数 <= 0:
            return False
        内容 = cls._读取归属记录(归属记录)
        if 内容 is None or 内容.get("状态") != "运行中":
            return False
        进程组号 = int(内容["进程组号"])
        成员 = cls._进程组成员(进程组号)
        验证片段 = str(内容["命令验证片段"])
        if not 成员 or not any(验证片段 in 命令 for _, 命令 in 成员):
            return False
        try:
            os.killpg(进程组号, signal.SIGTERM)
        except ProcessLookupError:
            return False
        # macOS 上组长退出后，短暂的僵尸记录仍可能由父 Python 等待回收；
        # 此时进程组内已无可运行成员，不能把它误判为回收失败。
        截止 = monotonic() + 超时秒数
        while monotonic() < 截止:
            if not cls._进程组成员(进程组号):
                Wine服务 = cls.回收遗留自有Wine服务(归属记录, 内容)
                cls._更新归属记录状态(
                    归属记录,
                    内容,
                    "已受限回收",
                    额外内容={"受限回收Wine服务进程号": list(Wine服务)},
                )
                return True
            sleep(0.1)
        return False

    @classmethod
    def 回收遗留自有Wine服务(
        cls,
        归属记录: Path,
        内容: dict[str, object] | None = None,
        超时秒数: float = 10,
    ) -> tuple[int, ...]:
        """在已验证归属记录中精确回收独立派生的 wineserver。

        Wine 服务不属于 terminal 所在进程组。仅接受归属记录内、且仍位于
        同一工作区 ``runtime`` 下的专属 Prefix；再以 wineserver 的 FD 4
        精确匹配 Prefix。旧归属记录未包含 Prefix 时保守地不做任何操作。
        """
        if os.name != "posix" or 超时秒数 <= 0:
            return ()
        # 即便调用方刚刚验证过归属记录，也重新从磁盘读取一次。这个公开
        # 方法不能因为调用方构造的字典而越过路径和结构校验。
        已验证内容 = cls._读取归属记录(归属记录)
        if 内容 is not None and 已验证内容 != 内容:
            return ()
        if 已验证内容 is None:
            return ()
        Wine前缀文本 = 已验证内容.get("Wine前缀")
        if not isinstance(Wine前缀文本, str):
            return ()
        Wine前缀 = Path(Wine前缀文本).resolve()
        待终止 = cls._查询Wine服务(Wine前缀)
        for 进程号 in 待终止:
            try:
                os.kill(进程号, signal.SIGTERM)
            except ProcessLookupError:
                pass
        截止 = monotonic() + 超时秒数
        while monotonic() < 截止:
            if not (cls._查询Wine服务(Wine前缀) & 待终止):
                return tuple(sorted(待终止))
            sleep(0.1)
        return ()

    @classmethod
    def 确认遗留自有进程组已退出(cls, 归属记录: Path) -> bool:
        """确认有效归属记录对应的进程组已经不存在，但绝不发送信号。

        这只用于宿主已提前退出、进程组又已由系统收敛的场景。既要确认
        ``ps`` 中没有非僵尸成员，也要以 ``killpg(..., 0)`` 得到
        ``ProcessLookupError``，避免把 PID/PGID 复用或短暂僵尸误判为结束。
        """
        if os.name != "posix":
            return False
        内容 = cls._读取归属记录(归属记录)
        if 内容 is None or 内容.get("状态") != "运行中":
            return False
        进程组号 = int(内容["进程组号"])
        if cls._进程组成员(进程组号):
            return False
        try:
            os.killpg(进程组号, 0)
        except ProcessLookupError:
            cls._更新归属记录状态(归属记录, 内容, "已确认退出")
            return True
        except PermissionError:
            return False
        return False

    @staticmethod
    def _更新归属记录状态(
        归属记录: Path,
        内容: dict[str, object],
        状态: str,
        *,
        额外内容: Mapping[str, object] | None = None,
    ) -> None:
        更新 = {
            **内容,
            **(额外内容 or {}),
            "状态": 状态,
            "结束时间": datetime.now(timezone.utc).isoformat(),
        }
        临时 = 归属记录.with_suffix(".json.tmp")
        临时.write_text(json.dumps(更新, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        临时.replace(归属记录)

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

        只认领启动前不存在、且 FD 4 精确指向本对象 Prefix 的服务进程；
        即便有外部调用恰好使用同一 Prefix，也不会被本对象回收。
        """
        if self._Wine前缀 is None or os.name != "posix":
            return ()
        self._自有Wine服务进程号.update(self._当前自有Wine服务() - self._启动前Wine服务进程号)
        return tuple(sorted(self._自有Wine服务进程号))

    @classmethod
    def _查询Wine服务(cls, Wine前缀: Path | None) -> set[int]:
        if Wine前缀 is None or os.name != "posix":
            return set()
        结果: set[int] = set()
        for 进程号 in cls._Wine服务候选进程号():
            查询 = subprocess.run(
                ["lsof", "-Fn", "-a", "-p", str(进程号), "-d", "4"],
                capture_output=True, check=False,
            )
            if 查询.returncode == 0:
                结果.update(cls._解析Wine服务进程(进程号, 查询.stdout, Wine前缀))
        return 结果

    def _当前自有Wine服务(self) -> set[int]:
        return self._查询Wine服务(self._Wine前缀)

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
            返回码 = self._进程.wait(timeout=超时秒数)
            内容 = self._读取归属记录(self.归属记录)
            if 内容 is not None and 内容.get("状态") == "运行中":
                self._更新归属记录状态(self.归属记录, 内容, "已退出")
            return 返回码
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
