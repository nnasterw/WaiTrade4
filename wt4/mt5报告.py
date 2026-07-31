from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
import re


class MT5报告错误(ValueError):
    pass


@dataclass(frozen=True)
class 报告期望:
    专家: str
    品种: str
    周期: str
    开始日: str
    结束日: str
    初始资金: Decimal


@dataclass(frozen=True)
class 订单明细:
    开仓时间: str
    订单号: int
    品种: str
    类型: str
    手数: Decimal
    价格: Decimal
    止损: Decimal | None
    止盈: Decimal | None
    状态: str
    注释: str


@dataclass(frozen=True)
class MT5报告摘要:
    专家: str
    品种: str
    周期: str
    开始日: str
    结束日: str
    初始资金: Decimal
    建模方式: str
    历史质量: Decimal
    净利润: Decimal
    总交易数: int
    盈利因子: Decimal
    最大余额回撤金额: Decimal
    最大余额回撤比例: Decimal
    最大权益回撤金额: Decimal
    最大权益回撤比例: Decimal
    订单: tuple[订单明细, ...]


class _表格解析器(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.表格: list[list[list[str]]] = []
        self._当前表: list[list[str]] | None = None
        self._当前行: list[str] | None = None
        self._当前格: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self._当前表 is not None:
                raise MT5报告错误("不支持嵌套表格")
            self._当前表 = []
        elif tag == "tr" and self._当前表 is not None:
            if self._当前行 is not None:
                raise MT5报告错误("表格行嵌套")
            self._当前行 = []
        elif tag in {"td", "th"} and self._当前行 is not None:
            if self._当前格 is not None:
                raise MT5报告错误("表格单元格嵌套")
            self._当前格 = []

    def handle_data(self, data: str) -> None:
        if self._当前格 is not None:
            self._当前格.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._当前格 is not None:
            assert self._当前行 is not None
            self._当前行.append(_规范文本("".join(self._当前格)))
            self._当前格 = None
        elif tag == "tr" and self._当前行 is not None:
            assert self._当前表 is not None
            self._当前表.append(self._当前行)
            self._当前行 = None
        elif tag == "table" and self._当前表 is not None:
            if self._当前行 is not None or self._当前格 is not None:
                raise MT5报告错误("表格未闭合")
            self.表格.append(self._当前表)
            self._当前表 = None

    def close(self) -> None:
        super().close()
        if self._当前表 is not None or self._当前行 is not None or self._当前格 is not None:
            raise MT5报告错误("HTML表格未闭合")


def _规范文本(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _读取utf16le(路径: Path) -> str:
    原始 = 路径.read_bytes()
    if not 原始.startswith(b"\xff\xfe"):
        raise MT5报告错误("报告必须为带 BOM 的 UTF-16LE")
    if len(原始) % 2:
        raise MT5报告错误("UTF-16LE报告字节长度异常")
    try:
        return 原始[2:].decode("utf-16le", errors="strict")
    except UnicodeDecodeError as 异常:
        raise MT5报告错误("UTF-16LE报告解码失败") from 异常


def _唯一字段(字段: dict[str, str], 标签: str, 值: str) -> None:
    旧值 = 字段.get(标签)
    if 旧值 is not None and 旧值 != 值:
        raise MT5报告错误(f"字段重复且冲突: {标签}")
    字段[标签] = 值


def _收集字段(表格: list[list[list[str]]]) -> dict[str, str]:
    字段: dict[str, str] = {}
    for 表 in 表格:
        for 行 in 表:
            for i in range(0, len(行) - 1, 2):
                标签, 值 = 行[i], 行[i + 1]
                if 标签.endswith(":") and 值:
                    _唯一字段(字段, 标签[:-1], 值)
    return 字段


def _金额(value: str, 标签: str) -> Decimal:
    if not re.fullmatch(r"-?(?:0|[1-9]\d{0,2}(?:,\d{3})*|[1-9]\d*)(?:\.\d+)?", value):
        raise MT5报告错误(f"{标签}金额格式异常: {value}")
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as 异常:
        raise MT5报告错误(f"{标签}金额格式异常: {value}") from 异常


def _百分比(value: str, 标签: str) -> Decimal:
    if not re.fullmatch(r"(?:0|[1-9]\d{0,2})(?:\.\d+)?%", value):
        raise MT5报告错误(f"{标签}百分比格式异常: {value}")
    return Decimal(value[:-1]) / Decimal("100")


def _历史质量与建模方式(value: str) -> tuple[Decimal, str]:
    匹配 = re.fullmatch(r"((?:0|[1-9]\d{0,2})(?:\.\d+)?%) (real ticks)", value)
    if 匹配 is None:
        raise MT5报告错误(f"History Quality格式或建模方式异常: {value}")
    return _百分比(匹配.group(1), "History Quality"), 匹配.group(2)


def _回撤(value: str, 标签: str) -> tuple[Decimal, Decimal]:
    匹配 = re.fullmatch(r"(.+) \(([^()]+)\)", value)
    if 匹配 is None:
        raise MT5报告错误(f"{标签}格式异常: {value}")
    return _金额(匹配.group(1), 标签), _百分比(匹配.group(2), 标签)


def _必填(字段: dict[str, str], 标签: str) -> str:
    try:
        return 字段[标签]
    except KeyError as 异常:
        raise MT5报告错误(f"缺少必要字段: {标签}") from 异常


def _解析周期(value: str) -> tuple[str, str, str]:
    匹配 = re.fullmatch(r"([A-Z]\d+) \((\d{4}\.\d{2}\.\d{2}) - (\d{4}\.\d{2}\.\d{2})\)", value)
    if 匹配 is None:
        raise MT5报告错误(f"Period格式异常: {value}")
    周期, 开始日, 结束日 = 匹配.groups()
    for 日期 in (开始日, 结束日):
        try:
            datetime.strptime(日期, "%Y.%m.%d")
        except ValueError as 异常:
            raise MT5报告错误(f"Period日期异常: {日期}") from 异常
    if 开始日 >= 结束日:
        raise MT5报告错误("Period日期区间无效")
    return 周期, 开始日, 结束日


def _解析订单(表格: list[list[list[str]]], 期望品种: str) -> tuple[订单明细, ...]:
    表头 = ["Open Time", "Order", "Symbol", "Type", "Volume", "Price", "S / L", "T / P", "Time", "State", "Comment"]
    匹配表: list[list[str]] | None = None
    for 表 in 表格:
        for 位置, 行 in enumerate(表):
            if 行 == 表头:
                if 匹配表 is not None:
                    raise MT5报告错误("Orders表重复")
                交易行 = 表[位置 + 1:]
                for 结束位置, 候选行 in enumerate(交易行):
                    if 候选行 == ["Deals"]:
                        交易行 = 交易行[:结束位置]
                        break
                匹配表 = 交易行
    if 匹配表 is None:
        raise MT5报告错误("缺少Orders交易明细表")
    订单: list[订单明细] = []
    编号: set[int] = set()
    for 行 in 匹配表:
        if not any(行):
            continue
        if len(行) != len(表头):
            raise MT5报告错误("Orders交易行列数异常")
        时间, 订单号, 品种, 类型, 手数, 价格, 止损, 止盈, _完成时间, 状态, 注释 = 行
        try:
            datetime.strptime(时间, "%Y.%m.%d %H:%M:%S")
        except ValueError as 异常:
            raise MT5报告错误(f"Orders开仓时间异常: {时间}") from 异常
        if not re.fullmatch(r"[1-9]\d*", 订单号):
            raise MT5报告错误(f"Orders订单号异常: {订单号}")
        编号值 = int(订单号)
        if 编号值 in 编号:
            raise MT5报告错误(f"Orders订单号重复: {订单号}")
        编号.add(编号值)
        if not re.fullmatch(r"(?:buy|sell|buy limit|sell limit|buy stop|sell stop)", 类型):
            raise MT5报告错误(f"Orders类型异常: {类型}")
        手数匹配 = re.fullmatch(r"(.+) / (.+)", 手数)
        if 手数匹配 is None or _金额(手数匹配.group(1), "Orders手数") != _金额(手数匹配.group(2), "Orders手数"):
            raise MT5报告错误(f"Orders手数异常: {手数}")
        价格值 = _金额(价格, "Orders价格")
        止损值 = None if not 止损 else _金额(止损, "Orders止损")
        止盈值 = None if not 止盈 else _金额(止盈, "Orders止盈")
        if not 品种 or not 状态:
            raise MT5报告错误("Orders品种或状态为空")
        if 品种 != 期望品种:
            raise MT5报告错误(f"Orders品种异常: {品种}")
        订单.append(订单明细(时间, 编号值, 品种, 类型, _金额(手数匹配.group(1), "Orders手数"), 价格值, 止损值, 止盈值, 状态, 注释))
    return tuple(订单)


def 解析MT5报告(路径: Path, 期望: 报告期望) -> MT5报告摘要:
    解析器 = _表格解析器()
    解析器.feed(_读取utf16le(路径))
    解析器.close()
    字段 = _收集字段(解析器.表格)
    周期, 开始日, 结束日 = _解析周期(_必填(字段, "Period"))
    专家 = _必填(字段, "Expert")
    品种 = _必填(字段, "Symbol")
    初始资金 = _金额(_必填(字段, "Initial Deposit"), "Initial Deposit")
    历史质量, 建模方式 = _历史质量与建模方式(_必填(字段, "History Quality"))
    净利润 = _金额(_必填(字段, "Total Net Profit"), "Total Net Profit")
    盈利因子 = _金额(_必填(字段, "Profit Factor"), "Profit Factor")
    总交易字符串 = _必填(字段, "Total Trades")
    if not re.fullmatch(r"0|[1-9]\d*", 总交易字符串):
        raise MT5报告错误(f"Total Trades格式异常: {总交易字符串}")
    最大余额回撤金额, 最大余额回撤比例 = _回撤(_必填(字段, "Balance Drawdown Maximal"), "Balance Drawdown Maximal")
    最大权益回撤金额, 最大权益回撤比例 = _回撤(_必填(字段, "Equity Drawdown Maximal"), "Equity Drawdown Maximal")
    if (专家, 品种, 周期, 开始日, 结束日, 初始资金) != (期望.专家, 期望.品种, 期望.周期, 期望.开始日, 期望.结束日, 期望.初始资金):
        raise MT5报告错误("报告身份与实验输入不一致")
    return MT5报告摘要(专家, 品种, 周期, 开始日, 结束日, 初始资金, 建模方式, 历史质量, 净利润, int(总交易字符串), 盈利因子, 最大余额回撤金额, 最大余额回撤比例, 最大权益回撤金额, 最大权益回撤比例, _解析订单(解析器.表格, 品种))
