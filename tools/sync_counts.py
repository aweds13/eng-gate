"""把交接文档里那行「台账进度：done a / partial b / …」刷成台账算出来的值（T-G52）。

## 为什么有它

`scripts/audit_progress.py` 会核对这行数字（**手写就会漂，本轮真漂过一次**），
但核对是**事后**的：我写完台账条目、忘了同步交接文档 → `audit` 红 → 再回头改，
每次白花几分钟。这个脚本把"刷数字"从手写改成一条命令，`--check` 还能当检查用。

判据与 audit 完全同一套正则（**一处格式来源**）：`台账进度：done a / partial b / todo c /
deferred d（共 N 条…`，只替换那五个数字，其余文字原样保留。

★ 卡 E38（T-AG492）：根不再按**文件位置**推（原来是
`ROOT = Path(__file__).resolve().parent.parent`）—— 在卡树里用 `../../tools/sync_counts.py`
跑，改的是**主树**的交接文档（E38 现场把主树弄脏过一次）。现在走 `tools/pipe_root.py`：
`PIPE_DATA` > 当前目录（像不像数据根）> 工具所在仓；写法与 `tools/wb_daily.py:54-55` 一致。

    python -X utf8 tools/sync_counts.py            # 直接改（只动那五个数字）
    python -X utf8 tools/sync_counts.py --check     # 只查，漂了就退 1（可当门禁用）
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import tomllib

try:
    import pipe_root
except ImportError:  # pragma: no cover —— 独立拷贝的树里没有 pipe_root
    try:
        from tools import pipe_root  # type: ignore[no-redef]
    except ImportError:
        pipe_root = None  # type: ignore[assignment]

#: 工具根：只用来找本工具，不当数据根。
_TOOL_ROOT = Path(__file__).resolve().parent.parent
#: 台账与交接文档住在**选中的那棵树**里（`pipe_root.data_root()`；没有 pipe_root 时降级回工具根）。
ROOT = pipe_root.data_root() if pipe_root is not None else _TOOL_ROOT
LEDGER = ROOT / "docs" / "traceability.toml"
HANDOFFS = (ROOT / "复盘" / "长任务执行协议.md", ROOT / "复盘" / "交接-重构进度.md")


# 与 `scripts/audit_progress.py` 的 `_HANDOFF_NUM` 同一形状，但**保留分组边界**以便只换数字
NUM = re.compile(
    r"(台账进度：\s*done\s*)(\d+)(\s*/\s*partial\s*)(\d+)"
    r"(\s*/\s*todo\s*)(\d+)(\s*/\s*deferred\s*)(\d+)(\s*（共\s*)(\d+)(\s*条)"
)


def counts() -> tuple[dict[str, int], int]:
    data = tomllib.loads(LEDGER.read_text(encoding="utf-8"))
    entries = data.get("entries", {})
    got: dict[str, int] = {"done": 0, "partial": 0, "todo": 0, "deferred": 0}
    for entry in entries.values():
        status = str(entry.get("status", ""))
        if status in got:
            got[status] += 1
    return got, len(entries)


def rewrite(text: str, got: dict[str, int], total: int) -> str:
    want = (got["done"], got["partial"], got["todo"], got["deferred"], total)

    def sub(m: re.Match[str]) -> str:
        parts = list(m.groups())
        for idx, value in zip((1, 3, 5, 7, 9), want, strict=True):
            parts[idx] = str(value)
        return "".join(parts)

    return NUM.sub(sub, text)


def main() -> int:
    ap = argparse.ArgumentParser(description="刷交接文档里的台账分布（与 audit 同一正则）")
    ap.add_argument("--check", action="store_true", help="只检查，不一致就退 1")
    args = ap.parse_args()

    got, total = counts()
    stale: list[str] = []
    for path in HANDOFFS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        fixed = rewrite(text, got, total)
        if fixed == text:
            continue
        stale.append(path.relative_to(ROOT).as_posix())
        if not args.check:
            path.write_text(fixed, encoding="utf-8")

    dist = " / ".join(f"{k}={v}" for k, v in got.items())
    if not stale:
        print(f"[OK ] 交接文档里的台账分布是最新的（{dist}，共 {total} 条）")
        return 0
    verb = "需要更新" if args.check else "已更新"
    detail = f"{verb}：{', '.join(stale)}（{dist}，共 {total} 条）"
    print(f"[{'FAIL' if args.check else 'OK '}] {detail}")
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
