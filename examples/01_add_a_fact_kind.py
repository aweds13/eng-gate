"""例 1（浅）· 加一个**事实 kind**：给 timeflow 加「阅读打卡」这件事。

什么时候用这个示例：你要记一件**新发生的事**（读了书、跑了步、喝了水……），
而它不需要新的表、不需要新的字段。

三条必懂的规矩：
1. **事实只记「发生了什么」**，不记「算成什么」 —— 「读了 35 分钟」是事实，
   「折算成 0.58 小时投入」是解读（那是 ledger 的事，而且本项目**不做时间折算**）。
2. `kind` 是**自由字符串**，约定 `域.动作`（如 `reading.logged`）——
   **加新 kind 不改表、不改 schema**。
3. 写完事实后要不要**联动**别的线，由订阅者决定（同步执行，`publish` 返回时联动已生效）。

跑法（在项目根目录）：
    python -X utf8 examples/01_add_a_fact_kind.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from timeflow.core import facts
from timeflow.storage import db

KIND = "reading.logged"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(str(Path(tmp) / "ex1.db"))

        # ① 订阅：谁关心「阅读」这件事（"reading.*" 是前缀通配，reading.logged 也命中）
        seen: list[str] = []

        def on_reading(kind: str, payload: dict[str, Any]) -> None:
            seen.append(f"{payload['book']} {int(payload['minutes'])} 分钟")

        facts.subscribe("reading.*", on_reading)

        # ② 记事实（落库）。extra 放罕见/结构化字段，不用于查询主路径。
        fid = facts.record(
            conn,
            kind=KIND,
            subject_type="book",
            subject_id="book-1",
            value_num=35,                      # 高频数值走固定列（可索引）
            value_text="《深度工作》",
            extra={"minutes": 35, "book": "《深度工作》"},
            source="desktop",
        )

        # ③ 通知订阅者（同步：publish 返回时联动已生效）
        facts.publish(KIND, {"conn": conn, "minutes": 35, "book": "《深度工作》"})

        # ④ 读回来（kind 支持前缀通配；subject_id 可精确查某一本书）
        rows = facts.query(conn, kind="reading.*")
        book_rows = facts.query(conn, kind=KIND, subject_id="book-1")

        assert len(rows) == 1 and rows[0]["kind"] == KIND, rows
        assert len(book_rows) == 1, book_rows
        assert seen == ["《深度工作》 35 分钟"], seen
        assert not facts.errors, facts.errors        # 订阅者抛错会被总线条隔离记在这里

        print(f"[例1] 事实 id={fid[:6]}  kind={KIND}  条数={facts.count(conn, KIND)}")
        print(f"[例1] 订阅者收到：{seen}")
        print("OK 例1：新事实 kind 已能记录 + 联动（**没改表、没改 schema、没动账本**）")

        facts.clear()   # 总线是**进程内**的；脚本里清掉，避免影响后续示例/测试
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
