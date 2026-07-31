from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Protocol

from wt4.experiment import 实验输入
from wt4.工件 import 归档工件
from wt4.账本 import 追加式账本


class 实验状态(StrEnum):
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

    def 运行(self, 输入: 实验输入, 执行器: MT5执行器) -> 编排结果:
        身份 = 输入.身份
        if self.账本.事件(身份):
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
