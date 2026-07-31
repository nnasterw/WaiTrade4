from __future__ import annotations

import os
from pathlib import Path
import sys

from wt4.mt5中断探测 import 两实例中断探测器
from wt4.mt5后台 import MT5后台进程


def _启动(目录: Path, 秒数: float) -> MT5后台进程:
    目录.mkdir(parents=True, exist_ok=True)
    return MT5后台进程.启动(
        (sys.executable, "-c", f"import time; time.sleep({秒数})"), 目录, dict(os.environ), 目录
    )


def test_仅中断甲的进程组且乙仍独立完成(tmp_path: Path) -> None:
    结果 = 两实例中断探测器(
        lambda: _启动(tmp_path / "甲", 30),
        lambda: _启动(tmp_path / "乙", 0.5),
    ).执行(0.2, 5)

    assert 结果.被中断已退出 is True
    assert 结果.被中断时仍运行 is True
    assert 结果.未中断完成 is True
    assert 结果.通过 is True


def test_参数必须为正(tmp_path: Path) -> None:
    探测器 = 两实例中断探测器(lambda: _启动(tmp_path / "甲", 1), lambda: _启动(tmp_path / "乙", 1))
    try:
        探测器.执行(0, 1)
    except ValueError as 异常:
        assert "必须为正" in str(异常)
    else:
        raise AssertionError("应拒绝无效参数")
