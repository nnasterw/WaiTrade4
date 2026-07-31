from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from wt4.mt5报告 import MT5报告摘要
from wt4.风险 import 已实现余额重演结果, 权益点


@dataclass(frozen=True)
class 验收输入:
    建模方式: int
    封存净收益: Decimal
    压力封存净收益: Decimal
    极端压力风险通过: bool
    输入工件完整: bool
    治理通过: bool
    已实现余额重演通过: bool = False
    权益风险证据完整: bool = False


@dataclass(frozen=True)
class 硬门槛结果:
    失败原因: list[str]

    @property
    def 通过(self) -> bool:
        return not self.失败原因


def 从MT5报告构造验收输入(
    报告: MT5报告摘要,
    *,
    声明建模方式: int,
    压力封存净收益: Decimal,
    极端压力风险通过: bool,
    输入工件完整: bool,
    治理通过: bool,
    已实现余额重演: 已实现余额重演结果 | None = None,
    权益风险证据完整: bool = False,
) -> 验收输入:
    """把已严格解析且身份已核验的报告转为验收所需事实。

    ``声明建模方式`` 来自不可变实验输入；报告内的 real ticks 文案只作为
    独立交叉核验，不能替代实验身份中的 Model=4。
    """
    if 报告.建模方式 != "real ticks":
        raise ValueError("MT5报告并非real ticks")
    return 验收输入(
        建模方式=声明建模方式,
        封存净收益=报告.净利润,
        压力封存净收益=压力封存净收益,
        极端压力风险通过=极端压力风险通过,
        输入工件完整=输入工件完整,
        治理通过=治理通过,
        已实现余额重演通过=已实现余额重演 is not None and 已实现余额重演.通过,
        权益风险证据完整=权益风险证据完整,
    )


def 评估硬门槛(输入: 验收输入) -> 硬门槛结果:
    失败原因: list[str] = []
    if 输入.建模方式 != 4:
        失败原因.append("必须使用Model 4 / Real Ticks")
    if 输入.封存净收益 <= 0:
        失败原因.append("封存样本外为非正")
    if 输入.压力封存净收益 <= 0:
        失败原因.append("压力封存样本外为非正")
    if not 输入.极端压力风险通过:
        失败原因.append("极端压力突破风险红线")
    if not 输入.输入工件完整:
        失败原因.append("输入或工件不完整")
    if not 输入.治理通过:
        失败原因.append("治理审计未通过")
    if not 输入.已实现余额重演通过:
        失败原因.append("Deals已实现余额独立重演未通过")
    if not 输入.权益风险证据完整:
        失败原因.append("逐tick权益与开放风险证据不完整")
    return 硬门槛结果(失败原因)

def 核验风险证据(EA权益快照: list[权益点], 独立重演权益: list[权益点], 允许权益偏差: Decimal) -> list[str]:
    if len(EA权益快照) != len(独立重演权益):
        return ["EA权益快照与独立重演长度不一致"]
    for EA点, 重演点 in zip(EA权益快照, 独立重演权益, strict=True):
        if EA点.时间 != 重演点.时间 or abs(EA点.权益 - 重演点.权益) > 允许权益偏差:
            return ["EA权益快照与独立重演不一致"]
    return []
