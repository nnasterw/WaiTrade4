from __future__ import annotations

from datetime import date

from wt4.窗口 import 生成验收窗口


def test_最后完整自然月冻结24个月三分窗口() -> None:
    窗口 = 生成验收窗口(date(2026, 7, 31))
    assert 窗口.开发 == (date(2024, 7, 1), date(2025, 6, 30))
    assert 窗口.验证 == (date(2025, 7, 1), date(2025, 12, 31))
    assert 窗口.封存 == (date(2026, 1, 1), date(2026, 6, 30))
