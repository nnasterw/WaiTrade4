from __future__ import annotations

import json
from pathlib import Path

from wt4.experiment import 实验输入
from wt4.mt5单实例探测 import 单实例MT5探测执行器
from wt4.mt5探测 import MT5短窗口探测配置
from wt4.编排 import 实验状态


def _输入() -> 实验输入:
    return 实验输入("abc", "def", {}, "ticks", "cost", "contract", "5", 4, "2026.05.01", "2026.05.02", "能力探测")


def test_探测会保留共享状态前后证据即使报告缺失(tmp_path) -> None:
    终端 = tmp_path / "MetaTrader 5 Tester"
    for 相对目录 in ("logs", "Tester/cache", "Tester/logs", "Tester/Agent-127.0.0.1-3000/logs", "reports"):
        (终端 / 相对目录).mkdir(parents=True)
    (终端 / "terminal64.exe").write_bytes(b"")
    wine = tmp_path / "wine"
    wine.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wine.chmod(0o755)
    前缀 = tmp_path / "prefix"
    前缀.mkdir()
    配置 = MT5短窗口探测配置(
        终端, r"WaiTrade\WaiTrade_OB", "WaiTrade_OB.set", "BTCUSDm", "M5",
        "2026.05.01", "2026.05.02", 300, 2000, "277656700", "Exness-MT5Trial5",
    )
    暂存 = tmp_path / "暂存"
    暂存.mkdir()

    结果 = 单实例MT5探测执行器(配置, wine, 前缀, 5).执行(_输入(), 暂存)

    assert 结果.状态 is 实验状态.执行无效
    assert (暂存 / "mt5-探测.ini").is_file()
    assert (暂存 / "共享状态-运行前.json").is_file()
    assert (暂存 / "共享状态差异.json").is_file()
    assert json.loads((暂存 / "共享状态差异.json").read_text(encoding="utf-8")) == {"删除": [], "修改": [], "新增": []}
