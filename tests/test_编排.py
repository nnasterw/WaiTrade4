from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest

from wt4.experiment import 实验输入
from wt4.编排 import 中央单实例后台队列, 中央实验编排器, 后台任务状态, 实验状态, 执行结果
from wt4.账本 import 追加式账本


def _输入(参数: dict | None = None) -> 实验输入:
    return 实验输入(
        策略实现提交="abc", 二进制哈希="def", 参数=参数 or {}, 数据指纹="ticks",
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


class _留痕执行器:
    def __init__(self, 名称: str, 顺序: list[str], 放行: Event | None = None, 失败: bool = False) -> None:
        self.名称 = 名称
        self.顺序 = 顺序
        self.放行 = 放行
        self.失败 = 失败

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        self.顺序.append(self.名称)
        if self.放行 is not None:
            assert self.放行.wait(5)
        if self.失败:
            raise RuntimeError(f"{self.名称} 故意失败")
        报告 = 暂存目录 / "报告.txt"
        报告.write_text(self.名称, encoding="utf-8")
        return 执行结果(实验状态.已归档, {报告.name: sha256(报告.read_bytes()).hexdigest()}, {})


def test_后台队列严格串行_故障不阻塞后续任务_可定向取消(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    队列 = 中央单实例后台队列(编排器)
    顺序: list[str] = []
    放行 = Event()
    甲 = 队列.提交(_输入({"任务": "甲"}), _留痕执行器("甲", 顺序, 放行))
    乙 = 队列.提交(_输入({"任务": "乙"}), _留痕执行器("乙", 顺序, 失败=True))
    丙 = 队列.提交(_输入({"任务": "丙"}), _留痕执行器("丙", 顺序))

    assert 队列.快照(甲).状态 is 后台任务状态.运行中
    assert 队列.取消(丙, "验证定向取消")
    assert not 队列.取消(甲)
    放行.set()

    assert 队列.等待(甲, 5).实验状态 is 实验状态.已归档
    乙快照 = 队列.等待(乙, 5)
    assert 乙快照.状态 is 后台任务状态.已完成
    assert "故意失败" in (乙快照.异常 or "")
    assert 队列.等待(丙, 5).状态 is 后台任务状态.已取消
    assert 顺序 == ["甲", "乙"]
    assert [事件.类型 for 事件 in 账本.事件(甲)] == ["已排队", "已创建", "已归档"]
    assert [事件.类型 for 事件 in 账本.事件(乙)] == ["已排队", "已创建", "执行无效"]
    assert [事件.类型 for 事件 in 账本.事件(丙)] == ["已排队", "已取消"]


def test_后台队列拒绝同一实验身份的重复提交(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    队列 = 中央单实例后台队列(中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件"))
    输入 = _输入({"任务": "唯一"})
    放行 = Event()
    队列.提交(输入, _留痕执行器("唯一", [], 放行))
    with pytest.raises(ValueError, match="拒绝重复提交"):
        队列.提交(输入, _成功执行器())
    放行.set()
    assert 队列.等待(输入.身份, 5).状态 is 后台任务状态.已完成
