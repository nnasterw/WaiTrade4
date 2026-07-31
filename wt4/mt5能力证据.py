from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from wt4.mt5单实例探测 import 解析MT5生命周期, 解析MT5实际测试区间, 核验MT5严格SOCKS5链路
from wt4.mt5报告 import MT5报告摘要, 报告期望, 解析MT5报告
from wt4.mt5能力 import 能力证据, 判定调度方式, 校验实例隔离, 测试实例配置
from wt4.账本 import 追加式账本


class 能力证据错误(ValueError):
    pass


@dataclass(frozen=True)
class 能力证据核验结果:
    证据: 能力证据
    调度方式: str
    来源: dict[str, str]

    @property
    def 通过(self) -> bool:
        return self.调度方式 == "两实例并行"

    def 可序列化(self) -> dict[str, Any]:
        return {"能力证据": asdict(self.证据), "调度方式": self.调度方式, "来源": self.来源, "通过": self.通过}


def 核验能力证据(重复结论: Path, 并发结论: Path, 中断结论: Path) -> 能力证据核验结果:
    """从既有真实 MT5 工件重新构造调度证据，任一不完整均拒绝并行。"""
    重复 = _读取结论(重复结论)
    并发 = _读取结论(并发结论)
    中断 = _读取结论(中断结论)
    重复通过 = _核验重复(重复, 重复结论.parent)
    并发通过 = _核验并发(并发, 并发结论.parent)
    中断通过 = _核验中断(中断, 中断结论.parent)
    证据 = 能力证据(重复通过, 重复通过, 中断通过, 并发通过, 并发通过, 并发通过)
    return 能力证据核验结果(
        证据, 判定调度方式(证据),
        {"重复结论": str(重复结论.resolve()), "并发结论": str(并发结论.resolve()), "中断结论": str(中断结论.resolve())},
    )


def _读取结论(路径: Path) -> dict[str, Any]:
    if not 路径.is_file() or 路径.is_symlink():
        raise 能力证据错误(f"结论文件不存在或不是普通文件: {路径}")
    try:
        内容 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 异常:
        raise 能力证据错误(f"结论文件无法解析: {路径}") from 异常
    if not isinstance(内容, dict):
        raise 能力证据错误(f"结论必须是对象: {路径}")
    return 内容


def _核验账本(根目录: Path, 实验标识: str, 终态: str, *, 要求已创建: bool = True) -> None:
    """结论必须同时有该实验身份的追加式账本起止事件。"""
    路径 = 根目录 / "账本.sqlite"
    try:
        事件 = 追加式账本(路径).事件(实验标识)
    except Exception as 异常:
        raise 能力证据错误(f"实验账本无法读取: {路径}") from 异常
    类型 = [事件项.类型 for 事件项 in 事件]
    if not 事件 or (要求已创建 and 类型[0] != "已创建") or 类型[-1] != 终态:
        raise 能力证据错误(f"实验账本缺少身份为 {实验标识} 的起止事件")


def _报告(路径: Path, 开始日: str, 结束日: str) -> MT5报告摘要:
    try:
        报告 = 解析MT5报告(路径, 报告期望("WaiTrade_OB", "BTCUSDm", "M1", 开始日, 结束日, Decimal("300.00")))
    except Exception as 异常:
        raise 能力证据错误(f"报告核验失败: {路径}") from 异常
    if 报告.建模方式 != "real ticks":
        raise 能力证据错误(f"报告不是 Real Ticks: {路径}")
    return 报告


def _读取严格SOCKS5配置(路径: Path) -> dict[str, str]:
    if not 路径.is_file() or 路径.is_symlink():
        raise 能力证据错误(f"MT5 探测配置不存在: {路径}")
    配置 = dict(
        行.split("=", 1) for 行 in 路径.read_text(encoding="utf-8").splitlines()
        if "=" in 行 and not 行.lstrip().startswith(";")
    )
    if 配置.get("ProxyEnable") != "1" or 配置.get("ProxyType") != "1" or not 配置.get("ProxyAddress"):
        raise 能力证据错误(f"MT5 探测配置不符合严格 SOCKS5 要求: {路径}")
    return 配置


def _确认归档报告(结论: dict[str, Any], 名称: str, 根目录: Path, 开始日: str, 结束日: str) -> MT5报告摘要:
    实验 = 结论.get(名称)
    if not isinstance(实验, dict) or not isinstance(实验.get("工件目录"), str):
        raise 能力证据错误(f"重复结论缺少{name}归档目录")
    目录 = Path(实验["工件目录"])
    if 目录.parent != 根目录 / "归档" or not 目录.is_dir() or 目录.is_symlink():
        raise 能力证据错误(f"{名称}归档目录不属于结论工件根目录")
    验收 = _读取结论(目录 / "验收结果.json")
    if 验收.get("MT5返回码") != 0 or 验收.get("MT5生命周期", {}).get("完整") is not True:
        raise 能力证据错误(f"{名称} MT5 生命周期不完整")
    配置 = _读取严格SOCKS5配置(目录 / "mt5-探测.ini")
    日志 = (目录 / "MT5日志证据.txt").read_text(encoding="utf-8")
    if 核验MT5严格SOCKS5链路(日志, 配置["ProxyAddress"]):
        raise 能力证据错误(f"{名称} 严格 SOCKS5 链路证据不完整")
    if tuple(验收.get("MT5实际测试区间", ())) != (开始日, 结束日):
        raise 能力证据错误(f"{名称}实际回测区间不符")
    return _报告(目录 / "报告.html", 开始日, 结束日)


def _核验重复(结论: dict[str, Any], 根目录: Path) -> bool:
    配置 = 结论.get("配置")
    if not isinstance(配置, dict) or 结论.get("通过") is not True or 结论.get("首次状态") != "已归档" or 结论.get("再次状态") != "已归档":
        raise 能力证据错误("重复结论状态不完整")
    开始日, 结束日 = 配置.get("开始日"), 配置.get("结束日")
    if not isinstance(开始日, str) or not isinstance(结束日, str):
        raise 能力证据错误("重复结论缺少日期")
    实验标识 = 结论.get("实验标识")
    if not isinstance(实验标识, str):
        raise 能力证据错误("重复结论缺少实验标识")
    # 父级重复能力事件只记录完成；两次子实验各自拥有已创建/已归档事件。
    _核验账本(根目录, 实验标识, "重复能力已完成", 要求已创建=False)
    首次 = _确认归档报告(结论, "首次实验", 根目录, 开始日, 结束日)
    再次 = _确认归档报告(结论, "再次实验", 根目录, 开始日, 结束日)
    for 名称 in ("首次实验", "再次实验"):
        实验身份 = 结论[名称].get("实验身份")
        if not isinstance(实验身份, str):
            raise 能力证据错误(f"重复结论缺少{name}实验身份")
        _核验账本(根目录, 实验身份, "已归档")
    if 首次 != 再次:
        raise 能力证据错误("重复报告摘要不一致")
    return True


def _实例配置(实例: dict[str, Any]) -> 测试实例配置:
    字段 = 测试实例配置.__dataclass_fields__
    try:
        return 测试实例配置(**{名称: 实例[名称] if 名称 == "名称" else Path(实例[名称]) for 名称 in 字段})
    except (KeyError, TypeError) as 异常:
        raise 能力证据错误("并发结论实例配置不完整") from 异常


def _核验并发(结论: dict[str, Any], 根目录: Path) -> bool:
    状态 = set(结论.get("串行状态", {}).values()) | set(结论.get("并行状态", {}).values())
    if 状态 != {"已归档"}:
        raise 能力证据错误("并发实验存在未归档运行")
    实验标识 = 结论.get("实验标识")
    if not isinstance(实验标识, str):
        raise 能力证据错误("并发结论缺少实验标识")
    _核验账本(根目录, 实验标识, "已完成")
    if not (结论.get("两实例逐笔一致") is True and 结论.get("并发失败率为零且有效提速") is True):
        raise 能力证据错误("并发结论未通过")
    串行秒, 并行秒 = 结论.get("串行墙钟秒"), 结论.get("并行墙钟秒")
    if not isinstance(串行秒, (int, float)) or not isinstance(并行秒, (int, float)) or 并行秒 <= 0 or 串行秒 / 并行秒 < 1.10:
        raise 能力证据错误("并发加速比未达到最低要求")
    实例 = 结论.get("实例")
    if not isinstance(实例, dict) or set(实例) != {"甲", "乙"}:
        raise 能力证据错误("并发结论缺少两套实例")
    校验实例隔离([_实例配置(实例["甲"]), _实例配置(实例["乙"])])
    基准: tuple[object, ...] | None = None
    for 阶段 in ("串行", "并行"):
        for 名称 in ("甲", "乙"):
            目录 = 根目录 / 阶段 / 名称
            配置 = _读取严格SOCKS5配置(目录 / "mt5-探测.ini")
            日志 = (目录 / "MT5日志证据.txt").read_text(encoding="utf-8")
            if 核验MT5严格SOCKS5链路(日志, 配置["ProxyAddress"]):
                raise 能力证据错误(f"并发{阶段}{名称}严格 SOCKS5 链路证据不完整")
            报告 = _报告(目录 / "报告.html", "2025.03.02", "2025.03.03")
            if 基准 is None:
                基准 = 报告.成交
            elif 报告.成交 != 基准:
                raise 能力证据错误("并发四份报告的逐笔成交不一致")
    return True


def _核验中断(结论: dict[str, Any], 根目录: Path) -> bool:
    必要真值 = ("中断无污染", "进程隔离通过", "甲被中断时仍运行", "乙生命周期完整", "运行结束无MT5Wine残留")
    if any(结论.get(字段) is not True for 字段 in 必要真值) or 结论.get("甲返回码") != -15 or 结论.get("乙返回码") != 0:
        raise 能力证据错误("中断无污染结论不完整")
    实验标识 = 结论.get("实验标识")
    if not isinstance(实验标识, str):
        raise 能力证据错误("中断结论缺少实验标识")
    _核验账本(根目录, 实验标识, "已完成")
    if tuple(结论.get("乙实际测试区间", ())) != ("2025.03.02", "2025.03.03"):
        raise 能力证据错误("中断实验乙实例区间不符")
    哈希 = 结论.get("工件哈希")
    if not isinstance(哈希, dict) or not 哈希:
        raise 能力证据错误("中断实验缺少工件哈希")
    for 相对路径, 期望哈希 in 哈希.items():
        文件 = 根目录 / 相对路径
        if not isinstance(期望哈希, str) or not 文件.is_file() or 文件.is_symlink() or sha256(文件.read_bytes()).hexdigest() != 期望哈希:
            raise 能力证据错误(f"中断工件哈希不匹配: {相对路径}")
    乙目录 = 根目录 / "乙"
    日志 = (乙目录 / "MT5日志证据.txt").read_text(encoding="utf-8")
    配置 = _读取严格SOCKS5配置(乙目录 / "mt5-探测.ini")
    if 核验MT5严格SOCKS5链路(日志, 配置["ProxyAddress"]):
        raise 能力证据错误("中断实验乙严格 SOCKS5 链路证据不完整")
    if not 解析MT5生命周期(日志).get("完整") or 解析MT5实际测试区间(日志) != ("2025.03.02", "2025.03.03"):
        raise 能力证据错误("中断实验乙生命周期或区间不完整")
    _报告(根目录 / "乙/报告.html", "2025.03.02", "2025.03.03")
    return True
