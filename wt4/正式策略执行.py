from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import shutil
from typing import Callable, Protocol

from wt4.experiment import 实验输入, 核验正式策略验收单期
from wt4.mt5报告 import 报告期望, 解析MT5报告
from wt4.mt5审计 import 转换MT5审计CSV
from wt4.mt5单实例探测 import 通过SOCKS5探测TLS端点
from wt4.正式验收工件 import 完成正式验收风险桥接
from wt4.策略实现 import BTC候选策略目录, 生成BTC正式运行参数, 读取BTC候选策略
from wt4.编排 import 实验状态, 执行结果


_专家顾问 = r"WaiTrade4\BTC订单块分层风控"
_场景报告名 = {"样本外": "报告.html", "压力": "压力报告.html", "无摩擦": "无摩擦报告.html"}


@dataclass(frozen=True)
class BTC正式单期配置:
    """正式单期的网络前置与审计根目录。

    代理地址是显式配置而非固定端口；TLS 前置失败时本执行器不会调用
    场景运行器，因而不存在直连降级路径。实际 MT5 的部署、编译和启动
    由隔离场景运行器实现，且必须在其内部继续保持禁止直连沙箱。
    """

    代理地址: str
    代理TLS端点: tuple[str, int]
    审计根目录: Path
    候选策略目录: Path = BTC候选策略目录


@dataclass(frozen=True)
class 正式场景结果:
    报告路径: Path
    审计目录: Path | None = None
    极端压力风险通过: bool = False


class 正式场景运行器(Protocol):
    def 运行(
        self,
        场景: str,
        输入: 实验输入,
        暂存目录: Path,
        参数路径: Path,
        审计目录: Path,
    ) -> 正式场景结果: ...


代理前置核验器 = Callable[[str, str, int], dict[str, object]]


class 正式BTC单期执行器:
    """将三种真实 MT5 场景收敛成一份可由中央编排器复核的单期结果。

    此类不允许调用方直接填验收数值。净收益、评分原料和风险限额均从
    三份 MT5 报告与 EA 写出的 CSV 原件重新解析/重演。
    """

    def __init__(
        self,
        配置: BTC正式单期配置,
        场景运行器: 正式场景运行器,
        代理前置核验: 代理前置核验器 = 通过SOCKS5探测TLS端点,
    ) -> None:
        self.配置 = 配置
        self.场景运行器 = 场景运行器
        self.代理前置核验 = 代理前置核验

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        try:
            核验正式策略验收单期(输入)
        except ValueError as 异常:
            return self._无效(实验状态.治理无效, str(异常))

        主机, 端口 = self.配置.代理TLS端点
        try:
            代理探测 = self.代理前置核验(self.配置.代理地址, 主机, 端口)
        except (OSError, ValueError) as 异常:
            return self._无效(实验状态.执行无效, f"代理前置核验异常: {异常}")
        if 代理探测.get("通过") is not True:
            return self._无效(实验状态.执行无效, f"代理前置核验失败: {代理探测}")

        try:
            if not 暂存目录.is_dir() or 暂存目录.is_symlink():
                raise ValueError("正式暂存目录不存在或不是普通目录")
            候选 = 读取BTC候选策略(self.配置.候选策略目录)
            参数 = 生成BTC正式运行参数(候选, 暂存目录 / "正式运行参数.set", 输入.身份)
            审计目录 = self.配置.审计根目录 / 输入.身份
            if 审计目录.exists():
                raise ValueError("正式审计目录已存在，拒绝复用")

            场景结果 = {
                场景: self.场景运行器.运行(场景, 输入, 暂存目录, 参数.运行路径, 审计目录)
                for 场景 in _场景报告名
            }
            报告 = {场景: self._核验报告(输入, 场景, 结果.报告路径, 暂存目录) for 场景, 结果 in 场景结果.items()}
            报告哈希 = {场景: sha256(结果.报告路径.read_bytes()).hexdigest() for 场景, 结果 in 场景结果.items()}
            if len(set(报告哈希.values())) != len(报告哈希):
                return self._无效(实验状态.治理无效, "正式三场景报告内容重复，拒绝复用样本外证据")

            样本外审计目录 = 场景结果["样本外"].审计目录
            if 样本外审计目录 is None or 样本外审计目录.resolve() != 审计目录.resolve():
                raise ValueError("样本外审计目录未绑定本次实验身份")
            权益, 风险 = self._封存审计原件(样本外审计目录, 暂存目录)
            风险限额 = 暂存目录 / "风险限额.json"
            验收输入 = 完成正式验收风险桥接(
                报告=报告["样本外"], 报告路径=场景结果["样本外"].报告路径,
                逐tick权益路径=权益, 成交风险路径=风险, 风险限额路径=风险限额,
                压力封存净收益=报告["压力"].净利润,
                极端压力风险通过=场景结果["压力"].极端压力风险通过,
                输入工件完整=True, 治理通过=True,
            )
            工件路径 = [
                参数.运行路径,
                *(结果.报告路径 for 结果 in 场景结果.values()),
                暂存目录 / "审计原件/equity.csv", 暂存目录 / "审计原件/opening_risk.csv",
                权益, 风险, 风险限额,
            ]
            工件 = {str(路径.relative_to(暂存目录)): sha256(路径.read_bytes()).hexdigest() for 路径 in 工件路径}
            return 执行结果(
                状态=实验状态.已归档, 工件=工件,
                结果={
                    "代理前置探测": 代理探测, "冻结来源标识": 候选.冻结来源标识,
                    "正式运行参数哈希": 参数.运行哈希,
                },
                验收输入=验收输入,
                评分证据工件=("压力报告.html", "无摩擦报告.html"),
                风险证据工件=("逐tick权益.json", "开仓风险.json", "风险限额.json"),
                报告工件=("报告.html", _专家顾问, "M5"),
            )
        except (OSError, ValueError, ArithmeticError) as 异常:
            return self._无效(实验状态.执行无效, f"正式策略执行失败: {异常}")

    @staticmethod
    def _无效(状态: 实验状态, 原因: str) -> 执行结果:
        return 执行结果(状态=状态, 工件={}, 结果={"原因": 原因})

    @staticmethod
    def _核验报告(输入: 实验输入, 场景: str, 路径: Path, 暂存目录: Path):
        期望路径 = 暂存目录 / _场景报告名[场景]
        if 路径.resolve() != 期望路径.resolve() or not 路径.is_file() or 路径.is_symlink():
            raise ValueError(f"{场景}报告路径无效或未写入本轮暂存目录")
        return 解析MT5报告(路径, 报告期望(
            _专家顾问, "BTCUSDm", "M5",
            输入.起始日.replace("-", "."), 输入.结束日.replace("-", "."), Decimal("300"),
        ))

    @staticmethod
    def _封存审计原件(来源目录: Path, 暂存目录: Path) -> tuple[Path, Path]:
        if not 来源目录.is_dir() or 来源目录.is_symlink():
            raise ValueError("样本外审计目录无效")
        原件目录 = 暂存目录 / "审计原件"
        if 原件目录.exists():
            raise ValueError("审计原件目录已存在，拒绝覆盖")
        原件目录.mkdir()
        for 名称 in ("equity.csv", "opening_risk.csv"):
            来源, 目标 = 来源目录 / 名称, 原件目录 / 名称
            if not 来源.is_file() or 来源.is_symlink():
                raise ValueError(f"缺少或拒绝链接的样本外审计原件: {名称}")
            shutil.copyfile(来源, 目标)
        权益, 风险 = 暂存目录 / "逐tick权益.json", 暂存目录 / "开仓风险.json"
        转换MT5审计CSV(原件目录 / "equity.csv", 原件目录 / "opening_risk.csv", 权益, 风险)
        return 权益, 风险
