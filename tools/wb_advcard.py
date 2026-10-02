r"""对抗复核**开场白 + 指针索引**生成器（卡 143 · T-G242）。

**为什么有它**：用户把对抗复核从"**闸**"（挡收口 ⇒ 每批都要等一轮）改成了"**审计**"
（**提交之后**、异步、与下一批并行 ⇒ 不挡流水线）。方法本身有效（今晚唯一一次真对抗
一次抓出 14 条 + 5 条判据漏洞），但那是一次性的、靠人临时写开场白。这个生成器把
"开场白 + 指针索引"变成**一条命令**：

    python -X utf8 tools/wb_advcard.py --commit <sha>     # ★ 主形态：提交之后跑
    python -X utf8 tools/wb_advcard.py --task <任务号>     # 从任务栅栏的状态文件取

产物落到 `gates/diag/batch/<任务或提交>.advcard.md`（**scratch、不进 git**），至少含：

1. ★ **这一笔/这一批新加了哪些能力**（从成员 `what` 与 claim `why` 抽）—— 每处新能力
   都可能是**新的假绿路径**；
2. ★ **改动文件清单**（`git diff`/`git show --name-only`）与**每处「谁判它」**——
   能复用**卡 142 的 `tools/wb_impact.py`** 就复用（`TF_IMPACT_TOOL` 可覆盖，自证要桩掉它），
   **拿不到影响面就明确降级、说"拿不到"**，**绝不自己硬编一张门表**；
3. ★ **要它攻击的四问**（固定模板）；
4. ★ **硬要求**：**只读** / 结论带**证据指针**（`路径:行` 或命令读数）/ **找不到就说找不到**
   （不许编）/ 产出是**跟进卡清单**（每条发现给出"该开哪张卡、治什么"）。

**边界（如实写）**：
- 它**只生成草稿**：不派活、不提交、不改任何被复核的文件（产物是它自己写的 scratch）。
- `--task` 形态依赖任务栅栏的状态：任务**还没 `landed`（没有 commit）** ⇒ 改动文件清单留空
  并写明"拿不到 commit"，**不猜**。
- 影响面工具（`tools/wb_impact.py`，卡 142）此刻**可能还没落地** ⇒ 生成器**明确降级**，
  照实写"拿不到影响面"，不硬编门表（判据见卡 143 §5 钉子⑤）。
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pool import task as pool_task  # noqa: E402 —— tools/ 已在 sys.path 上

#: 生成物落这儿（scratch、不进 git）—— 与任务栅栏同一个 batch 目录（主树）。
OUT_DIR_REL = ("gates", "diag", "batch")


class AdvError(Exception):
    """用法 / 环境层面的错（拿不到东西就如实报，别静默）。"""


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def git_out(*args: str) -> tuple[int, str]:
    """在**主树**跑一条 git（`cwd` 显式给，免得落在别的树上）；返回 (rc, 合并后的输出)。

    ★ `-c core.quotepath=false`：中文路径不转义（否则得到 `"\\345\\244\\215..."` 那种乱码，
    对复核者毫无用处）。
    """
    done = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def changed_files(sha: str) -> list[str]:
    """这一笔改了哪些文件（`git show --name-only`）——去重、保序、跳过空行。"""
    rc, out = git_out("show", "--pretty=format:", "--name-only", sha)
    if rc != 0:
        raise AdvError(f"算不出 {sha} 的改动文件（git 退 {rc}）：{out.strip()}")
    seen: list[str] = []
    for line in out.splitlines():
        name = line.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def impact_tool() -> Path:
    """影响面工具（卡 142）——`TF_IMPACT_TOOL` 可覆盖（自证要桩掉它）。"""
    override = os.environ.get("TF_IMPACT_TOOL", "").strip()
    if override:
        return Path(override)
    return ROOT / "tools" / "wb_impact.py"


def impact_section(files: list[str]) -> str:
    """★ 复用影响面：把改动文件交给 `tools/wb_impact.py`，**原样收它的输出**。

    **拿不到就明确降级**（工具不在 / 跑不动）—— 照实写"拿不到影响面"，
    ★ **绝不自己硬编一张门表**（判据：卡 143 §5 钉子⑤）。
    """
    if not files:
        return "（这一笔没有改动文件，或拿不到改动清单 ⇒ 影响面无从谈起）"
    tool = impact_tool()
    if not tool.is_file():
        return (f"★ **拿不到影响面**：影响面工具不在（`{tool}`）—— 不在这里硬编门表；"
                f"请人工核每处改动的判据与反例钉子路径。待复核的文件：{'、'.join(files)}")
    done = subprocess.run([sys.executable, "-X", "utf8", str(tool), *files],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode != 0:
        tail = "\n".join(((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-12:])
        return (f"★ **拿不到影响面**：`{tool.name}` 退 {done.returncode} —— 不硬编门表。"
                f"它的尾部读数：\n```\n{tail}\n```")
    body = (done.stdout or "").strip()
    return body or f"★ `{tool.name}` 没输出内容（空）—— 不硬编门表，请人工核。"


#: ★ 固定四问（卡 143 §2.2）—— 一字不改地进草稿。
FOUR_QUESTIONS = (
    "① 哪条**新能力**让「看着绿其实没查」变得可能？",
    "② 哪条判据只查**存在性**而非**真伪**？",
    "③ 哪条**自报清单**还在被当判据？",
    "④ 哪条**退出码/产物**被当成了结论？",
)

#: ★ 硬要求（卡 143 §2.2）。
HARD_RULES = (
    "**只读**：不改任何文件（不许写、不许提交、不许改别人的树）。",
    "结论必须带**证据指针**（`路径:行` 或命令读数）—— 不带指针的结论等于没结论。",
    "**找不到攻击点就说找不到**（不许编）。",
    "产出是**跟进卡清单**：每条发现给出「该开哪张卡、治什么」。",
)


def name_for_task(task_id: str) -> str:
    return task_id


def name_for_commit(sha: str) -> str:
    return sha[:12]


def load_task_bundle(task_id: str) -> dict:
    """读任务栅栏的状态 + 预声明 + 每张卡的申请（收不到的卡如实标"缺席"）。"""
    state = pool_task.read_json(pool_task.state_path(task_id))
    man = pool_task.load_manifest(task_id)
    members = []
    for mem in man["member"]:
        mid = mem["id"]
        inbox = pool_task.inbox_dir(task_id) / f"{mid}.json"
        claim = pool_task.read_json(inbox) if inbox.exists() else None
        members.append({"mem": mem, "claim": claim})
    return {"state": state, "man": man, "members": members}


def _member_lines(bundle: dict) -> str:
    """★ 这一批新加了哪些能力（从成员 `what` 与 claim `why` 抽）—— 每处都可能是假绿路径。"""
    rows = []
    state = bundle["state"]
    ro = set(state.get("read_only") or [])
    for row in bundle["members"]:
        mem, claim = row["mem"], row["claim"]
        mid = mem["id"]
        tag = "★只读(审计)" if mid in ro else mem.get("layer", "")
        what = mem.get("what", "")
        why = (claim or {}).get("why", "")
        detail = why or what
        rows.append(f"- **{mid}**（{tag}）：{detail}")
        if why and what and why != what:
            rows.append(f"  · 卡片的自我描述：{what}")
    return "\n".join(rows) if rows else "（这份任务没有成员能力描述 —— 见预声明）"


def render_task(task_id: str) -> str:
    bundle = load_task_bundle(task_id)
    state = bundle["state"]
    commit = (state.get("landed") or {}).get("commit")
    file_list = "(任务还没 landed ⇒ 拿不到 commit，改动文件清单留空)"
    if commit:
        try:
            files = changed_files(commit)
            file_list = "\n".join(f"- `{f}`" for f in files) or "（这一笔没有改动文件）"
        except AdvError as exc:
            file_list = f"★ 算不出改动文件：{exc}"
    else:
        files = []
    impact = impact_section(files if commit else [])
    return _render(name=name_for_task(task_id), title=f"任务 {task_id}", commit=commit,
                   abilities=_member_lines(bundle), files_block=file_list, impact=impact)


def render_commit(sha: str) -> str:
    rc, subject = git_out("log", "-1", "--pretty=format:%s", sha)
    subject = subject.strip() if rc == 0 else "（读不到这一笔的标题）"
    files = changed_files(sha)
    files_block = "\n".join(f"- `{f}`" for f in files) or "（这一笔没有改动文件）"
    abilities = ("（按 `--commit` 生成 ⇒ **没有任务清单**；"
                 "新能力见这一笔的改动文件与提交信息）\n\n"
                 f"> 提交标题：{subject}")
    return _render(name=name_for_commit(sha), title=f"提交 {name_for_commit(sha)}", commit=sha,
                   abilities=abilities, files_block=files_block, impact=impact_section(files))


def _render(*, name: str, title: str, commit: str | None, abilities: str,
            files_block: str, impact: str) -> str:
    four = "\n".join(f"{q}" for q in FOUR_QUESTIONS)
    rules = "\n".join(f"- {r}" for r in HARD_RULES)
    return f"""# 对抗复核开场白 · {title}

> 生成于 {now_iso()} · 这一份是**审计**（提交之后、异步、与下一批并行）—— **不挡收口**。
> 被复核的提交：`{commit or '（没有 commit）'}`
> ★ 复核者必须与实现者**不同族**（同族共享盲点）。
> ★ 你的产物是**跟进卡清单**，不是"通过/不通过"的章：发现问题 ⇒ 开跟进卡（fix-forward）。
> ★ 诚实边界：复核**降低**概率、**不归零**；你也会漏；最终责任仍在主控（唯一写者）。

## 一、这一批新加了哪些能力（**每处新能力都可能是新的假绿路径**）

{abilities}

## 二、改动文件清单 + 每处「谁判它」

### 改动文件

{files_block}

### 谁判它（影响面 · 判据 + 反例钉子路径）

{impact}

★ 这一节的要求：**每处改动**都要指出「谁判它」—— 判据在哪（`路径:行`）+ 反例钉子在哪
（"故意坏掉会红"的那条用例）。对不上就在四问里点名。

## 三、要你攻击的四问（固定模板）

{four}

## 四、硬要求（缺一条就是没做到）

{rules}

## 五、怎么回报

每条发现一行：`严重度 · 结论 · 证据指针（路径:行 / 命令读数）· 该开哪张卡、治什么`。
**找不到攻击点就写"找不到"**，别把"没找到"包装成"通过"。
"""


def out_path(name: str) -> Path:
    return pool_task.batch_dir() / f"{name}.advcard.md"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="wb_advcard",
        description="对抗复核开场白 + 指针索引生成器（提交之后、异步；只读审计）")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--task", help="任务号（从任务栅栏的状态文件取）")
    g.add_argument("--commit", help="提交 sha（★ 主形态：提交之后跑）")
    args = parser.parse_args(argv)
    try:
        if args.task:
            name, text = name_for_task(args.task), render_task(args.task)
        else:
            name, text = name_for_commit(args.commit), render_commit(args.commit)
        target = out_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    except (AdvError, pool_task.BatchError) as exc:
        print(f"✗ {type(exc).__name__}：{exc}", file=sys.stderr)
        return 2
    print(f"对抗复核草稿写好了：{target}（{len(text.encode('utf-8'))} 字节）")
    print("  ★ 审计（提交之后 · 异步 · 不挡收口）；发现的问题开跟进卡；最终责任在写者")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
