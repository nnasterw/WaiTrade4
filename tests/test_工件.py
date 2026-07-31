from __future__ import annotations

import hashlib

import pytest

from wt4.工件 import 归档工件


def test_校验成功才原子归档(tmp_path) -> None:
    暂存 = tmp_path / "暂存"
    暂存.mkdir()
    (暂存 / "报告.txt").write_text("完整报告", encoding="utf-8")
    哈希 = hashlib.sha256((暂存 / "报告.txt").read_bytes()).hexdigest()

    目标 = 归档工件(暂存, tmp_path / "工件", "实验-1", {"报告.txt": 哈希})

    assert (目标 / "报告.txt").read_text(encoding="utf-8") == "完整报告"
    assert not 暂存.exists()


def test_哈希不符时拒绝归档并保留暂存(tmp_path) -> None:
    暂存 = tmp_path / "暂存"
    暂存.mkdir()
    (暂存 / "报告.txt").write_text("被篡改", encoding="utf-8")

    with pytest.raises(ValueError, match="哈希不匹配"):
        归档工件(暂存, tmp_path / "工件", "实验-1", {"报告.txt": "0" * 64})

    assert 暂存.exists()


def test_拒绝清单外工件和越界路径(tmp_path) -> None:
    暂存 = tmp_path / "暂存"
    暂存.mkdir()
    (暂存 / "报告.txt").write_text("完整报告", encoding="utf-8")
    (暂存 / "未声明.txt").write_text("不应归档", encoding="utf-8")
    哈希 = hashlib.sha256((暂存 / "报告.txt").read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="清单不一致"):
        归档工件(暂存, tmp_path / "工件", "实验-1", {"报告.txt": 哈希})
    with pytest.raises(ValueError, match="暂存目录内"):
        归档工件(暂存, tmp_path / "工件", "实验-2", {"../报告.txt": 哈希})
