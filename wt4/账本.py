from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(frozen=True)
class 账本事件:
    序号: int
    实验身份: str
    类型: str
    内容: dict[str, Any]
    发生于: str


class 追加式账本:
    def __init__(self, 路径: Path) -> None:
        self.路径 = 路径
        self.路径.parent.mkdir(parents=True, exist_ok=True)
        with self._连接() as 数据库:
            数据库.executescript(
                """
                CREATE TABLE IF NOT EXISTS 事件 (
                    序号 INTEGER PRIMARY KEY AUTOINCREMENT,
                    实验身份 TEXT NOT NULL,
                    类型 TEXT NOT NULL,
                    内容 TEXT NOT NULL,
                    发生于 TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS 禁止更新事件
                BEFORE UPDATE ON 事件 BEGIN
                    SELECT RAISE(ABORT, '事件账本只允许追加');
                END;
                CREATE TRIGGER IF NOT EXISTS 禁止删除事件
                BEFORE DELETE ON 事件 BEGIN
                    SELECT RAISE(ABORT, '事件账本只允许追加');
                END;
                """
            )

    def _连接(self) -> sqlite3.Connection:
        数据库 = sqlite3.connect(self.路径)
        数据库.execute("PRAGMA foreign_keys = ON")
        return 数据库

    def 追加(self, 实验身份: str, 类型: str, 内容: dict[str, Any]) -> 账本事件:
        发生于 = datetime.now(UTC).isoformat()
        with self._连接() as 数据库:
            游标 = 数据库.execute(
                "INSERT INTO 事件 (实验身份, 类型, 内容, 发生于) VALUES (?, ?, ?, ?)",
                (实验身份, 类型, json.dumps(内容, ensure_ascii=False, sort_keys=True), 发生于),
            )
            序号 = int(游标.lastrowid)
        return 账本事件(序号, 实验身份, 类型, 内容, 发生于)

    def 事件(self, 实验身份: str) -> list[账本事件]:
        with self._连接() as 数据库:
            行 = 数据库.execute(
                "SELECT 序号, 实验身份, 类型, 内容, 发生于 FROM 事件 WHERE 实验身份 = ? ORDER BY 序号",
                (实验身份,),
            ).fetchall()
        return [账本事件(序号, 身份, 类型, json.loads(内容), 时间) for 序号, 身份, 类型, 内容, 时间 in 行]
