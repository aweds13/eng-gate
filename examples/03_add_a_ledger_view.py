"""例 3（深）· 加一条**解读层口径**：「本周产出条数（按类分开）」，并把这条链走完。

什么时候用这个示例：你要给用户看一个**新数字/新图表** —— 它不是"新发生的事"，
而是**对已有事实的一种解读**。

为什么必须分两层（见 `docs/implementation/architecture.md`）：
- **事实层（facts）**：只记发生了什么（`output.manual` / `output.retracted` …），与心智模型无关；
- **解读层（ledger / insights）**：按**当前**心智模型把事实算成账目/指标。换口径只改解读层，
  历史事实一条都不用动 —— 这就是"如实记账"能成立的原因。

本示例真的会跑：建临时库 → 造 3 条产出 + 撤销其中 1 条 → 用自己的口径算 → 打印。
**注意两条口径**（抄自 `core/ledger/ledger.py`，自己也别发明）：
  ① 按 `subject_id` **去重**（同一笔被记两次只算一笔）；
  ② **撤销照扣**（`output.retracted` 的 subject_id 要减掉）——
     撤销不是"删掉事实"，是"再记一条反向事实"。

真正接进产品还要 3 步（形状见 `docs/EXTENDING.md` §四）：
    ② `src/timeflow/api/app.py` 加只读路由 → ③ `src/web/index.html` 加展示位
    ④ `docs/traceability.toml` 加证据断言（**审计会逐条实跑**，写了就必须成立）

跑法（在项目根目录）：
    python -X utf8 examples/03_add_a_ledger_view.py
"""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from timeflow.core import facts
from timeflow.storage import db

if TYPE_CHECKING:
    import sqlite3


def outputs_since(conn: sqlite3.Connection, since: str) -> Counter[str]:
    """某时刻以来的**有效**产出条数，按 `kind`（kpi / asset）分开报。

    只读事实层；不折算、不估值、不做目标对标（守约定层红线）。
    """
    manual = facts.query(conn, kind="output.manual", since=since)
    retracted = {
        row["subject_id"] for row in facts.query(conn, kind="output.retracted", since=since)
    }
    live = {row["subject_id"] or row["id"]: row for row in manual}
    return Counter(
        str(row["value_text"] or "asset") for sid, row in live.items() if sid not in retracted
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(str(Path(tmp) / "ex3.db"))

        def add(entry_id: str, kind: str, value: float) -> None:
            facts.record(
                conn,
                kind="output.manual",
                subject_type="output",
                subject_id=entry_id,
                value_num=value,
                value_text=kind,
                extra={"entry_id": entry_id, "kind": kind, "value": value},
                source="desktop",
            )

        add("o1", "asset", 1)      # 一篇笔记（知识资产）
        add("o2", "asset", 1)      # 另一篇笔记 —— 下面会被撤销
        add("o3", "kpi", 1)        # 一次成绩达标（学校 KPI）
        facts.record(                # 撤销 o2：**再记一条反向事实**，不删原事实
            conn,
            kind="output.retracted",
            subject_type="output",
            subject_id="o2",
            value_num=1,
            value_text="asset",
            extra={"entry_id": "o2"},
            source="desktop",
        )

        counts = outputs_since(conn, "2000-01-01T00:00:00")

        assert counts == Counter({"asset": 1, "kpi": 1}), counts
        assert facts.count(conn, "output.manual") == 3, "原事实不许被删（撤销是追加，不是覆盖）"

        print(f"[例3] 本周产出（有效）：合计 {sum(counts.values())} 条 —— "
              f"知识资产 {counts['asset']} / 学校 KPI {counts['kpi']}")
        print("[例3] 撤销的那条已扣掉，但**原事实仍在库里**（可回溯、可解释）")
        print("OK 例3：解读层口径可跑；接进产品还要加 API 路由 + 界面展示位 + 台账证据")
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
