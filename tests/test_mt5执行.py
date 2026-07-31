from __future__ import annotations

import sys

from wt4.experiment import 实验输入
from wt4.mt5执行 import MT5回测配置, 隔离MT5执行器
from wt4.编排 import 实验状态


def _输入() -> 实验输入:
    return 实验输入(
        策略实现提交="abc", 二进制哈希="def", 参数={}, 数据指纹="ticks",
        成本快照="cost", 合约规格="contract", mt5版本="5", 建模方式=4,
        起始日="2024.01.01", 结束日="2024.06.30", 分区="开发",
    )


def test_命令成功且工件齐全才能进入归档(tmp_path) -> None:
    执行器 = 隔离MT5执行器(
        MT5回测配置(
            (sys.executable, "-c", "from pathlib import Path; Path('报告.html').write_text('ok')"),
            5,
            ("报告.html",),
        )
    )

    结果 = 执行器.执行(_输入(), tmp_path)

    assert 结果.状态 is 实验状态.已归档
    assert 结果.结果["受限回收Wine服务进程号"] == []
    assert set(结果.工件) == {"执行日志.txt", "报告.html", "后台-stdout.txt", "后台-stderr.txt"}
    assert (tmp_path / "后台-stdout.txt").is_file()
    assert (tmp_path / "后台-stderr.txt").is_file()
    assert 结果.结果["后台进程"]["结束状态"] == "已退出"


def test_命令成功但缺失报告仍为执行无效(tmp_path) -> None:
    执行器 = 隔离MT5执行器(MT5回测配置((sys.executable, "-c", "pass"), 5, ("报告.html",)))

    结果 = 执行器.执行(_输入(), tmp_path)

    assert 结果.状态 is 实验状态.执行无效
    assert 结果.结果["缺失"] == ["报告.html"]


def test_超时被记录为执行无效且保存日志(tmp_path) -> None:
    执行器 = 隔离MT5执行器(
        MT5回测配置((sys.executable, "-c", "import time; time.sleep(10)"), 1, ("报告.html",))
    )

    结果 = 执行器.执行(_输入(), tmp_path)

    assert 结果.状态 is 实验状态.执行无效
    assert "执行超时" in (tmp_path / "执行日志.txt").read_text(encoding="utf-8")


def test_执行器可为专属实例传递环境变量(tmp_path) -> None:
    执行器 = 隔离MT5执行器(
        MT5回测配置(
            (sys.executable, "-c", "from pathlib import Path; import os; Path('报告.html').write_text(os.environ['WT4_TEST'])"),
            5,
            ("报告.html",),
            {"WT4_TEST": "隔离值"},
        )
    )

    结果 = 执行器.执行(_输入(), tmp_path)

    assert 结果.状态 is 实验状态.已归档
    assert (tmp_path / "报告.html").read_text(encoding="utf-8") == "隔离值"
