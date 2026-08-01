from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from wt4.mt5报告 import MT5报告摘要
from wt4.风险 import (
    开仓风险证据,
    权益点,
    风险限额快照,
    核验MT5开仓风险证据,
    重演MT5已实现余额,
    重演逐tick日内权益风险,
    重演风险限额,
)
from wt4.验收 import 从MT5报告构造验收输入, 验收输入


class 正式验收工件错误(ValueError):
    pass


def _小数(value: object, 名称: str) -> Decimal:
    if isinstance(value, bool):
        raise 正式验收工件错误(f"{名称}必须是十进制数")
    try:
        结果 = Decimal(str(value))
    except (InvalidOperation, ValueError) as 异常:
        raise 正式验收工件错误(f"{名称}必须是十进制数") from 异常
    if not 结果.is_finite():
        raise 正式验收工件错误(f"{名称}必须是有限十进制数")
    return 结果


def _列表(内容: object, 名称: str) -> list[dict[str, Any]]:
    if not isinstance(内容, list) or not all(isinstance(项, dict) for 项 in 内容):
        raise 正式验收工件错误(f"{名称}必须是对象列表")
    return 内容


def _时间(value: object, 名称: str) -> datetime:
    if not isinstance(value, str):
        raise 正式验收工件错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS或YYYY.MM.DD HH:MM:SS.fff")
    try:
        格式 = "%Y.%m.%d %H:%M:%S.%f" if "." in value[11:] else "%Y.%m.%d %H:%M:%S"
        结果 = datetime.strptime(value, 格式)
    except ValueError as 异常:
        raise 正式验收工件错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS或YYYY.MM.DD HH:MM:SS.fff") from 异常
    # 保持字典序与时间序一致；权益审计允许毫秒，以免同一服务器秒内的
    # 多个 tick 被丢弃。
    标准 = 结果.strftime("%Y.%m.%d %H:%M:%S")
    if "." in value[11:]:
        小数 = value.rsplit(".", 1)[1]
        if len(小数) != 3 or not 小数.isdigit() or 标准 + "." + 小数 != value:
            raise 正式验收工件错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS.fff")
    elif 标准 != value:
        raise 正式验收工件错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS")
    return 结果


def 读取逐tick权益工件(路径: Path) -> list[权益点]:
    try:
        内容 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 异常:
        raise 正式验收工件错误("逐tick权益工件不是有效JSON") from 异常
    项目 = _列表(内容.get("权益点") if isinstance(内容, dict) else None, "权益点")
    if not 项目:
        raise 正式验收工件错误("逐tick权益工件不能为空")
    结果: list[权益点] = []
    上一时间: datetime | None = None
    for 项 in 项目:
        时间 = 项.get("时间")
        解析时间 = _时间(时间, "逐tick权益时间")
        if 上一时间 is not None and 解析时间 <= 上一时间:
            raise 正式验收工件错误("逐tick权益时间必须严格递增")
        余额, 权益 = _小数(项.get("余额"), "余额"), _小数(项.get("权益"), "权益")
        if 余额 <= 0 or 权益 <= 0:
            raise 正式验收工件错误("逐tick权益和余额必须为正")
        结果.append(权益点(时间, 余额, 权益))
        上一时间 = 解析时间
    return 结果


def 读取开仓风险工件(路径: Path) -> list[开仓风险证据]:
    try:
        内容 = json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as 异常:
        raise 正式验收工件错误("成交风险工件不是有效JSON") from 异常
    项目 = _列表(内容.get("开仓风险") if isinstance(内容, dict) else None, "开仓风险")
    结果: list[开仓风险证据] = []
    for 项 in 项目:
        成交号, 时间 = 项.get("成交号"), 项.get("时间")
        if not isinstance(成交号, int) or isinstance(成交号, bool) or 成交号 <= 0:
            raise 正式验收工件错误("开仓风险成交号或时间无效")
        _时间(时间, "开仓风险时间")
        当前权益 = _小数(项.get("当前权益"), "当前权益")
        单笔初始风险 = _小数(项.get("单笔初始风险"), "单笔初始风险")
        开放初始风险 = _小数(项.get("开放初始风险"), "开放初始风险")
        if 当前权益 <= 0 or 单笔初始风险 < 0 or 开放初始风险 < 0:
            raise 正式验收工件错误("开仓风险金额或权益无效")
        结果.append(开仓风险证据(成交号, 时间, 风险限额快照(
            时间, 当前权益, 单笔初始风险, 开放初始风险,
        )))
    return 结果


def 构造正式验收风险工件(
    *,
    报告: MT5报告摘要,
    报告路径: Path,
    逐tick权益路径: Path,
    成交风险路径: Path,
    压力封存净收益: Decimal,
    极端压力风险通过: bool,
    输入工件完整: bool,
    治理通过: bool,
) -> tuple[dict[str, object], 验收输入]:
    """从真实报告及两类独立原始工件构造不可伪造的验收输入。

    风险限额工件由这里独立重演生成，避免执行器以布尔字段或调用者
    拼装内容替代真实风险事实。
    """
    权益 = 读取逐tick权益工件(逐tick权益路径)
    开仓风险 = 读取开仓风险工件(成交风险路径)
    成交重演 = 核验MT5开仓风险证据(报告, 开仓风险, 权益)
    # 证据为空时仍写入结构化失败工件，令编排层能够保留可审计的
    # `有效失败`，而不是因空列表异常把真实报告误标成执行故障。
    风险重演 = 重演风险限额([项.快照 for 项 in 开仓风险]) if 开仓风险 else None
    逐tick重演 = 重演逐tick日内权益风险(权益)
    验收输入 = 从MT5报告构造验收输入(
        报告,
        声明建模方式=4,
        压力封存净收益=压力封存净收益,
        极端压力风险通过=极端压力风险通过,
        输入工件完整=输入工件完整,
        治理通过=治理通过,
        已实现余额重演=重演MT5已实现余额(报告),
        成交风险重演=成交重演,
        逐tick权益证据完整=True,
        逐tick日内权益风险=逐tick重演,
        风险限额重演=风险重演,
    )
    风险限额内容 = {
        "来源": "由报告、逐tick权益与独立开仓风险工件重演",
        "源工件哈希": {
            "MT5报告": sha256(报告路径.read_bytes()).hexdigest(),
            "逐tick权益": sha256(逐tick权益路径.read_bytes()).hexdigest(),
            "开仓风险": sha256(成交风险路径.read_bytes()).hexdigest(),
        },
        "最大单笔初始风险比例": str(风险重演.最大单笔初始风险比例) if 风险重演 else None,
        "最大开放初始风险比例": str(风险重演.最大开放初始风险比例) if 风险重演 else None,
        "失败原因": list(风险重演.失败原因) if 风险重演 else ["没有开仓风险证据"],
    }
    return 风险限额内容, 验收输入


def 完成正式验收风险桥接(
    *,
    报告: MT5报告摘要,
    报告路径: Path,
    逐tick权益路径: Path,
    成交风险路径: Path,
    风险限额路径: Path,
    压力封存净收益: Decimal,
    极端压力风险通过: bool,
    输入工件完整: bool,
    治理通过: bool,
) -> 验收输入:
    """生成第三份结构化风险工件，并返回同一来源构造的验收输入。"""
    内容, 验收输入 = 构造正式验收风险工件(
        报告=报告,
        报告路径=报告路径,
        逐tick权益路径=逐tick权益路径,
        成交风险路径=成交风险路径,
        压力封存净收益=压力封存净收益,
        极端压力风险通过=极端压力风险通过,
        输入工件完整=输入工件完整,
        治理通过=治理通过,
    )
    写入风险限额工件(风险限额路径, 内容)
    return 验收输入


def 写入风险限额工件(路径: Path, 内容: dict[str, object]) -> str:
    if 路径.exists():
        raise 正式验收工件错误("风险限额工件已存在，拒绝覆盖")
    路径.write_text(json.dumps(内容, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return sha256(路径.read_bytes()).hexdigest()
