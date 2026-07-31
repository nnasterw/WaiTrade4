from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
from typing import Any

from wt4.窗口 import 验收窗口


@dataclass(frozen=True)
class 实验输入:
    策略实现提交: str
    二进制哈希: str
    参数: dict[str, Any]
    数据指纹: str
    成本快照: str
    合约规格: str
    mt5版本: str
    建模方式: int
    起始日: str
    结束日: str
    分区: str
    正式策略验收: bool = False
    交易品种: str | None = None
    初始资金: str | None = None

    @property
    def 身份(self) -> str:
        规范内容 = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(规范内容.encode("utf-8")).hexdigest()

    def 规范内容(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=2)


def 核验正式策略验收批次(批次: tuple[实验输入, ...], 窗口: 验收窗口) -> None:
    """拒绝将能力探测或不完整时间范围冒充为 BTC 正式策略验收。"""
    if len(批次) != 4:
        raise ValueError("正式策略验收必须覆盖四个连续半年周期")
    期望周期 = tuple((开始.isoformat(), 结束.isoformat()) for 开始, 结束 in 窗口.周期)
    实际周期 = tuple((输入.起始日, 输入.结束日) for 输入 in 批次)
    if 实际周期 != 期望周期:
        raise ValueError("正式策略验收必须覆盖四个连续半年周期")
    for 输入 in 批次:
        核验正式策略验收单期(输入)


def 核验正式策略验收单期(输入: 实验输入) -> None:
    """校验所有正式验收共有的不可降低边界。

    四期连续性由批次入口额外校验；这里必须由单期编排入口调用，避免
    调用者绕开批次函数后把其它品种、资金或日期格式伪装为正式验收。
    """
    if not 输入.正式策略验收:
        raise ValueError("正式策略验收必须显式标记为正式策略验收")
    if 输入.交易品种 != "BTCUSDm" or 输入.合约规格 != "BTCUSDm":
        raise ValueError("正式策略验收当前仅允许 BTCUSDm")
    if 输入.初始资金 != "300":
        raise ValueError("正式策略验收初始资金必须为 300 美元")
    if 输入.建模方式 != 4:
        raise ValueError("正式策略验收必须使用 Model 4 / Real Ticks")
    try:
        开始日 = date.fromisoformat(输入.起始日)
        结束日 = date.fromisoformat(输入.结束日)
    except ValueError as 异常:
        raise ValueError("正式策略验收日期必须使用ISO格式") from 异常
    if 开始日 >= 结束日:
        raise ValueError("正式策略验收日期区间无效")
