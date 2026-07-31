from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from threading import Event

import pytest

from wt4.experiment import 实验输入
from wt4.评分 import 评分原料
from wt4.验收 import 验收输入
from wt4.风险 import 风险限额快照, 重演风险限额, 权益点, 重演逐tick日内权益风险
from wt4.mt5后台 import MT5后台进程
from wt4.编排 import (
    中央单实例后台队列,
    中央实验编排器,
    后台任务状态,
    实验状态,
    执行结果,
    运行正式策略验收批次,
)
from wt4.账本 import 追加式账本


def _输入(参数: dict | None = None) -> 实验输入:
    return 实验输入(
        策略实现提交="abc", 二进制哈希="def", 参数=参数 or {}, 数据指纹="ticks",
        成本快照="cost", 合约规格="contract", mt5版本="5", 建模方式=4,
        起始日="2024.01.01", 结束日="2024.06.30", 分区="开发",
    )


def _正式输入(开始日: str, 结束日: str, 参数: dict | None = None) -> 实验输入:
    return 实验输入(
        策略实现提交="正式策略", 二进制哈希="正式二进制", 参数=参数 or {}, 数据指纹="ticks",
        成本快照="cost", 合约规格="BTCUSDm", mt5版本="5", 建模方式=4,
        起始日=开始日, 结束日=结束日, 分区="正式验收", 正式策略验收=True,
        交易品种="BTCUSDm", 初始资金="300",
    )


def _验收输入() -> 验收输入:
    return 验收输入(
        建模方式=4, 封存净收益=Decimal("10"), 压力封存净收益=Decimal("2"),
        极端压力风险通过=True, 输入工件完整=True, 治理通过=True,
        已实现余额重演通过=True, 权益风险证据完整=True,
        报告最大权益回撤比例=Decimal("0.1"), 日初余额={"2026-01-01": Decimal("300")},
        已实现日损失={"2026-01-01": Decimal("1")},
        逐tick日内权益风险=重演逐tick日内权益风险([
            权益点("2026.01.01 00:00:00", Decimal("300"), Decimal("300")),
        ]),
        风险限额重演=重演风险限额([
            风险限额快照("2026-01-01 00:00:00", Decimal("300"), Decimal("1"), Decimal("1")),
        ]),
    )


def _评分原料() -> 评分原料:
    return 评分原料(
        样本外净收益=Decimal("10"), 压力净收益=Decimal("2"), 成本保留率=Decimal("0.5"),
        最大回撤=Decimal("0.1"), 最大单笔贡献=Decimal("0.2"),
        移除最佳月后压力期望=Decimal("1"), 月度正收益比例=Decimal("0.6"),
        证据完整=True, 订单异常数=0,
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


class _篡改输入执行器:
    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        输入.参数["风险"] = 99
        输入.参数["嵌套"]["值"].append(99)
        return 执行结果(实验状态.数据无效, {}, {"原因": "用于验证输入快照"})


class _正式成功执行器:
    def __init__(self, *, 失败: bool = False, 缺少风险证据: bool = False) -> None:
        self.失败 = 失败
        self.缺少风险证据 = 缺少风险证据
        self.执行次数 = 0

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        self.执行次数 += 1
        报告 = 暂存目录 / "报告.txt"
        报告.write_text(输入.起始日, encoding="utf-8")
        权益 = 暂存目录 / "逐tick权益.json"
        成交风险 = 暂存目录 / "成交风险.json"
        风险 = 暂存目录 / "风险限额.json"
        权益.write_text(
            '{"权益点":[{"时间":"2026.01.01 00:00:00","余额":"300","权益":"300"}]}',
            encoding="utf-8",
        )
        成交风险.write_text(
            '{"开仓风险":[{"成交号":2,"时间":"2026.01.01 00:00:00","当前权益":"300",'
            '"单笔初始风险":"1","开放初始风险":"1"}]}',
            encoding="utf-8",
        )
        风险重演 = 重演风险限额([
            风险限额快照("2026.01.01 00:00:00", Decimal("300"), Decimal("1"), Decimal("1")),
        ])
        风险.write_text(json.dumps({
            "来源": "由报告、逐tick权益与独立开仓风险工件重演",
            "源工件哈希": {
                "逐tick权益": sha256(权益.read_bytes()).hexdigest(),
                "开仓风险": sha256(成交风险.read_bytes()).hexdigest(),
            },
            "最大单笔初始风险比例": str(风险重演.最大单笔初始风险比例),
            "最大开放初始风险比例": str(风险重演.最大开放初始风险比例),
            "失败原因": list(风险重演.失败原因),
        }, ensure_ascii=False), encoding="utf-8")
        验收 = _验收输入()
        if self.失败:
            验收 = 验收.__class__(
                **{**验收.__dict__, "压力封存净收益": Decimal("-1")}
            )
        工件 = {路径.name: sha256(路径.read_bytes()).hexdigest() for 路径 in (报告, 权益, 成交风险, 风险)}
        return 执行结果(
            实验状态.已归档, 工件, {}, 验收输入=验收, 评分原料=_评分原料(),
            风险证据工件=None if self.缺少风险证据 else (权益.name, 成交风险.name, 风险.name),
        )


class _占位风险工件执行器(_正式成功执行器):
    """模拟旧实现：任意非空 JSON 被伪装成正式风险证据。"""

    def 执行(self, 输入: 实验输入, 暂存目录: Path) -> 执行结果:
        结果 = super().执行(输入, 暂存目录)
        占位 = {
            "逐tick权益.json": {"来源": "占位"},
            "成交风险.json": {"来源": "占位"},
            "风险限额.json": {"来源": "占位"},
        }
        工件 = dict(结果.工件)
        for 名称, 内容 in 占位.items():
            路径 = 暂存目录 / 名称
            路径.write_text(json.dumps(内容, ensure_ascii=False), encoding="utf-8")
            工件[名称] = sha256(路径.read_bytes()).hexdigest()
        return replace(结果, 工件=工件)


def test_成功实验原子归档并写入完整事件链(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")

    结果 = 编排器.运行(_输入(), _成功执行器())

    assert 结果.状态 is 实验状态.已归档
    assert (结果.工件目录 / "报告.txt").is_file()
    assert (结果.工件目录 / "验收结果.json").is_file()
    清单 = json.loads((结果.工件目录 / "工件清单.json").read_text(encoding="utf-8"))
    assert set(清单["工件哈希"]) == {"报告.txt", "验收结果.json"}
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


def test_执行器篡改可变参数不会改写实验身份或已创建账本输入(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"风险": 3, "嵌套": {"值": [1]}})

    结果 = 编排器.运行(输入, _篡改输入执行器())

    assert 结果.实验身份 == 输入.身份
    assert 账本.事件(输入.身份)[0].内容["输入"]["参数"] == {"风险": 3, "嵌套": {"值": [1]}}
    assert 输入.参数 == {"风险": 3, "嵌套": {"值": [1]}}


def test_启动恢复会将仅已创建且无终态的实验标为执行无效(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "异常退出后恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})

    assert 编排器.回收未终态实验(输入.身份, "后台宿主异常退出") is True
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "执行无效"]
    assert 账本.事件(输入.身份)[-1].内容 == {"原因": "后台宿主异常退出"}


def test_启动恢复不改写已有终态或仅排队实验(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    已排队 = _输入({"任务": "排队"})
    已归档 = _输入({"任务": "完成"})
    账本.追加(已排队.身份, 实验状态.已排队, {"输入": {}})
    账本.追加(已归档.身份, 实验状态.已创建, {"输入": {}})
    账本.追加(已归档.身份, 实验状态.已归档, {"工件目录": "/tmp/工件"})

    assert 编排器.回收未终态实验(已排队.身份) is False
    assert 编排器.回收未终态实验(已归档.身份) is False
    assert [事件.类型 for 事件 in 账本.事件(已排队.身份)] == ["已排队"]
    assert [事件.类型 for 事件 in 账本.事件(已归档.身份)] == ["已创建", "已归档"]


def test_受限恢复仅在归属进程组已回收后追加无效终态(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "受限恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})
    (暂存目录 / "后台-归属.json").write_text("{}", encoding="utf-8")

    assert 编排器.受限恢复遗留后台实验(输入.身份) is False
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建"]


def test_受限恢复在进程组证据通过后才追加无效终态(tmp_path, monkeypatch) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "已验证受限恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})
    归属记录 = 暂存目录 / "后台-归属.json"
    归属记录.write_text("{}", encoding="utf-8")
    已调用: list[Path] = []

    def _已回收(路径: Path) -> bool:
        已调用.append(路径)
        return True

    monkeypatch.setattr(MT5后台进程, "回收遗留自有进程组", _已回收)

    assert 编排器.受限恢复遗留后台实验(输入.身份) is True
    assert 已调用 == [归属记录]
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "执行无效"]


def test_受限恢复确认进程组已不存在后才追加无效终态(tmp_path, monkeypatch) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _输入({"任务": "已退出恢复"})
    暂存目录 = tmp_path / "暂存" / 输入.身份
    暂存目录.mkdir(parents=True)
    账本.追加(输入.身份, 实验状态.已创建, {"输入": {}})

    monkeypatch.setattr(MT5后台进程, "回收遗留自有进程组", lambda _: False)
    monkeypatch.setattr(MT5后台进程, "确认遗留自有进程组已退出", lambda _: True)

    assert 编排器.受限恢复遗留后台实验(输入.身份) is True
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "执行无效"]


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


def test_后台排队后篡改调用者输入不会分裂实验身份或账本(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    队列 = 中央单实例后台队列(编排器)
    放行 = Event()
    占用 = 队列.提交(_输入({"任务": "占用"}), _留痕执行器("占用", [], 放行))
    输入 = _输入({"风险": 3, "嵌套": {"值": [1]}})

    身份 = 队列.提交(输入, _成功执行器())
    输入.参数["风险"] = 99
    输入.参数["嵌套"]["值"].append(99)
    放行.set()

    assert 队列.等待(占用, 5).实验状态 is 实验状态.已归档
    快照 = 队列.等待(身份, 5)
    assert 快照.实验状态 is 实验状态.已归档
    assert [事件.类型 for 事件 in 账本.事件(身份)] == ["已排队", "已创建", "已归档"]
    assert 账本.事件(身份)[0].内容["输入"]["参数"] == {"风险": 3, "嵌套": {"值": [1]}}
    assert not 账本.事件(输入.身份)


def test_正式验收必须提供可独立评估的硬门与评分原料(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _成功执行器())

    assert 结果.状态 is 实验状态.治理无效
    assert [事件.类型 for 事件 in 账本.事件(输入.身份)] == ["已创建", "治理无效"]


def test_直接单期正式验收也拒绝绕开BTC与资金边界(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31", {"单期": True})
    输入 = 输入.__class__(**{**输入.__dict__, "交易品种": "ETHUSDm", "合约规格": "ETHUSDm"})

    with pytest.raises(ValueError, match="BTC"):
        编排器.运行(输入, _正式成功执行器())
    assert 账本.事件(输入.身份) == []


def test_正式验收拒绝仅由调用者布尔声明的权益风险证据(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _正式成功执行器(缺少风险证据=True))

    assert 结果.状态 is 实验状态.治理无效
    assert "封存逐tick权益" in 账本.事件(输入.身份)[-1].内容["原因"]


def test_正式验收拒绝任意JSON占位风险工件(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = _正式输入("2024-07-01", "2024-12-31")

    结果 = 编排器.运行(输入, _占位风险工件执行器())

    assert 结果.状态 is 实验状态.治理无效
    assert "封存逐tick权益" in 账本.事件(输入.身份)[-1].内容["原因"]


def test_正式四周期先冻结范围_逐期硬门通过才归档评分基线(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    窗口输入 = (
        _正式输入("2024-07-01", "2024-12-31"),
        _正式输入("2025-01-01", "2025-06-30"),
        _正式输入("2025-07-01", "2025-12-31"),
        _正式输入("2026-01-01", "2026-06-30"),
    )
    执行器 = _正式成功执行器()

    结果 = 运行正式策略验收批次(date(2026, 7, 31), 窗口输入, 编排器, (执行器,) * 4)

    assert 结果.通过
    assert 执行器.执行次数 == 4
    for 单期 in 结果.周期结果:
        assert 单期.状态 is 实验状态.已归档
        验收 = json.loads((单期.工件目录 / "验收结果.json").read_text(encoding="utf-8"))
        assert 验收["验收硬门通过"] is True
        assert 验收["评分基线"]["版本"] == 1


def test_正式批次任一期硬门失败立即停止后续周期(tmp_path) -> None:
    账本 = 追加式账本(tmp_path / "账本.sqlite")
    编排器 = 中央实验编排器(账本, tmp_path / "暂存", tmp_path / "工件")
    输入 = tuple(
        _正式输入(开始日, 结束日) for 开始日, 结束日 in (
            ("2024-07-01", "2024-12-31"), ("2025-01-01", "2025-06-30"),
            ("2025-07-01", "2025-12-31"), ("2026-01-01", "2026-06-30"),
        )
    )
    失败执行器 = _正式成功执行器(失败=True)
    未执行 = _正式成功执行器()

    结果 = 运行正式策略验收批次(date(2026, 7, 31), 输入, 编排器, (失败执行器, 未执行, 未执行, 未执行))

    assert not 结果.通过
    assert len(结果.周期结果) == 1
    assert 结果.周期结果[0].状态 is 实验状态.有效失败
    assert 未执行.执行次数 == 0
