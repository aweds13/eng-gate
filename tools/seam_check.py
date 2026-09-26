"""跨卡接缝预检：按「符号」取交集（T-G139）。

为什么有这个工具：白名单只保证「文件不相交」，保证不了「契约不相交」。
真撞过两次 —— 卡 022（5f51806）改了 `_write_myday_rank` 的签名（新增
keyword-only 参数 `bump_version`），T-G126（803be3a）在另一个文件里用
`monkeypatch.setattr(manager, "_write_myday_rank", …)` 把它整只换成老签名的桩；
两卡各自全绿，集成时全量门禁才红（`assert 500 == 409`）。

符号取三类（宁可少、不可滥）：
  1. 定义：`def NAME(` / `class NAME` / `async def NAME(`（新增或删除行）；
  2. 被桩替换/打补丁的对象：`setattr(…, "NAME"` / `monkeypatch.setattr(…, "NAME"` /
     `patch(…, "NAME"`（★ 本次接缝正是这个形状）；
  3. 新增/改动的形参名：只取**打开的 def 参数表里**的参数行（形如 `NAME: T = 默认` 或
     `*, NAME`），并把所在签名的函数名一并记上（★ 签名改动 = 契约改动；
     `def` 行本身常是上下文行，不改这一条会漏报卡 022 那种接缝）。
     函数体里的局部变量、字符串里的词一概不算。

用法（集成前 / 队列里有两张以上改同一模块的卡时跑一次）：
    python -X utf8 tools/seam_check.py --card 022=5f51806 --card 126=803be3a

退出码：有交集 = 1（必须串行，或后一张基于前一张重做）；无交集 = 0；
用法错误 / 提交不存在 = 2。只读：只跑 `git show`，不写任何仓库文件。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

# 只在这些路径里找符号（与卡的口径一致：实现层 + 测试层；文档不算契约）
ALLOWED_PREFIXES = ("src/", "tools/", "scripts/", "tests/")

RE_FILE_NEW = re.compile(r"^\+\+\+ b/(.+)$")
RE_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@\s*(.*)$")
RE_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\((.*)$")
RE_CLASS = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b")
RE_SETATTR = re.compile(
    r"\b(?:monkeypatch\.)?setattr\s*\(\s*[^,()]+,\s*[\"']([A-Za-z_][\w.]*)[\"']"
)
RE_PATCH = re.compile(r"\bpatch\s*\(\s*[\"']([A-Za-z_][\w.]*)[\"']")
# 单个形参 token：`NAME` / `NAME: 类型` / `NAME: 类型 = 默认` / `NAME = 默认`
RE_PARAM = re.compile(r"^([A-Za-z_]\w*)\s*(?::\s*[^=,]+)?(?:=.*)?$")

KIND_LABEL = {
    "def": "定义",
    "stub": "桩替换",
    "param": "形参",
    "sig": "签名改动",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    path: str
    kind: str  # "def" | "stub" | "param" | "sig"


def _param_names(line: str) -> list[str]:
    """从一条参数行里取出形参名；取不动的 token 直接跳过（宁可少、不可滥）。"""
    names: list[str] = []
    for token in line.strip().rstrip(",").split(","):
        t = token.strip().lstrip("*").strip()
        if not t:
            continue
        m = RE_PARAM.match(t)
        if m:
            names.append(m.group(1))
    return names


def _paren_delta(text: str) -> int:
    return text.count("(") - text.count(")")


def extract_symbols(diff_text: str) -> list[Symbol]:
    """从一段 `git show` 的 diff 文本里抽符号（纯函数，测试直接喂假 diff）。"""
    symbols: list[Symbol] = []
    seen: set[Symbol] = set()

    def add(name: str, path: str, kind: str) -> None:
        s = Symbol(name, path, kind)
        if s not in seen:
            seen.add(s)
            symbols.append(s)

    path: str | None = None
    in_sig = False  # 某个 def 的参数表正开着（括号没闭拢）
    sig_name: str | None = None
    bal = 0

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            path, in_sig, sig_name, bal = None, False, None, 0
            continue
        m_file = RE_FILE_NEW.match(raw)
        if m_file:
            p = m_file.group(1).strip()
            path = p if p.startswith(ALLOWED_PREFIXES) else None
            in_sig, sig_name, bal = False, None, 0
            continue
        if path is None or raw.startswith("---"):
            continue
        if raw.startswith("@@"):
            m_hunk = RE_HUNK.match(raw)
            ctx = m_hunk.group(1) if m_hunk else ""
            m_def = RE_DEF.match(ctx)
            if m_def:
                # hunk 头里带的函数上下文：括号没闭拢 → 参数表还开着
                # （正则把 `def NAME(` 的开括号吃掉了，所以基数是 1）
                bal = 1 + _paren_delta(m_def.group(2))
                in_sig = bal > 0
                sig_name = m_def.group(1) if in_sig else None
            else:
                in_sig, sig_name, bal = False, None, 0
            continue
        if raw.startswith("+++"):
            continue  # 文件行已在上面处理过

        body = raw[1:] if raw[:1] in ("+", "-") else raw
        is_change = raw[:1] in ("+", "-")

        # ② 被桩替换 / 打补丁的对象（本卡接缝的形状，必须有；只看改动行）
        if is_change:
            for m in RE_SETATTR.finditer(body):
                add(m.group(1).rsplit(".", 1)[-1], path, "stub")
            for m in RE_PATCH.finditer(body):
                add(m.group(1).rsplit(".", 1)[-1], path, "stub")

        # ① 定义（def / class）—— def 行常是上下文行（卡 022 正是如此），
        #    所以**上下文行也要**用它开/关参数表状态；只有改动行才记符号
        m_def = RE_DEF.match(body)
        if m_def:
            if is_change:
                add(m_def.group(1), path, "def")
            # 同上：开括号被正则吃掉，基数是 1
            bal = 1 + _paren_delta(m_def.group(2))
            in_sig = bal > 0
            sig_name = m_def.group(1) if in_sig else None
            continue
        if is_change:
            m_cls = RE_CLASS.match(body)
            if m_cls:
                add(m_cls.group(1), path, "def")
                in_sig, sig_name, bal = False, None, 0
                continue

        # 参数表状态随每一行（含上下文行）推进
        if in_sig:
            bal += _paren_delta(body)
            if bal <= 0:
                in_sig, sig_name = False, None
            # ③ 形参：只收「打开的参数表里」像参数的行；带引号（字符串）、
            #    带括号、不以逗号/星号收尾的一律不要 —— 别把函数体的局部变量算进来
            stripped = body.strip()
            if (
                is_change
                and sig_name
                and "\"" not in body
                and "'" not in body
                and (stripped.endswith(",") or stripped.startswith("*"))
                and "(" not in body
                and ")" not in body
            ):
                add(sig_name, path, "sig")
                for name in _param_names(body):
                    add(name, path, "param")

    return symbols


def git_show(sha: str) -> str:
    proc = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", "show",
         "--format=", "--no-color", "--no-ext-diff", sha],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print(f"[错误] git show {sha} 失败：{proc.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
    return proc.stdout


def parse_cards(values: list[str]) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = []
    for v in values:
        name, sep, sha = v.partition("=")
        if not sep or not name.strip() or not sha.strip():
            print(f"[错误] --card 要 <名字>=<sha> 形式，收到：{v!r}", file=sys.stderr)
            raise SystemExit(2)
        cards.append((name.strip(), sha.strip()))
    return cards


def find_common(
    card_symbols: dict[str, list[Symbol]],
) -> dict[str, list[str]]:
    """返回 交集名 → 出现过的卡名列表（只收 ≥2 张卡共有的名字）。"""
    where: dict[str, list[str]] = {}
    for card, syms in card_symbols.items():
        for s in syms:
            lst = where.setdefault(s.name, [])
            if card not in lst:
                lst.append(card)
    return {n: cs for n, cs in where.items() if len(cs) >= 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="跨卡接缝预检：按符号取交集（定义/桩替换对象/形参）",
    )
    parser.add_argument(
        "--card", action="append", required=True, metavar="名字=sha",
        help="一张卡的提交，可重复给多张（如 --card 022=5f51806）",
    )
    args = parser.parse_args(argv)
    cards = parse_cards(args.card)

    card_symbols: dict[str, list[Symbol]] = {}
    for name, sha in cards:
        syms = extract_symbols(git_show(sha))
        card_symbols[name] = syms
        if syms:
            parts = "、".join(f"{s.name}（{s.path} · {KIND_LABEL[s.kind]}）" for s in syms)
        else:
            parts = "（无 —— 允许路径内没有新增/删除代码行）"
        print(f"[卡 {name}={sha}] 符号：{parts}")

    common = find_common(card_symbols)
    if common:
        for name, owners in common.items():
            print(
                f"[交集] ★ {name} ← 出现在 {'、'.join(owners)}"
                f" → 必须串行，或后一张基于前一张重做"
            )
        return 1
    print("[交集] 无交集")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
