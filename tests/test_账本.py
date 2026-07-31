from __future__ import annotations

import sqlite3

import pytest

from wt4.账本 import 追加式账本


def test_账本只允许追加事件(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    账本.追加("实验-1", "已创建", {"来源": "测试"})

    assert [事件.类型 for 事件 in 账本.事件("实验-1")] == ["已创建"]
    with sqlite3.connect(tmp_path / "账本.sqlite") as 数据库:
        with pytest.raises(sqlite3.DatabaseError):
            数据库.execute("UPDATE 事件 SET 类型 = '篡改'")
