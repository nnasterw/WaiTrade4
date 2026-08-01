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
from wt4.mt5单实例探测 import 单实例MT5探测执行器
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.正式验收工件 import 完成正式验收风险桥接
from wt4.策略实现 import (
    BTC候选策略目录,
    BTC候选实际二进制,
    BTC候选策略,
    BTC候选策略部署,
    MT5候选策略编译配置,
    受控编译BTC候选策略,
    生成BTC正式运行参数,
    部署BTC候选策略,
    读取BTC候选策略,
)
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
    # 场景运行器必须返回目标隔离终端内受控编译产生的 EX5 哈希。
    # 正式输入中的二进制哈希只在这里得到实际加载证据，不能由调用方自报。
    实际二进制哈希: str | None = None
    # 底层 MT5 运行会产生启动配置、代理配置、日志等证据；正式执行器必须
    # 原样声明它们，不能只拿走报告后在归档前留下未声明文件。
    工件: dict[str, str] | None = None


class 正式场景运行器(Protocol):
    def 运行(
        self,
        场景: str,
        输入: 实验输入,
        暂存目录: Path,
        参数路径: Path,
        审计目录: Path,
    ) -> 正式场景结果: ...


@dataclass(frozen=True)
class 正式MT5场景运行配置:
    """真实正式场景使用的专属 Wine/MT5 终端。

    Prefix 必须在本仓库的 ``runtime`` 下，避免正式运行误写进日常使用的
    MT5 安装。网络边界仍交由 ``单实例MT5探测执行器`` 的 sandbox-exec
    强制执行；此配置不提供 HTTP 或直连回退字段。
    """

    Wine命令: Path
    Wine前缀: Path
    终端目录: Path
    登录账号: str
    服务器: str
    超时秒数: int
    杠杆: int = 2000
    代理地址: str = "127.0.0.1:7897"
    Mihomo日志路径: Path | None = None


class 真实MT5正式场景运行器:
    """以受限单实例链路运行一个正式 BTC M5 场景。

    它不编造报告或 EX5 身份：报告只能由底层 MT5 执行器从本轮唯一输出
    收集，EX5 哈希只读取目标隔离终端实际存在的普通文件。编译和冻结输入
    的时序仍由批次准备层负责，防止在已冻结实验身份后静默替换二进制。
    """

    def __init__(self, 配置: 正式MT5场景运行配置) -> None:
        self.配置 = 配置
        工作区 = Path(__file__).resolve().parent.parent
        runtime根目录 = (工作区 / "runtime").resolve()
        前缀 = 配置.Wine前缀.resolve()
        终端 = 配置.终端目录.resolve()
        if not 配置.Wine命令.is_file() or not 前缀.is_dir() or not 终端.is_dir():
            raise ValueError("正式 MT5 的 Wine、前缀或终端目录无效")
        try:
            前缀.relative_to(runtime根目录)
            终端.relative_to(前缀 / "drive_c")
        except ValueError as 异常:
            raise ValueError("正式 MT5 Wine Prefix 必须位于本仓库 runtime 且终端在其 drive_c 内") from 异常
        if 配置.超时秒数 <= 0 or not 配置.登录账号 or not 配置.服务器:
            raise ValueError("正式 MT5 登录信息或超时无效")
        if 配置.杠杆 <= 0 or 配置.代理地址 != "127.0.0.1:7897":
            raise ValueError("正式 MT5 仅允许显式的 127.0.0.1:7897 SOCKS5 代理")

    def 运行(
        self,
        场景: str,
        输入: 实验输入,
        暂存目录: Path,
        参数路径: Path,
        审计目录: Path,
    ) -> 正式场景结果:
        if 场景 not in _场景报告名:
            raise ValueError(f"未知正式场景: {场景}")
        if not 参数路径.is_file() or 参数路径.is_symlink() or 参数路径.parent.resolve() != 暂存目录.resolve():
            raise ValueError("正式场景参数必须是本轮暂存目录中的普通文件")
        if not (self.配置.终端目录 / "terminal64.exe").is_file():
            raise ValueError("正式 MT5 terminal64.exe 不存在")
        实际二进制 = self.配置.终端目录 / "MQL5/Experts/WaiTrade4/BTC订单块分层风控.ex5"
        if not 实际二进制.is_file() or 实际二进制.is_symlink():
            raise ValueError("正式场景缺少受控编译的实际 EX5")
        运行前二进制哈希 = sha256(实际二进制.read_bytes()).hexdigest()
        期望审计目录 = self.配置.终端目录 / "MQL5/Files/wt4/audit" / 审计目录.name
        if 审计目录.resolve() != 期望审计目录.resolve():
            raise ValueError("正式场景审计目录必须属于目标隔离终端")

        场景工作目录 = 暂存目录 / f"{场景}-mt5运行"
        if 场景工作目录.exists() or 场景工作目录.is_symlink():
            raise ValueError("正式 MT5 场景工作目录已存在")
        场景工作目录.mkdir()
        场景参数路径 = 场景工作目录 / 参数路径.name
        场景参数路径.write_bytes(参数路径.read_bytes())
        探测配置 = MT5短窗口探测配置(
            终端目录=self.配置.终端目录, 专家顾问=_专家顾问,
            参数文件=场景参数路径.name, 品种="BTCUSDm", 周期="M5",
            开始日=输入.起始日.replace("-", "."), 结束日=输入.结束日.replace("-", "."),
            初始资金=300, 杠杆=self.配置.杠杆, 登录账号=self.配置.登录账号,
            服务器=self.配置.服务器, 代理地址=self.配置.代理地址, 参数文件路径=场景参数路径,
        )
        结果 = 单实例MT5探测执行器(
            探测配置, self.配置.Wine命令, self.配置.Wine前缀, self.配置.超时秒数,
            self.配置.Mihomo日志路径, 启动配置路径模式="前缀内C盘",
            报告封存名称=_场景报告名[场景],
        ).执行(输入, 场景工作目录)
        if 结果.状态 is not 实验状态.已归档:
            raise ValueError(f"正式 MT5 场景未归档: {结果.结果.get('原因', 结果.状态)}")
        来源报告 = 场景工作目录 / _场景报告名[场景]
        目标报告 = 暂存目录 / _场景报告名[场景]
        if not 来源报告.is_file() or 来源报告.is_symlink():
            raise ValueError("正式 MT5 场景缺少唯一报告")
        if 目标报告.exists():
            raise ValueError("正式场景报告封存目标已存在")
        运行后二进制哈希 = sha256(实际二进制.read_bytes()).hexdigest()
        if 运行后二进制哈希 != 运行前二进制哈希:
            raise ValueError("正式 MT5 场景运行期间 EX5 二进制发生变化")
        目标报告.write_bytes(来源报告.read_bytes())
        场景工件 = {
            f"{场景工作目录.name}/{名称}": 哈希
            for 名称, 哈希 in 结果.工件.items()
            if 名称 != _场景报告名[场景]
        }
        场景工件[f"{场景工作目录.name}/{场景参数路径.name}"] = sha256(场景参数路径.read_bytes()).hexdigest()
        来源报告.unlink()
        场景工件[_场景报告名[场景]] = sha256(目标报告.read_bytes()).hexdigest()
        return 正式场景结果(
            报告路径=目标报告,
            审计目录=审计目录 if 审计目录.is_dir() and not 审计目录.is_symlink() else None,
            实际二进制哈希=运行前二进制哈希,
            工件=场景工件,
        )


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
            参数组 = {
                场景: 生成BTC正式运行参数(
                    候选, 暂存目录 / f"正式运行参数-{场景}.set", self._场景审计标识(输入.身份, 场景)
                )
                for 场景 in _场景报告名
            }
            审计目录组 = {
                场景: self.配置.审计根目录 / 参数.审计运行标识
                for 场景, 参数 in 参数组.items()
            }
            if any(目录.exists() for 目录 in 审计目录组.values()):
                raise ValueError("正式场景审计目录已存在，拒绝复用")

            场景结果 = {
                场景: self.场景运行器.运行(场景, 输入, 暂存目录, 参数组[场景].运行路径, 审计目录组[场景])
                for 场景 in _场景报告名
            }
            实际二进制哈希 = {结果.实际二进制哈希 for 结果 in 场景结果.values()}
            if None in 实际二进制哈希 or 实际二进制哈希 != {输入.二进制哈希}:
                return self._无效(实验状态.治理无效, "正式场景实际加载二进制哈希与冻结实验输入不一致")
            报告 = {场景: self._核验报告(输入, 场景, 结果.报告路径, 暂存目录) for 场景, 结果 in 场景结果.items()}
            报告哈希 = {场景: sha256(结果.报告路径.read_bytes()).hexdigest() for 场景, 结果 in 场景结果.items()}
            if len(set(报告哈希.values())) != len(报告哈希):
                return self._无效(实验状态.治理无效, "正式三场景报告内容重复，拒绝复用样本外证据")

            样本外审计目录 = 场景结果["样本外"].审计目录
            if 样本外审计目录 is None or 样本外审计目录.resolve() != 审计目录组["样本外"].resolve():
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
                *(参数.运行路径 for 参数 in 参数组.values()),
                *(结果.报告路径 for 结果 in 场景结果.values()),
                暂存目录 / "审计原件/equity.csv", 暂存目录 / "审计原件/opening_risk.csv",
                权益, 风险, 风险限额,
            ]
            工件 = {str(路径.relative_to(暂存目录)): sha256(路径.read_bytes()).hexdigest() for 路径 in 工件路径}
            for 场景, 场景结果项 in 场景结果.items():
                if 场景结果项.工件 is None:
                    continue
                for 名称, 哈希 in 场景结果项.工件.items():
                    if 名称 in 工件 and 工件[名称] != 哈希:
                        raise ValueError(f"{场景}场景工件哈希与正式清单冲突: {名称}")
                    工件[名称] = 哈希
            return 执行结果(
                状态=实验状态.已归档, 工件=工件,
                结果={
                    "代理前置探测": 代理探测, "冻结来源标识": 候选.冻结来源标识,
                    "正式运行参数哈希": {场景: 参数.运行哈希 for 场景, 参数 in 参数组.items()},
                    "实际加载二进制哈希": 输入.二进制哈希,
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
    def _场景审计标识(实验身份: str, 场景: str) -> str:
        if 场景 not in _场景报告名:
            raise ValueError(f"未知正式场景: {场景}")
        return sha256(f"{实验身份}:{场景}".encode("utf-8")).hexdigest()

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
