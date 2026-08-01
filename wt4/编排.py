from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
from collections import deque
from threading import Condition, Thread
from typing import Protocol

from wt4.experiment import 实验输入, 核验正式策略验收单期, 核验正式策略验收批次
from wt4.工件 import 归档工件
from wt4.账本 import 追加式账本
from wt4.评分 import 评分原料, 从正式MT5工件构造评分原料
from wt4.正式验收工件 import (
    构造正式验收风险工件,
    读取开仓风险工件,
    读取逐tick权益工件,
)
from wt4.mt5报告 import 报告期望, 解析MT5报告
from wt4.验收 import 验收输入, 评估硬门槛
from wt4.风险 import 重演逐tick日内权益风险, 重演风险限额
from wt4.窗口 import 生成验收窗口


class 实验状态(StrEnum):
    已排队 = "已排队"
    已取消 = "已取消"
    已创建 = "已创建"
    已归档 = "已归档"
    有效失败 = "有效失败"
    执行无效 = "执行无效"
    数据无效 = "数据无效"
    治理无效 = "治理无效"
    # 反事实能力实验的正向结论：它证明了某项边界，而非一场可用于
    # 策略验收的成功回测。必须单列，避免把预期的无报告结果混入
    # "执行无效"，也绝不能误标为"已归档"。
    能力边界已验证 = "能力边界已验证"


@dataclass(frozen=True)
class 执行结果:
    状态: 实验状态
    工件: dict[str, str]
    结果: dict[str, object]
    验收输入: 验收输入 | None = None
    # 正式验收评分必须从三份已封存 MT5 报告重演，不接受调用者自报数值。
    评分证据工件: tuple[str, str] | None = None
    风险证据工件: tuple[str, str, str] | None = None
    # 正式验收必须把原始 UTF-16LE MT5 报告作为已哈希工件声明；
    # 周期和专家由执行器明确声明，其他身份字段只能从冻结实验输入推导。
    报告工件: tuple[str, str, str] | None = None


class MT5执行器(Protocol):
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果: ...


@dataclass(frozen=True)
class 编排结果:
    实验身份: str
    状态: 实验状态
    工件目录: Path | None


@dataclass(frozen=True)
class 正式策略验收批次结果:
    窗口截至日: date
    周期结果: tuple[编排结果, ...]
    失败原因: tuple[str, ...]

    @property
    def 通过(self) -> bool:
        return len(self.周期结果) == 4 and not self.失败原因 and all(结果.状态 is 实验状态.已归档 for 结果 in self.周期结果)


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
        from wt4.mt5后台 import MT5后台进程, 独占实验执行锁

        归属记录 = self.暂存根目录 / 实验身份 / "后台-归属.json"
        # 若原编排器仍持锁，说明它仍能写入同一份账本和工件；此时绝不能
        # 把其运行中的 MT5 误判为遗留进程。宿主死亡时内核会自动释放锁，
        # 后继恢复者才会继续执行下方的归属验证和回收。
        with 独占实验执行锁(归属记录.parent, 非阻塞=True) as 已接管:
            if not 已接管:
                return False
            已受限回收 = MT5后台进程.回收遗留自有进程组(归属记录)
            已确认退出 = (
                not 已受限回收
                and MT5后台进程.确认遗留自有进程组已退出(归属记录)
            )
            if not (已受限回收 or 已确认退出):
                return False
            原因 = (
                "后台宿主提前退出，已受限回收本轮进程组"
                if 已受限回收
                else "后台宿主提前退出，已确认本轮进程组退出"
            )
            return self.回收未终态实验(实验身份, 原因)

    def 运行(self, 输入: 实验输入, 执行器: MT5执行器, *, 允许已排队: bool = False) -> 编排结果:
        # 在执行器获得对象之前冻结规范内容。frozen dataclass 不能冻结其中的
        # dict/list；执行器即使改写其副本，也不能改变身份或已创建账本证据。
        输入快照 = json.loads(输入.规范内容())
        冻结输入 = 实验输入(**输入快照)
        身份 = 冻结输入.身份
        if 冻结输入.正式策略验收:
            核验正式策略验收单期(冻结输入)
        已有事件 = self.账本.事件(身份)
        if 已有事件 and not (允许已排队 and [事件.类型 for 事件 in 已有事件] == [实验状态.已排队]):
            raise ValueError(f"实验身份已存在，拒绝重跑: {身份}")
        暂存目录 = self.暂存根目录 / 身份
        if 暂存目录.exists() or (self.工件根目录 / 身份).exists():
            raise ValueError(f"实验目录已存在，拒绝覆盖: {身份}")

        暂存目录.mkdir(parents=True)
        self.账本.追加(身份, 实验状态.已创建, {"输入": 输入快照})
        from wt4.mt5后台 import 独占实验执行锁

        # 覆盖执行、工件归档和账本终态的整个临界区，防止外部恢复流程与
        # 正常宿主并发写入第二个终态。
        with 独占实验执行锁(暂存目录) as 已获得锁:
            assert 已获得锁
            try:
                执行结果 = 执行器.执行(冻结输入, 暂存目录)
                执行结果 = self._核验正式验收结果(冻结输入, 执行结果, 暂存目录)
                if 执行结果.状态 not in {
                    实验状态.已归档,
                    实验状态.能力边界已验证,
                    实验状态.有效失败,
                    实验状态.执行无效,
                    实验状态.数据无效,
                    实验状态.治理无效,
                }:
                    raise ValueError(f"不支持的实验终态: {执行结果.状态}")

                if 执行结果.状态 not in {实验状态.已归档, 实验状态.能力边界已验证}:
                    self.账本.追加(身份, 执行结果.状态, 执行结果.结果)
                    return 编排结果(身份, 执行结果.状态, None)

                预期哈希 = self._写入验收结果(暂存目录, 执行结果)
                工件目录 = 归档工件(暂存目录, self.工件根目录, 身份, 预期哈希)
                工件哈希 = dict(预期哈希)
                工件哈希["工件清单.json"] = sha256((工件目录 / "工件清单.json").read_bytes()).hexdigest()
                self.账本.追加(身份, 执行结果.状态, {"工件目录": str(工件目录), "工件哈希": 工件哈希, **执行结果.结果})
                return 编排结果(身份, 执行结果.状态, 工件目录)
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

    @staticmethod
    def _核验正式验收结果(输入: 实验输入, 结果: 执行结果, 暂存目录: Path) -> 执行结果:
        if not 输入.正式策略验收:
            return 结果
        # 能力边界实验不是正式策略验收的可接受产物。即使某个执行器
        # 误把它返回给正式输入，也必须阻断其归档，防止后续流程把
        # 反事实的无报告结论当作正式周期证据。
        if 结果.状态 is 实验状态.能力边界已验证:
            return 执行结果(
                实验状态.治理无效,
                {},
                {**结果.结果, "原因": "正式策略验收不得使用能力边界实验结果"},
            )
        if 结果.状态 is not 实验状态.已归档:
            return 结果
        if 结果.验收输入 is None or 结果.评分证据工件 is None:
            return 执行结果(
                实验状态.治理无效, {}, {**结果.结果, "原因": "正式策略验收缺少独立硬门或评分证据"},
            )
        if not 结果.验收输入.权益风险证据完整 or not _核验封存风险证据工件(输入, 结果, 暂存目录):
            return 执行结果(
                实验状态.治理无效, {}, {**结果.结果, "原因": "正式策略验收缺少封存逐tick权益与风险快照工件"},
            )
        硬门 = 评估硬门槛(结果.验收输入)
        if not 硬门.通过:
            return 执行结果(
                实验状态.有效失败, {}, {**结果.结果, "原因": "正式策略验收硬门未通过", "验收硬门失败原因": 硬门.失败原因},
            )
        try:
            评分原料 = _从封存评分证据构造原料(输入, 结果, 暂存目录)
        except (ValueError, ArithmeticError) as 异常:
            return 执行结果(
                实验状态.治理无效, {}, {**结果.结果, "原因": f"正式策略验收评分证据无效: {异常}"},
            )
        if 评分原料.压力净收益 != 结果.验收输入.压力封存净收益:
            return 执行结果(
                实验状态.治理无效, {}, {**结果.结果, "原因": "评分压力报告与验收压力净收益不一致"},
            )
        验收结果 = {
            **结果.结果,
            "验收硬门通过": True,
            "评分基线": {
                "版本": 1,
                "验收硬门通过": True,
                "原料": _序列化评分原料(评分原料),
            },
        }
        return replace(结果, 结果=验收结果)


def _从封存评分证据构造原料(输入: 实验输入, 结果: 执行结果, 暂存目录: Path) -> 评分原料:
    评分声明 = 结果.评分证据工件
    报告声明 = 结果.报告工件
    风险声明 = 结果.风险证据工件
    if (
        评分声明 is None
        or 报告声明 is None
        or 风险声明 is None
        or len(set(评分声明)) != 2
        or 报告声明[0] in 评分声明
    ):
        raise ValueError("评分报告声明不完整")
    报告名称, 专家, 周期 = 报告声明
    权益名称 = 风险声明[0]

    def 读取报告(名称: str):
        相对路径 = Path(名称)
        路径 = 暂存目录 / 相对路径
        if 相对路径.is_absolute() or ".." in 相对路径.parts or not 路径.is_file() or 路径.is_symlink():
            raise ValueError("评分报告路径无效")
        if 结果.工件.get(名称) != sha256(路径.read_bytes()).hexdigest():
            raise ValueError("评分报告未被工件清单哈希")
        return 解析MT5报告(路径, 报告期望(
            专家, 输入.交易品种 or "", 周期,
            输入.起始日.replace("-", "."), 输入.结束日.replace("-", "."),
            Decimal(输入.初始资金 or "0"),
        ))

    样本外 = 读取报告(报告名称)
    压力 = 读取报告(评分声明[0])
    无摩擦 = 读取报告(评分声明[1])
    权益路径 = 暂存目录 / 权益名称
    if not 权益路径.is_file() or 结果.工件.get(权益名称) != sha256(权益路径.read_bytes()).hexdigest():
        raise ValueError("评分逐tick权益工件无效")
    return 从正式MT5工件构造评分原料(样本外, 压力, 无摩擦, 逐tick权益工件=权益路径)


def _序列化评分原料(原料: 评分原料) -> dict[str, object]:
    return {名称: str(值) if isinstance(值, Decimal) else 值 for 名称, 值 in asdict(原料).items()}


def _核验封存风险证据工件(输入: 实验输入, 结果: 执行结果, 暂存目录: Path) -> bool:
    """正式验收不能将调用者布尔字段当作逐 tick 风险证据。

    执行器必须明确声明逐 tick 权益、独立成交风险、风险限额三份结构化工件，并把
    它们放入本次不可变工件哈希清单；后续真实 MT5 执行器再负责从报告链
    解析、重演并构造 ``验收输入``。
    """
    名称 = 结果.风险证据工件
    if 名称 is None or len(名称) != 3 or len(set(名称)) != 3:
        return False
    内容组: dict[str, tuple[Path, dict[str, object]]] = {}
    for 相对路径 in 名称:
        路径 = Path(相对路径)
        文件 = 暂存目录 / 路径
        if (
            路径.is_absolute()
            or ".." in 路径.parts
            or not 文件.is_file()
            or 文件.is_symlink()
            or 结果.工件.get(相对路径) != sha256(文件.read_bytes()).hexdigest()
        ):
            return False
        try:
            内容 = json.loads(文件.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(内容, dict) or not 内容:
            return False
        内容组[相对路径] = (文件, 内容)

    权益项 = [(路径, 内容) for 路径, 内容 in 内容组.values() if "权益点" in 内容]
    风险项 = [(路径, 内容) for 路径, 内容 in 内容组.values() if "开仓风险" in 内容]
    限额项 = [(路径, 内容) for 路径, 内容 in 内容组.values() if "源工件哈希" in 内容]
    if len(权益项) != 1 or len(风险项) != 1 or len(限额项) != 1:
        return False
    权益路径, _ = 权益项[0]
    风险路径, _ = 风险项[0]
    _, 限额内容 = 限额项[0]
    报告声明 = 结果.报告工件
    if (
        报告声明 is None
        or len(报告声明) != 3
        or not all(isinstance(项, str) and 项 for 项 in 报告声明)
    ):
        return False
    报告名称, 专家, 周期 = 报告声明
    报告相对路径 = Path(报告名称)
    报告路径 = 暂存目录 / 报告相对路径
    if (
        报告相对路径.is_absolute()
        or ".." in 报告相对路径.parts
        or not 报告路径.is_file()
        or 报告路径.is_symlink()
        or 结果.工件.get(报告名称) != sha256(报告路径.read_bytes()).hexdigest()
    ):
        return False
    if 限额内容.get("来源") != "由报告、逐tick权益与独立开仓风险工件重演":
        return False
    源哈希 = 限额内容.get("源工件哈希")
    if not isinstance(源哈希, dict) or 源哈希 != {
        "MT5报告": sha256(报告路径.read_bytes()).hexdigest(),
        "逐tick权益": sha256(权益路径.read_bytes()).hexdigest(),
        "开仓风险": sha256(风险路径.read_bytes()).hexdigest(),
    }:
        return False
    try:
        报告 = 解析MT5报告(
            报告路径,
            报告期望(
                专家, 输入.交易品种 or "", 周期,
                输入.起始日.replace("-", "."), 输入.结束日.replace("-", "."),
                Decimal(输入.初始资金 or "0"),
            ),
        )
        if 报告.建模方式 != "real ticks":
            return False
        权益 = 读取逐tick权益工件(权益路径)
        开仓风险 = 读取开仓风险工件(风险路径)
        逐tick重演 = 重演逐tick日内权益风险(权益)
        风险重演 = 重演风险限额([项.快照 for 项 in 开仓风险])
        _, 报告验收输入 = 构造正式验收风险工件(
            报告=报告,
            报告路径=报告路径,
            逐tick权益路径=权益路径,
            成交风险路径=风险路径,
            压力封存净收益=结果.验收输入.压力封存净收益,
            极端压力风险通过=结果.验收输入.极端压力风险通过,
            输入工件完整=结果.验收输入.输入工件完整,
            治理通过=结果.验收输入.治理通过,
        )
    except (ValueError, ArithmeticError):
        return False
    验收 = 结果.验收输入
    if (
        验收 is None
        or 验收.逐tick日内权益风险 != 逐tick重演
        or 验收.风险限额重演 != 风险重演
        or 验收 != 报告验收输入
    ):
        return False
    if (
        限额内容.get("最大单笔初始风险比例") != str(风险重演.最大单笔初始风险比例)
        or 限额内容.get("最大开放初始风险比例") != str(风险重演.最大开放初始风险比例)
        or 限额内容.get("失败原因") != list(风险重演.失败原因)
    ):
        return False
    return True


def 运行正式策略验收批次(
    截至日: date,
    批次: tuple[实验输入, ...],
    编排器: 中央实验编排器,
    执行器: tuple[MT5执行器, ...],
) -> 正式策略验收批次结果:
    """按冻结的四个半年周期串行运行正式 BTC 策略验收。

    任一期无效或硬门失败即停止，既不伪造完整批次，也不允许后续周期
    以独立成功冒充批次通过。评分标尺仍需另行汇集至少五份真实归档基线。
    """
    窗口 = 生成验收窗口(截至日)
    核验正式策略验收批次(批次, 窗口)
    if len(执行器) != 4:
        raise ValueError("正式策略验收必须提供四个周期执行器")
    周期结果: list[编排结果] = []
    失败原因: list[str] = []
    for 输入, 单期执行器 in zip(批次, 执行器, strict=True):
        结果 = 编排器.运行(输入, 单期执行器)
        周期结果.append(结果)
        if 结果.状态 is not 实验状态.已归档:
            失败原因.append(f"{输入.起始日}至{输入.结束日}: {结果.状态}")
            break
    return 正式策略验收批次结果(截至日, tuple(周期结果), tuple(失败原因))


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
        # 排队期间调用方仍可能持有并改写嵌套参数；必须在写入排队账本、
        # 生成队列键和保存任务前使用同一份冻结快照。
        输入快照 = json.loads(输入.规范内容())
        冻结输入 = 实验输入(**输入快照)
        身份 = 冻结输入.身份
        with self._条件:
            if 身份 in self._任务 or self._编排器.账本.事件(身份):
                raise ValueError(f"实验身份已存在，拒绝重复提交: {身份}")
            if (self._编排器.暂存根目录 / 身份).exists() or (self._编排器.工件根目录 / 身份).exists():
                raise ValueError(f"实验目录已存在，拒绝覆盖: {身份}")
            self._编排器.账本.追加(身份, 实验状态.已排队, {"输入": 输入快照})
            self._任务[身份] = _后台任务(冻结输入, 执行器)
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
