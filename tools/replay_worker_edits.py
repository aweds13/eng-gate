"""把已死工人（CodeBuddy，429 掐断）的 Edit 操作**照原顺序重放**回卡树。

为什么要它：本轮 197/198 的工人干了 19~41 次调用后被 429 掐断，它们的编辑**不在树里**
（转写记录在 `gates/diag/wb-<卡>.jsonl`）⇒ 重放能把"半成品"接上，而不是从零重做。

用法：`python -X utf8 tools/replay_worker_edits.py <卡号> [--dry-run]`
仅支持 `Edit`（`old_string`/`new_string` 精确替换）—— `Write` 一类我们这轮没用到。
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pool.jobs import read_log_lines  # 读法唯一真源（卡 E75）；本文件先挂 tools/

CARDS = {"197": ".wt/queue", "198": ".wt/reviewallow"}


def load_edits(card: str) -> list[dict]:
    """按转写记录里出现的**先后顺序**取出所有 Edit。"""
    log = pathlib.Path("gates/diag") / f"wb-{card}.jsonl"
    edits: list[dict] = []
    for line in read_log_lines(log):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue

        def walk(o):
            if isinstance(o, dict):
                if o.get("name") == "Edit" and isinstance(o.get("input"), dict):
                    edits.append(o["input"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(d)
    return edits


def main(argv: list[str]) -> int:
    card = argv[0]
    dry = "--dry-run" in argv
    tree = pathlib.Path(CARDS[card]) if card in CARDS else None
    if tree is None:
        print(f"★ 没有 {card} 的树映射（只支持 {list(CARDS)}）")
        return 2
    edits = load_edits(card)
    print(f"  卡 {card}：转写里 {len(edits)} 笔 Edit，树 = {tree}")
    ok = skipped = failed = 0
    for i, e in enumerate(edits, 1):
        raw = str(e.get("file_path", ""))
        # 工人写的是绝对路径（Windows）；取它在树里的相对位置
        rel = raw.replace("\\", "/")
        marker = f"/{tree.as_posix().split('/')[-1]}/"
        rel = rel.split(marker, 1)[1] if marker in rel else rel.split("/")[-1]
        target = tree / rel
        old, new = e.get("old_string", ""), e.get("new_string", "")
        if not target.exists():
            print(f"    ✗ {i}: 目标不在：{target}")
            failed += 1
            continue
        text = target.read_text(encoding="utf-8")
        if new and new in text and old not in text:
            print(f"    ↷ {i}: 已经是新内容（跳过）")
            skipped += 1
            continue
        if old and old not in text:
            print(f"    ✗ {i}: old_string 匹配不上（{rel}）")
            failed += 1
            continue
        if dry:
            print(f"    · {i}: 可打（{rel}，{len(old)}→{len(new)} 字符）")
            ok += 1
            continue
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        ok += 1
        print(f"    ✓ {i}: 已打（{rel}）")
    print(f"  合计：成功 {ok} · 跳过 {skipped} · 失败 {failed}{'（干跑）' if dry else ''}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
