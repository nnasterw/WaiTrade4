from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from wt4.experiment import 实验输入
from wt4.编排 import 中央实验编排器, 实验状态, 执行结果
from wt4.账本 import 追加式账本


def _输入() -> 实验输入:
    return 实验输入(
        策略实现提交="abc", 二进制哈希="def", 参数={}, 数据指纹="ticks",
        成本快照="cost", 合约规格="contract", mt5版本="5", 建模方式=4,
        起始日="2024.01.01", 结束日="2024.06.30", 分区="开发",
    )


class _成功执行器:
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        报告 = 暂存目录 / "报告.txt"
        报告.write_text("mt5 evidence", encoding="utf-8")
        return 执行结果(
            实验状态.已归档,
            {报告.name: sha256(报告.read_bytes()).hexdigest()},
            {"净收益": 12, "硬门槛通过": True},
        )


class _失败执行器:
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        return 执行结果(实验状态.数据无效, {}, {"原因": "缺失真实 ticks"})


def test_成功实验原子归档并写入完整事件链(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")

    结果 = 编排器.运行(_输入(), _成功执行器())

    assert 结果.状态 is 实验状态.已归档
    assert (结果.工件目录 / "报告.txt").is_file()
    assert (结果.工件目录 / "验收结果.json").is_file()
    assert [事件.类型 for 事件 in 账本.事件(结果.实验身份)] == ["已创建", "已归档"]


def test_无效实验保留失败分类且拒绝相同身份重跑(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入()

    结果 = 编排器.运行(输入, _失败执行器())

    assert 结果.状态 is 实验状态.数据无效
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "数据无效"]
    with pytest.raises(ValueError, match="拒绝重跑"):
        编排器.运行(输入, _失败执行器())
