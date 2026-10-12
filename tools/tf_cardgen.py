"""卡规格 + 开工切片样板生成器（卡 096 · 台账号 `T-G191`）。

## 一句话
每次派活主控都要手抄一份「卡规格 + 开工切片（brief）」，模板固定、只有坐标与禁区在变
（一张卡 + 切片 ≈ 5~13 KB 手写）。本工具从**结构化输入**把两份 markdown 生成出来。

## 硬要求（卡 §④）
- 参数缺失（`--id/--task/--title/--tree/--base` 任一）→ **明确报错退 2**，不许生成半份；
- `--dry-run` 只打印到 stdout，**不落盘**；
- 文件名口径与本仓一致：`<out-dir>/卡<id>-<短标题>.md` 与 `<out-dir>/brief-<id>.md`；
- 生成物**必须包含** `Task:` 行与「★ 不要 commit」那一段；
- ★ 生成结果**不得**包含任何真实台账内容 —— 本工具**不读** `docs/traceability.toml`
  （也不读任何台账）。

用法：
    python -X utf8 tools/tf_cardgen.py --id 096 --task T-G191 --title "…" \
        --tree .wt/mech2 --base 5db2aa1 --pool codebuddy \
        --files a.py b.py --forbid c.py d.py --out-dir gates/diag [--dry-run]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# ★ 短标题里不许出现的字符（Windows/跨平台文件名安全）。
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SHORT_MAX = 60

CARD_TPL = """# 卡 {id} —— {title}（{task}）

**树**：`{tree}`（★ 开局就在这棵树里；`git rev-parse --short HEAD` 必须是主控给你的 base）
**base**：`{base}`（进树先核对）
**号池**：{pool} ｜ **提交**：★ **每完成一小步就 commit 到本卡分支 `card/{id}`**\
（不许碰主干 / push / tag）

Task: {task}

---

## 一、病人话（这一张要治什么病）

TODO：用人话写清「谁还在手工做机器该做的事 / 现状哪里疼」，附实测数字或出处。

## 二、你要做的（白名单 —— 只许动这些文件，其余一个字都不许碰）

{files}

## 三、验收判据

- TODO：每条判据都要有**反例**（缺参数 / 不一致 / 判不了 / 空集合，各自都要能当场说出话来）。
- 主控怎么用**一条命令**验出做到了：TODO

## 四、禁区

- ★ **小步提交到本卡分支 `card/{id}`**；不许碰主干、不许 push、不许打 tag；\
不要动 `.git` 里别的东西。
- 白名单之外一个字不许碰。尤其不许碰：
{forbid}
- 不要装依赖 / 联网；不要顺手重构无关文件。

## 五、回报（≤9 行）

1) 新增/改了哪些文件（逐条 + 一句话）
2) 关键命令的**原样输出**（先跑红、再跑绿）
3) 每条判据的原样输出
4) pytest 原样结论
5) ★ 没做到 / 不确定的：<如实写，没有就写"无">
6) ★ 判断"该改但不属于本卡"的地方
"""

BRIEF_TPL = """# 开工切片 · 卡 {id}（台账号 `{task}`）—— {title}

★ 你是外包工人，只做这一张卡。**卡规格**：`{out_dir}/卡{id}-{slug}.md`（先读它）。

Task: {task}

## 你现在的坐标（主控实测）

```
工作树：{tree}    底座 HEAD = {base}    ← 核对：git rev-parse --short HEAD 必须是它
号池：{pool} ｜ 提交：★ 小步 commit 到 `card/{id}`（不许碰主干 / push / tag）
★ 本卡只许动：
{files}
  其余【一个字都不许碰】—— 尤其：
{forbid}
```

## 本卡要治的病（人还在手工做机器该做的事）

TODO：一段写清现状疼在哪（谁在手工做、哪里可机器化）。

## 你要做到的三件（细节看卡）

1. TODO
2. TODO
3. TODO

## 工作纪律（违反即这轮失败）

- **小步提交到 `card/{id}`**；**不许碰主干**；**不许 push / tag**；不许 `git add .`。
- 不许装依赖 / 联网；不许顺手重构无关文件。
- ★ 每条判据都要有**反例**（缺参数 / 不一致 / 判不了 / 空集合，各自都要能当场说出话来）。

## 干活前先自问

- 我这条判据**红了会说话吗**（点名到条目/参数/文件）？
- 我有没有把"没做检查"伪装成"检查通过"（把空集当通过）？
- 主控怎么用**一条命令**验出做到了？证据留原样输出。

## 回报（卡 §回报 优先）
"""


def short_title(title: str, slug: str | None) -> str:
    """短标题：给了 `--slug` 就用它；否则从标题剥掉文件名不安全字符并截断。"""
    if slug:
        return _UNSAFE.sub("", slug).strip().strip(".")
    cleaned = _UNSAFE.sub("", title).strip()
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned[: _SHORT_MAX].strip().strip(".")
    return cleaned or "untitled"


def _bullets(items: list[str], empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- `{it}`" for it in items)


def render_card(args: argparse.Namespace) -> str:
    return CARD_TPL.format(
        id=args.id, task=args.task, title=args.title, tree=args.tree, base=args.base,
        pool=args.pool,
        files=_bullets(args.files, "TODO：列出本卡白名单文件"),
        forbid=_bullets(args.forbid, "TODO：列出本卡点名禁区"),
    )


def render_brief(args: argparse.Namespace, slug: str) -> str:
    return BRIEF_TPL.format(
        id=args.id, task=args.task, title=args.title, tree=args.tree, base=args.base,
        pool=args.pool, slug=slug, out_dir=args.out_dir,
        files=_bullets(args.files, "  - TODO：本卡白名单"),
        forbid=_bullets(args.forbid, "  - TODO：本卡点名禁区"),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tf_cardgen.py",
        description="卡规格 + 开工切片样板生成（★ 不读台账）",
    )
    p.add_argument("--id", required=True, help="卡号，如 096")
    p.add_argument("--task", required=True, help="台账号，如 T-G191")
    p.add_argument("--title", required=True, help="卡标题")
    p.add_argument("--tree", required=True, help="工作树，如 .wt/mech2")
    p.add_argument("--base", required=True, help="底座 HEAD 短号，如 5db2aa1")
    p.add_argument("--pool", default="codebuddy", help="号池（默认 codebuddy）")
    p.add_argument("--slug", default=None, help="短标题（不给就从 --title 派生）")
    p.add_argument("--files", nargs="*", default=[], help="白名单文件")
    p.add_argument("--forbid", nargs="*", default=[], help="点名禁区")
    p.add_argument("--out-dir", default="gates/diag", help="产出目录（默认 gates/diag）")
    p.add_argument("--dry-run", action="store_true", help="只打印到 stdout，不落盘")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    slug = short_title(args.title, args.slug)
    card = render_card(args)
    brief = render_brief(args, slug)

    if args.dry_run:
        print(f"===== [dry-run] {args.out_dir}/卡{args.id}-{slug}.md =====")
        print(card)
        print(f"===== [dry-run] {args.out_dir}/brief-{args.id}.md =====")
        print(brief)
        print("（--dry-run：未落盘）")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    card_path = out_dir / f"卡{args.id}-{slug}.md"
    brief_path = out_dir / f"brief-{args.id}.md"
    card_path.write_text(card, encoding="utf-8")
    brief_path.write_text(brief, encoding="utf-8")
    print(f"已生成：{card_path}")
    print(f"已生成：{brief_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
