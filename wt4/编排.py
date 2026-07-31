from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
from collections import deque
from threading import Condition, Thread
from typing import Protocol

from wt4.experiment import 实验输入
from wt4.工件 import 归档工件
from wt4.账本 import 追加式账本


class 实验状态(StrEnum):
    已排队 = "已排队"
    已取消 = "已取消"
    已创建 = "已创建"
    已归档 = "已归档"
    有效失败 = "有效失败"
    执行无效 = "执行无效"
    数据无效 = "数据无效"
    治理无效 = "治理无效"


@dataclass(frozen=True)
class 执行结果:
    状态: 实验状态
    工件: dict[str, str]
    结果: dict[str, object]


class MT5执行器(Protocol):
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果: ...


@dataclass(frozen=True)
class 编排结果:
    实验身份: str
    状态: 实验状态
    工件目录: Path | None


class 中央实验编排器:
    """将一次不可变输入执行为可追溯、不可覆盖的实验。"""

    def __init__(self, 账本: 追加式账本, 暂存根目录: Path, 工件根目录: Path) -> None:
        self.账本 = 账本
        self.暂存根目录 = 暂存根目录
        self.工件根目录 = 工件根目录

    def 回收未终态实验(self, 实验身份: str, 原因: str = "检测到未完成的后台实验") -> bool:
        """fail-closed 收敛宿主退出时遗留的已创建实验。

        仅允许追加 ``执行无效``，绝不自动重跑或覆盖暂存工件；仍在排队的
        任务没有启动过 MT5，必须交由显式恢复流程处理。
        """
        事件 = self.账本.事件(实验身份)
        if not 事件 or 事件[-1].类型 != 实验状态.已创建:
            return False
        self.账本.追加(实验身份, 实验状态.执行无效, {"原因": 原因})
        return True

    def 受限恢复遗留后台实验(self, 实验身份: str) -> bool:
        """仅在本轮归属记录可精确验证时回收宿主退出后的实验。

        不扫描系统进程，也不碰其他实验目录。进程组验证或账本状态任一
        不符合预期，均保持原样并返回 ``False``。
        """
        from wt4.mt5后台 import MT5后台进程

        归属记录 = self.暂存根目录 / 实验身份 / "后台-归属.json"
        if not MT5后台进程.回收遗留自有进程组(归属记录):
            return False
        return self.回收未终态实验(实验身份, "后台宿主提前退出，已受限回收本轮进程组")

    def 运行(self, 输入: 实验输入, 执行器: MT5执行器, *, 允许已排队: bool = False) -> 编排结果:
        身份 = 输入.身份
        已有事件 = self.账本.事件(身份)
        if 已有事件 and not (允许已排队 and [事件.类型 for 事件 in 已有事件] == [实验状态.已排队]):
            raise ValueError(f"实验身份已存在，拒绝重跑: {身份}")
        暂存目录 = self.暂存根目录 / 身份
        if 暂存目录.exists() or (self.工件根目录 / 身份).exists():
            raise ValueError(f"实验目录已存在，拒绝覆盖: {身份}")

        暂存目录.mkdir(parents=True)
        self.账本.追加(身份, 实验状态.已创建, {"输入": json.loads(输入.规范内容())})
        try:
            执行结果 = 执行器.执行(输入, 暂存目录)
            if 执行结果.状态 not in {
                实验状态.已归档,
                实验状态.有效失败,
                实验状态.执行无效,
                实验状态.数据无效,
                实验状态.治理无效,
            }:
                raise ValueError(f"不支持的实验终态: {执行结果.状态}")

            if 执行结果.状态 is not 实验状态.已归档:
                self.账本.追加(身份, 执行结果.状态, 执行结果.结果)
                return 编排结果(身份, 执行结果.状态, None)

            预期哈希 = self._写入验收结果(暂存目录, 执行结果)
            工件目录 = 归档工件(暂存目录, self.工件根目录, 身份, 预期哈希)
            self.账本.追加(身份, 实验状态.已归档, {"工件目录": str(工件目录), **执行结果.结果})
            return 编排结果(身份, 实验状态.已归档, 工件目录)
        except Exception as 异常:
            # 账本的终态本身也可能失败（例如磁盘已满），此时不掩盖原始
            # 执行错误；正常路径下必须留下一条明确的执行无效终态。
            self.账本.追加(身份, 实验状态.执行无效, {"原因": str(异常)})
            raise

    @staticmethod
    def _写入验收结果(暂存目录: Path, 执行结果: 执行结果) -> dict[str, str]:
        结果文件 = 暂存目录 / "验收结果.json"
        if 结果文件.exists():
            raise ValueError("执行器不得预写验收结果.json")
        结果文件.write_text(
            json.dumps(执行结果.结果, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        预期哈希 = dict(执行结果.工件)
        预期哈希[结果文件.name] = sha256(结果文件.read_bytes()).hexdigest()
        return 预期哈希


class 后台任务状态(StrEnum):
    已排队 = "已排队"
    运行中 = "运行中"
    已取消 = "已取消"
    已完成 = "已完成"


@dataclass(frozen=True)
class 后台任务快照:
    实验身份: str
    状态: 后台任务状态
    实验状态: 实验状态 | None
    异常: str | None


@dataclass
class _后台任务:
    输入: 实验输入
    执行器: MT5执行器
    状态: 后台任务状态 = 后台任务状态.已排队
    结果: 编排结果 | None = None
    异常: str | None = None


class 中央单实例后台队列:
    """以单一工作线程串行消费不可变实验。

    这不是 MT5 的伪并行包装：任一时刻至多调用一个执行器。提交、取消、
    失败和终态均写入同一追加式账本；取消仅允许发生在尚未启动的任务上。
    """

    def __init__(self, 编排器: 中央实验编排器) -> None:
        self._编排器 = 编排器
        self._条件 = Condition()
        self._待执行: deque[str] = deque()
        self._任务: dict[str, _后台任务] = {}
        self._工作线程: Thread | None = None

    def 提交(self, 输入: 实验输入, 执行器: MT5执行器) -> str:
        身份 = 输入.身份
        with self._条件:
            if 身份 in self._任务 or self._编排器.账本.事件(身份):
                raise ValueError(f"实验身份已存在，拒绝重复提交: {身份}")
            if (self._编排器.暂存根目录 / 身份).exists() or (self._编排器.工件根目录 / 身份).exists():
                raise ValueError(f"实验目录已存在，拒绝覆盖: {身份}")
            self._编排器.账本.追加(身份, 实验状态.已排队, {"输入": json.loads(输入.规范内容())})
            self._任务[身份] = _后台任务(输入, 执行器)
            self._待执行.append(身份)
            if self._工作线程 is None or not self._工作线程.is_alive():
                self._工作线程 = Thread(target=self._持续执行, name="wt4-中央单实例队列", daemon=True)
                self._工作线程.start()
            self._条件.notify_all()
        return 身份

    def 取消(self, 实验身份: str, 原因: str = "用户取消") -> bool:
        with self._条件:
            任务 = self._任务.get(实验身份)
            if 任务 is None or 任务.状态 is not 后台任务状态.已排队:
                return False
            self._待执行.remove(实验身份)
            任务.状态 = 后台任务状态.已取消
            self._编排器.账本.追加(实验身份, 实验状态.已取消, {"原因": 原因})
            self._条件.notify_all()
            return True

    def 快照(self, 实验身份: str) -> 后台任务快照:
        with self._条件:
            任务 = self._任务.get(实验身份)
            if 任务 is None:
                raise KeyError(f"未知后台任务: {实验身份}")
            return 后台任务快照(
                实验身份, 任务.状态, 任务.结果.状态 if 任务.结果 else None, 任务.异常
            )

    def 等待(self, 实验身份: str, 超时秒数: float) -> 后台任务快照:
        if 超时秒数 <= 0:
            raise ValueError("等待超时必须为正")
        from time import monotonic

        截止 = monotonic() + 超时秒数
        with self._条件:
            while self._任务[实验身份].状态 in {后台任务状态.已排队, 后台任务状态.运行中}:
                剩余 = 截止 - monotonic()
                if 剩余 <= 0:
                    raise TimeoutError(f"后台任务未在时限内结束: {实验身份}")
                self._条件.wait(剩余)
            return self.快照(实验身份)

    def _持续执行(self) -> None:
        while True:
            with self._条件:
                if not self._待执行:
                    return
                身份 = self._待执行.popleft()
                任务 = self._任务[身份]
                # 取消会将任务从 deque 移除；此处仍明确保护未来维护变更。
                if 任务.状态 is not 后台任务状态.已排队:
                    continue
                任务.状态 = 后台任务状态.运行中
                self._条件.notify_all()
            try:
                结果 = self._编排器.运行(任务.输入, 任务.执行器, 允许已排队=True)
            except Exception as 异常:  # 编排器已将执行异常作为终态留痕。
                with self._条件:
                    任务.异常 = str(异常)
                    任务.状态 = 后台任务状态.已完成
                    self._条件.notify_all()
            else:
                with self._条件:
                    任务.结果 = 结果
                    任务.状态 = 后台任务状态.已完成
                    self._条件.notify_all()
