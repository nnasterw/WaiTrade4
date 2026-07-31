from __future__ import annotations

from wt4.迁移 import 冻结迁移, 收集最小依赖闭包


def test_冻结迁移仅复制入口和实际include依赖(tmp_path) -> None:
    旧根 = tmp_path / "旧/mql5"
    (旧根 / "Experts/WaiTrade2").mkdir(parents=True)
    (旧根 / "Include/WaiTrade2").mkdir(parents=True)
    (旧根 / "Experts/WaiTrade2/策略.mq5").write_text('#include <WaiTrade2/甲.mqh>\n', encoding="utf-8")
    (旧根 / "Include/WaiTrade2/甲.mqh").write_text('#include <WaiTrade2/乙.mqh>\n', encoding="utf-8")
    (旧根 / "Include/WaiTrade2/乙.mqh").write_text('// end\n', encoding="utf-8")
    (旧根 / "Include/WaiTrade2/无关.mqh").write_text('// ignore\n', encoding="utf-8")
    参数 = tmp_path / "策略.set"
    参数.write_text('风险=2.7\n', encoding="utf-8")

    依赖 = 收集最小依赖闭包(旧根, __import__('pathlib').Path('Experts/WaiTrade2/策略.mq5'))
    结果 = 冻结迁移(旧根, __import__('pathlib').Path('Experts/WaiTrade2/策略.mq5'), 参数, tmp_path / "冻结", "WaiTrade2:v11")

    assert len(依赖) == 3
    assert (tmp_path / "冻结/Include/WaiTrade2/无关.mqh").exists() is False
    assert (tmp_path / "冻结/来源.json").exists()
    assert len(结果.文件哈希) == 4

import json


def test_来源清单包含入口和原始参数路径(tmp_path) -> None:
    旧根 = tmp_path / "旧/mql5"
    (旧根 / "Experts/WaiTrade2").mkdir(parents=True)
    (旧根 / "Experts/WaiTrade2/策略.mq5").write_text('// entry\n', encoding="utf-8")
    参数 = tmp_path / "策略.set"
    参数.write_text('风险=2.7\n', encoding="utf-8")

    冻结迁移(旧根, __import__('pathlib').Path('Experts/WaiTrade2/策略.mq5'), 参数, tmp_path / "冻结", "WaiTrade2:commit:v11")

    清单 = json.loads((tmp_path / "冻结/来源.json").read_text(encoding="utf-8"))
    assert 清单["入口相对路径"] == "Experts/WaiTrade2/策略.mq5"
    assert 清单["参数原始路径"] == str(参数)
