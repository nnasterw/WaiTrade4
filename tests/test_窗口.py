from __future__ import annotations

from datetime import date

from wt4.窗口 import 生成验收窗口


def test_最后完整自然月冻结24个月四个连续半年周期() -> None:
    窗口 = 生成验收窗口(date(2026, 7, 31))
    assert 窗口.周期一 == (date(2024, 7, 1), date(2024, 12, 31))
    assert 窗口.周期二 == (date(2025, 1, 1), date(2025, 6, 30))
    assert 窗口.周期三 == (date(2025, 7, 1), date(2025, 12, 31))
    assert 窗口.周期四 == (date(2026, 1, 1), date(2026, 6, 30))
    assert 窗口.周期 == (窗口.周期一, 窗口.周期二, 窗口.周期三, 窗口.周期四)


def test_跨年末日冻结仍为四段连续自然半年() -> None:
    窗口 = 生成验收窗口(date(2026, 1, 1))

    assert 窗口.周期 == (
        (date(2024, 1, 1), date(2024, 6, 30)),
        (date(2024, 7, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 6, 30)),
        (date(2025, 7, 1), date(2025, 12, 31)),
    )
