from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from wt4.账本 import 追加式账本
from wt4.正式验收工件 import 读取逐tick权益工件
from wt4.mt5报告 import MT5报告摘要
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


def 从正式MT5工件构造评分原料(
    样本外报告: MT5报告摘要,
    压力报告: MT5报告摘要,
    无摩擦报告: MT5报告摘要,
    *,
    逐tick权益工件: Path,
) -> 评分原料:
    """只从已解析的三份同口径 MT5 报告和逐 tick 工件推导评分事实。

    样本外、压力、无摩擦三个情景必须拥有相同的交易身份；缺少任一
    原始报告时拒绝评分，而不是由执行器填入一个未验证的 Decimal。
    """
    _核验评分报告同口径(样本外报告, 压力报告, "压力")
    _核验评分报告同口径(样本外报告, 无摩擦报告, "无摩擦")
    权益 = 读取逐tick权益工件(逐tick权益工件)
    if not 权益:
        raise ValueError("评分缺少逐tick权益证据")
    月度收益 = _按月已实现净收益(样本外报告)
    压力月度收益 = _按月已实现净收益(压力报告)
    if not 月度收益 or not 压力月度收益:
        raise ValueError("评分报告缺少可聚合的已实现成交")
    if 无摩擦报告.净利润 <= 0:
        raise ValueError("无摩擦报告净收益必须为正")
    压力去最佳月 = list(压力月度收益.values())
    if len(压力去最佳月) < 2:
        raise ValueError("压力报告至少需要两个月的已实现收益")
    压力去最佳月.remove(max(压力去最佳月))
    正收益月数 = sum(收益 > 0 for 收益 in 月度收益.values())
    已平仓贡献 = _已平仓净贡献(样本外报告)
    正贡献总额 = sum((值 for 值 in 已平仓贡献 if 值 > 0), Decimal("0"))
    if 正贡献总额 <= 0:
        raise ValueError("样本外报告没有正向已平仓贡献")
    return 评分原料(
        样本外净收益=样本外报告.净利润,
        压力净收益=压力报告.净利润,
        成本保留率=样本外报告.净利润 / 无摩擦报告.净利润,
        最大回撤=样本外报告.最大权益回撤比例,
        最大单笔贡献=max(已平仓贡献) / 正贡献总额,
        移除最佳月后压力期望=sum(压力去最佳月, Decimal("0")) / Decimal(len(压力去最佳月)),
        月度正收益比例=Decimal(正收益月数) / Decimal(len(月度收益)),
        证据完整=True,
        订单异常数=0,
    )


def _核验评分报告同口径(基准: MT5报告摘要, 候选: MT5报告摘要, 名称: str) -> None:
    if 基准.建模方式 != "real ticks":
        raise ValueError("样本外评分报告并非real ticks")
    字段 = ("专家", "品种", "周期", "开始日", "结束日", "初始资金", "建模方式")
    if any(getattr(基准, 字段名) != getattr(候选, 字段名) for 字段名 in 字段):
        raise ValueError(f"{名称}评分报告与样本外报告身份不一致")
    if 候选.建模方式 != "real ticks":
        raise ValueError(f"{名称}评分报告并非real ticks")


def _按月已实现净收益(报告: MT5报告摘要) -> dict[str, Decimal]:
    月度: dict[str, Decimal] = {}
    for 成交 in 报告.成交:
        if 成交.类型 == "balance":
            continue
        月份 = datetime.strptime(成交.时间, "%Y.%m.%d %H:%M:%S").strftime("%Y-%m")
        月度[月份] = 月度.get(月份, Decimal("0")) + 成交.佣金 + 成交.隔夜利息 + 成交.盈亏
    return 月度


def _已平仓净贡献(报告: MT5报告摘要) -> list[Decimal]:
    """以 MT5 out deal 为不可再分的已实现平仓贡献，费用一并计入。"""
    贡献 = [
        成交.佣金 + 成交.隔夜利息 + 成交.盈亏
        for 成交 in 报告.成交
        if 成交.方向 == "out"
    ]
    if not 贡献:
        raise ValueError("评分报告缺少已平仓成交")
    return 贡献


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
    退化指标: tuple[str, ...] = ()


def 从已归档实验构造基线样本(
    账本: 追加式账本,
    工件根目录: Path,
    实验身份: str,
) -> 基线样本:
    """从不可变账本与封存工件读取一个可用于校准的正式验收基线。

    校准入口不接受调用者临时拼装的原料；必须能从账本的已创建输入、
    已归档事件、工件清单和验收结果逐一回溯。这样即使真实代表性池尚未
    跑完，也不会把内存样本误当成生产标尺的来源。
    """
    if not 实验身份:
        raise ValueError("基线实验身份不能为空")
    事件 = 账本.事件(实验身份)
    if len(事件) < 2 or 事件[0].类型 != "已创建" or 事件[-1].类型 != "已归档":
        raise ValueError("评分基线必须具有已创建和已归档账本终态")
    输入 = 事件[0].内容.get("输入")
    if not isinstance(输入, dict):
        raise ValueError("评分基线缺少不可变实验输入")
    计算身份 = sha256(
        json.dumps(输入, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if 计算身份 != 实验身份:
        raise ValueError("评分基线账本输入与实验身份不一致")
    if not (
        输入.get("正式策略验收") is True
        and 输入.get("交易品种") == "BTCUSDm"
        and 输入.get("合约规格") == "BTCUSDm"
        and 输入.get("初始资金") == "300"
        and 输入.get("建模方式") == 4
    ):
        raise ValueError("评分基线必须来自 BTCUSDm 正式策略验收")

    工件目录 = (工件根目录 / 实验身份).resolve()
    if 工件目录.parent != 工件根目录.resolve() or not 工件目录.is_dir():
        raise ValueError("评分基线归档目录不存在或越界")
    已归档目录 = 事件[-1].内容.get("工件目录")
    if 已归档目录 != str(工件目录):
        raise ValueError("账本归档目录与评分基线工件目录不一致")

    清单文件 = 工件目录 / "工件清单.json"
    验收文件 = 工件目录 / "验收结果.json"
    if not 清单文件.is_file() or not 验收文件.is_file():
        raise ValueError("评分基线缺少工件清单或验收结果")
    try:
        清单 = json.loads(清单文件.read_text(encoding="utf-8"))
        验收结果 = json.loads(验收文件.read_text(encoding="utf-8"))
    except json.JSONDecodeError as 异常:
        raise ValueError("评分基线工件不是有效 JSON") from 异常
    哈希 = 清单.get("工件哈希") if isinstance(清单, dict) else None
    账本哈希 = 事件[-1].内容.get("工件哈希")
    清单哈希 = sha256(清单文件.read_bytes()).hexdigest()
    if (
        not isinstance(哈希, dict)
        or not isinstance(账本哈希, dict)
        or 账本哈希.get("工件清单.json") != 清单哈希
        or {名称: 值 for 名称, 值 in 账本哈希.items() if 名称 != "工件清单.json"} != 哈希
    ):
        raise ValueError("评分基线工件清单与账本哈希不一致")
    声明路径: set[Path] = set()
    for 名称, 期望哈希 in 哈希.items():
        相对路径 = Path(名称) if isinstance(名称, str) else None
        if (
            相对路径 is None
            or 相对路径.is_absolute()
            or ".." in 相对路径.parts
            or not isinstance(期望哈希, str)
        ):
            raise ValueError("评分基线工件哈希格式无效")
        路径 = 工件目录 / 相对路径
        if not 路径.is_file() or 路径.is_symlink():
            raise ValueError("评分基线工件清单包含越界或缺失文件")
        if sha256(路径.read_bytes()).hexdigest() != 期望哈希:
            raise ValueError("评分基线工件哈希不匹配")
        声明路径.add(相对路径)
    实际路径 = {路径.relative_to(工件目录) for 路径 in 工件目录.rglob("*") if 路径.is_file()}
    if 实际路径 != 声明路径 | {Path("工件清单.json")}:
        raise ValueError("评分基线工件与清单不一致")

    基线 = 验收结果.get("评分基线") if isinstance(验收结果, dict) else None
    原料内容 = 基线.get("原料") if isinstance(基线, dict) else None
    if not isinstance(基线, dict) or 基线.get("版本") != 1 or not isinstance(原料内容, dict):
        raise ValueError("评分基线缺少版本化评分原料")
    if 基线.get("验收硬门通过") is not True:
        raise ValueError("评分基线验收硬门未通过")
    try:
        原料 = 评分原料(
            样本外净收益=Decimal(str(原料内容["样本外净收益"])),
            压力净收益=Decimal(str(原料内容["压力净收益"])),
            成本保留率=Decimal(str(原料内容["成本保留率"])),
            最大回撤=Decimal(str(原料内容["最大回撤"])),
            最大单笔贡献=Decimal(str(原料内容["最大单笔贡献"])),
            移除最佳月后压力期望=Decimal(str(原料内容["移除最佳月后压力期望"])),
            月度正收益比例=Decimal(str(原料内容["月度正收益比例"])),
            证据完整=原料内容["证据完整"],
            订单异常数=原料内容["订单异常数"],
        )
    except (KeyError, ArithmeticError, ValueError) as 异常:
        raise ValueError("评分基线原料格式无效") from 异常
    if not isinstance(原料.证据完整, bool) or not isinstance(原料.订单异常数, int) or isinstance(原料.订单异常数, bool):
        raise ValueError("评分基线证据或订单异常字段无效")
    return 基线样本(实验身份, 原料, 硬门槛结果([]))


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
    退化指标: list[str] = []
    for 指标名, 属性名, _ in _评分指标:
        值 = sorted(getattr(样本.原料, 属性名) for 样本 in 已排序基线池)
        低分界 = 值[(len(值) - 1) // 3]
        高分界 = 值[(len(值) - 1) * 2 // 3]
        三档分界[指标名] = (低分界, 高分界)
        # 两个分界重合时，数值阈值无法形成低、中、高三个可区分的档位。
        # 保留该标尺的全部来源以供审计，但禁止将其当作有效三分制评分。
        if 低分界 == 高分界:
            退化指标.append(指标名)
    规范内容 = json.dumps(
        {
            "基线身份": 身份,
            "三档分界": {名称: [str(值) for 值 in 分界] for 名称, 分界 in 三档分界.items()},
            "退化指标": 退化指标,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return 评分标尺(身份, sha256(规范内容.encode()).hexdigest(), 三档分界, tuple(退化指标))


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
    if 标尺.退化指标:
        限制.append(f"评分标尺三档退化: {','.join(标尺.退化指标)}")
        指标["评分标尺身份"] = 标尺.标尺身份
        指标["评分标尺退化指标"] = list(标尺.退化指标)
        return 评分卡(指标, None, "观察", 限制)
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
