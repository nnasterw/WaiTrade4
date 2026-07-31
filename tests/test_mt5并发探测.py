from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import time

from wt4.mt5并发探测 import 两实例MT5并发探测器
from wt4.mt5报告 import MT5报告摘要, 成交明细
from wt4.编排 import 实验状态, 执行结果


def _报告(标识: str) -> MT5报告摘要:
    成交 = (成交明细("2026.05.01 00:00:00", 1, "", "balance", "", None, None, None, Decimal("0"), Decimal("0"), Decimal("300"), Decimal("300"), 标识),)
    return MT5报告摘要("EA", "BTCUSDm", "M1", "2026.05.01", "2026.05.02", Decimal("300"), "real ticks", Decimal("1"), Decimal("0"), 0, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), (), 成交)


def _执行器(延迟: float = 0.03, 失败: bool = False):
    def 执行(目录: Path) -> 执行结果:
        time.sleep(延迟)
        (目录 / "报告.html").write_text(目录.name, encoding="utf-8")
        return 执行结果(实验状态.执行无效 if 失败 else 实验状态.已归档, {}, {})
    return 执行


def test_并发探测只在成交逐笔一致且可观提速时通过(tmp_path: Path) -> None:
    def 解析(路径: Path) -> MT5报告摘要:
        return _报告("完全一致")

    探测器 = 两实例MT5并发探测器({"甲": _执行器(), "乙": _执行器()}, 解析, 最低加速比=1.2)
    结果 = 探测器.执行(tmp_path)

    assert 结果.两实例逐笔一致 is True
    assert 结果.并发失败率为零且有效提速 is True
    assert 结果.加速比 >= 1.2
    for 方式 in ("串行", "并行"):
        for 名称 in ("甲", "乙"):
            assert (tmp_path / 方式 / 名称 / "报告.html").is_file()


def test_成交不一致或任意失败都拒绝并发能力(tmp_path: Path) -> None:
    def 解析(路径: Path) -> MT5报告摘要:
        报告 = _报告("一致")
        return replace(报告, 成交=replace(报告.成交[0], 注释=路径.parent.parent.name))

    探测器 = 两实例MT5并发探测器({"甲": _执行器(), "乙": _执行器(失败=True)}, 解析)
    结果 = 探测器.执行(tmp_path)

    assert 结果.两实例逐笔一致 is False


def test_甲乙实例即使各自串并一致也必须互相逐笔一致(tmp_path: Path) -> None:
    def 解析(路径: Path) -> MT5报告摘要:
        return _报告(路径.parent.name)

    探测器 = 两实例MT5并发探测器({"甲": _执行器(), "乙": _执行器()}, 解析)
    结果 = 探测器.执行(tmp_path)

    assert 结果.两实例逐笔一致 is False


def test_探测器拒绝非两实例和计时噪声阈值() -> None:
    with __import__("pytest").raises(ValueError, match="甲、乙"):
        两实例MT5并发探测器({"甲": _执行器()}, lambda _: _报告("x"))
    with __import__("pytest").raises(ValueError, match="大于 1"):
        两实例MT5并发探测器({"甲": _执行器(), "乙": _执行器()}, lambda _: _报告("x"), 1.0)
