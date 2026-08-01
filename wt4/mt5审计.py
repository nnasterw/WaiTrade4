from __future__ import annotations

"""将受控 EA 写入的 UTF-8 CSV 审计原件封存为正式验收 JSON 工件。

EA 只能写入 MT5 Tester 的 ``MQL5/Files`` 沙盒；本模块在执行器已将
原件复制到本轮暂存目录后转换。转换只做格式收紧与封存，不推导浮动
权益、止损或风险金额。
"""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path


class MT5审计错误(ValueError):
    pass


_权益表头 = ("time", "balance", "equity")
_风险表头 = ("deal_id", "time", "equity", "initial_risk", "open_initial_risk")


def 转换MT5审计CSV(
    权益原始路径: Path,
    开仓风险原始路径: Path,
    逐tick权益路径: Path,
    开仓风险路径: Path,
) -> None:
    """一次性封存两类 EA 审计工件，拒绝覆盖和任何格式宽松解析。"""
    if 逐tick权益路径.exists() or 开仓风险路径.exists():
        raise MT5审计错误("正式审计工件已存在，拒绝覆盖")
    权益 = _读取权益(权益原始路径)
    风险 = _读取风险(开仓风险原始路径)
    _原子写入JSON(逐tick权益路径, {"权益点": 权益})
    try:
        _原子写入JSON(开仓风险路径, {"开仓风险": 风险})
    except Exception:
        逐tick权益路径.unlink(missing_ok=True)
        raise


def _读取CSV(路径: Path, 期望表头: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with 路径.open("r", encoding="utf-8-sig", newline="") as 文件:
            读取器 = csv.DictReader(文件)
            if tuple(读取器.fieldnames or ()) != 期望表头:
                raise MT5审计错误(f"审计CSV表头不匹配: {路径.name}")
            行 = list(读取器)
    except (OSError, UnicodeDecodeError, csv.Error) as 异常:
        raise MT5审计错误(f"审计CSV不可读取: {路径}") from 异常
    for 行号, 项 in enumerate(行, start=2):
        if None in 项 or any(值 is None or 值 == "" for 值 in 项.values()):
            raise MT5审计错误(f"审计CSV第{行号}行字段不完整")
    return 行


def _读取权益(路径: Path) -> list[dict[str, str]]:
    结果: list[dict[str, str]] = []
    上一时间: datetime | None = None
    for 行号, 项 in enumerate(_读取CSV(路径, _权益表头), start=2):
        时间 = _毫秒时间(项["time"], f"权益CSV第{行号}行时间")
        if 上一时间 is not None and 时间 <= 上一时间:
            raise MT5审计错误("逐tick权益时间必须严格递增")
        余额 = _金额(项["balance"], f"权益CSV第{行号}行余额")
        权益 = _金额(项["equity"], f"权益CSV第{行号}行权益")
        if 余额 <= 0 or 权益 <= 0:
            raise MT5审计错误(f"权益CSV第{行号}行余额或权益非正")
        结果.append({"时间": 项["time"], "余额": str(余额), "权益": str(权益)})
        上一时间 = 时间
    if not 结果:
        raise MT5审计错误("逐tick权益审计不能为空")
    return 结果


def _读取风险(路径: Path) -> list[dict[str, str | int]]:
    结果: list[dict[str, str | int]] = []
    已见成交: set[int] = set()
    for 行号, 项 in enumerate(_读取CSV(路径, _风险表头), start=2):
        try:
            成交号 = int(项["deal_id"])
        except ValueError as 异常:
            raise MT5审计错误(f"风险CSV第{行号}行成交号无效") from 异常
        if 成交号 <= 0 or str(成交号) != 项["deal_id"] or 成交号 in 已见成交:
            raise MT5审计错误(f"风险CSV第{行号}行成交号重复或无效")
        _服务器秒时间(项["time"], f"风险CSV第{行号}行时间")
        当前权益 = _金额(项["equity"], f"风险CSV第{行号}行当前权益")
        单笔 = _金额(项["initial_risk"], f"风险CSV第{行号}行单笔初始风险")
        开放 = _金额(项["open_initial_risk"], f"风险CSV第{行号}行开放初始风险")
        if 当前权益 <= 0 or 单笔 <= 0 or 开放 < 单笔:
            raise MT5审计错误(f"风险CSV第{行号}行风险金额无效")
        结果.append({"成交号": 成交号, "时间": 项["time"], "当前权益": str(当前权益), "单笔初始风险": str(单笔), "开放初始风险": str(开放)})
        已见成交.add(成交号)
    return 结果


def _金额(文本: str, 名称: str) -> Decimal:
    try:
        数值 = Decimal(文本)
    except InvalidOperation as 异常:
        raise MT5审计错误(f"{名称}不是十进制金额") from 异常
    if not 数值.is_finite():
        raise MT5审计错误(f"{名称}不是有限金额")
    return 数值


def _服务器秒时间(文本: str, 名称: str) -> datetime:
    try:
        时间 = datetime.strptime(文本, "%Y.%m.%d %H:%M:%S")
    except ValueError as 异常:
        raise MT5审计错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS") from 异常
    if 时间.strftime("%Y.%m.%d %H:%M:%S") != 文本:
        raise MT5审计错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS")
    return 时间


def _毫秒时间(文本: str, 名称: str) -> datetime:
    try:
        时间 = datetime.strptime(文本, "%Y.%m.%d %H:%M:%S.%f")
    except ValueError as 异常:
        raise MT5审计错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS.fff") from 异常
    秒, 小数 = 文本.rsplit(".", 1) if "." in 文本 else ("", "")
    if len(小数) != 3 or not 小数.isdigit() or 时间.strftime("%Y.%m.%d %H:%M:%S") != 秒:
        raise MT5审计错误(f"{名称}必须为YYYY.MM.DD HH:MM:SS.fff")
    return 时间


def _原子写入JSON(路径: Path, 内容: dict[str, object]) -> None:
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时 = 路径.with_name(f".{路径.name}.tmp")
    if 临时.exists():
        raise MT5审计错误(f"审计工件临时路径已存在: {临时.name}")
    try:
        临时.write_text(json.dumps(内容, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        临时.replace(路径)
    finally:
        临时.unlink(missing_ok=True)
