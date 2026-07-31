from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from wt4.验收 import 硬门槛结果


@dataclass(frozen=True)
class 评分原料:
    样本外净收益: Decimal
    压力净收益: Decimal
    成本保留率: Decimal
    最大回撤: Decimal
    最大单笔贡献: Decimal
    移除最佳月后压力期望: Decimal
    月度正收益比例: Decimal
    证据完整: bool
    订单异常数: int


@dataclass(frozen=True)
class 评分卡:
    指标: dict[str, Any]
    总分: int | None
    最高状态: str
    等级限制原因: list[str]


@dataclass(frozen=True)
class 基线样本:
    """一个已封存、已通过硬门的代表性策略周期汇总。"""

    实验身份: str
    原料: 评分原料
    硬门结果: 硬门槛结果


@dataclass(frozen=True)
class 评分标尺:
    """由代表性基线池校准出的可追溯三档相对标尺。

    评分只用于把已通过硬门的候选放入人工复核优先级；不替代风险、
    证据和治理硬门，也不能被用于生产准入。
    """

    基线身份: tuple[str, ...]
    标尺身份: str
    三档分界: dict[str, tuple[Decimal, Decimal]]


_评分指标 = (
    ("样本外净收益", "样本外净收益", True),
    ("压力净收益", "压力净收益", True),
    ("成本保留率", "成本保留率", True),
    ("最大权益回撤", "最大回撤", False),
    ("最大单笔贡献", "最大单笔贡献", False),
    ("移除最佳月后压力期望", "移除最佳月后压力期望", True),
    ("月度正收益比例", "月度正收益比例", True),
)


def 校准评分标尺(基线池: list[基线样本]) -> 评分标尺:
    """从至少五个有完整证据的代表性基线样本计算每项的三档分界。

    分界采用基线池的 1/3 与 2/3 分位位置，故它只表达相对复用优先级，
    不把当前小样本伪装成可跨市场复用的绝对收益目标。
    """
    if len(基线池) < 5:
        raise ValueError("评分标尺至少需要五个代表性基线样本")
    身份 = tuple(样本.实验身份 for 样本 in 基线池)
    if any(not 标识 for 标识 in 身份) or len(set(身份)) != len(身份):
        raise ValueError("基线实验身份必须非空且唯一")
    if any(not 样本.原料.证据完整 or 样本.原料.订单异常数 or not 样本.硬门结果.通过 for 样本 in 基线池):
        raise ValueError("基线池只能包含硬门通过、证据完整且无订单异常的样本")
    已排序基线池 = tuple(sorted(基线池, key=lambda 样本: 样本.实验身份))
    身份 = tuple(样本.实验身份 for 样本 in 已排序基线池)

    三档分界: dict[str, tuple[Decimal, Decimal]] = {}
    for 指标名, 属性名, _ in _评分指标:
        值 = sorted(getattr(样本.原料, 属性名) for 样本 in 已排序基线池)
        三档分界[指标名] = (值[(len(值) - 1) // 3], 值[(len(值) - 1) * 2 // 3])
    规范内容 = json.dumps(
        {"基线身份": 身份, "三档分界": {名称: [str(值) for 值 in 分界] for 名称, 分界 in 三档分界.items()}},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return 评分标尺(身份, sha256(规范内容.encode()).hexdigest(), 三档分界)


def 生成评分卡(原料: 评分原料, 标尺: 评分标尺 | None = None, *, 硬门结果: 硬门槛结果 | None = None) -> 评分卡:
    限制: list[str] = []
    if not 原料.证据完整:
        限制.append("证据不完整")
    if 原料.订单异常数:
        限制.append("存在订单异常")
    if 原料.移除最佳月后压力期望 <= 0:
        限制.append("移除最佳月后压力期望非正")
    if 硬门结果 is None or not 硬门结果.通过:
        限制.append("验收硬门未通过")
    最高状态 = "观察" if 限制 else "候选"
    指标: dict[str, Any] = {
        "样本外净收益": 原料.样本外净收益,
        "压力净收益": 原料.压力净收益,
        "成本保留率": 原料.成本保留率,
        "最大权益回撤": 原料.最大回撤,
        "最大单笔贡献": 原料.最大单笔贡献,
        "移除最佳月后压力期望": 原料.移除最佳月后压力期望,
        "月度正收益比例": 原料.月度正收益比例,
        "订单异常数": 原料.订单异常数,
    }
    if 标尺 is None:
        return 评分卡(指标, None, 最高状态, 限制)
    总分, 分项 = _按标尺评分(原料, 标尺)
    指标["评分标尺身份"] = 标尺.标尺身份
    指标["三档分项"] = 分项
    if not 限制:
        最高状态 = ("优先人工复核" if 总分 >= 10 else "候选")
    return 评分卡(指标, 总分, 最高状态, 限制)


def _按标尺评分(原料: 评分原料, 标尺: 评分标尺) -> tuple[int, dict[str, int]]:
    指标分: dict[str, int] = {}
    for 指标名, 属性名, 高者优先 in _评分指标:
        if 指标名 not in 标尺.三档分界:
            raise ValueError(f"评分标尺缺少指标: {指标名}")
        低分界, 高分界 = 标尺.三档分界[指标名]
        值 = getattr(原料, 属性名)
        if 高者优先:
            分数 = 0 if 值 < 低分界 else 1 if 值 < 高分界 else 2
        else:
            分数 = 2 if 值 <= 低分界 else 1 if 值 <= 高分界 else 0
        指标分[指标名] = 分数
    return sum(指标分.values()), 指标分
