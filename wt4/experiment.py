from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


@dataclass(frozen=True)
class 实验输入:
    策略实现提交: str
    二进制哈希: str
    参数: dict[str, Any]
    数据指纹: str
    成本快照: str
    合约规格: str
    mt5版本: str
    建模方式: int
    起始日: str
    结束日: str
    分区: str

    @property
    def 身份(self) -> str:
        规范内容 = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(规范内容.encode("utf-8")).hexdigest()

    def 规范内容(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=2)
