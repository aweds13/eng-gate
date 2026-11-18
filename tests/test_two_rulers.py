r"""「两把尺子」钉子（卡 E60 · T-AG518）。

为什么有它：同一件事在仓里被**两处**判断，两处给出相反答案，而且没人钉住它们必须一致。
这不是「某个判据写错了」，而是**一致性本身没有守卫** —— 所以每发现一处，就得在此处
补一条「必须说同一句话」的钉子；光修一处实现，下一次还会漂。

本文件钉三处（全部实测过会咬）：

**一、`tree_without_gates()` 在旧 rev 上必须真把 `gates/` 摘掉。**
  病根：`scripts/run_gates.py` 的 `git rm -r --cached --ignore-unmatch --quiet gates`
  **缺 `-f`**。`read-tree <旧 rev>` 建出来的索引里 `gates/` 条目与工作区、HEAD 都不一致
  （`last.json` 每趟都被改写），git 以「staged content different from both the file and
  the HEAD」拒删并退 1；返回值没人看 ⇒ `write-tree` 返回**含 gates/ 的整棵树**。
  于是 `last.json.tree` 从「摘掉 gates 的固定点」静默退化成「完整提交树」，自指解药失效。
  14 笔实测：不加 `-f` 时 **13 笔退 1**。

**二、`tools/wb_review.py` 与门禁对「什么叫红」必须同一口径。**
  病根：门禁侧 `gates_ok()` 只数 `blocking` 门；复核侧却无条件把所有 `exit_code != 0`
  当红 ⇒ `web_live exit 3 blocking=false NOT RUN` 这道「没验证」的门，同一份
  `last.json` 在门禁侧判绿、复核侧判红。

**三、`scripts/cloud/run_gate.sh` 的播种判定必须与门禁同口径。**
  病根同上，而且它**卡住云门禁本身**：一份真·全绿读数（`ok=True`，只有非阻断的
  `web_live` exit 3）会被播种判定当成红 ⇒ 云机根本起不来。

★ 全部离线：不连云机、不跑门禁（云机实测由主控做）。
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 只为类型标注（`from __future__ import annotations` 已开，运行时用不到）
    from collections.abc import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_GATES = ROOT / "scripts" / "run_gates.py"
WB_REVIEW = ROOT / "tools" / "wb_review.py"
RUN_GATE_SH = ROOT / "scripts" / "cloud" / "run_gate.sh"


# --------------------------------------------------------------------------- 工具

def _src(path: Path) -> str:
    """读源码，把**所有** CR 归一成 LF，行号才对得上人眼看到的那一行。

    `scripts/run_gates.py` 是三重 CR + 裸 CR 混排（历史入库的）。只收 CR 串+LF 会
    留下裸 CR，`splitlines()` 把它也当换行 ⇒ 报出来的行号与编辑器里差一大截；
    一步写成 `\r\n?` 又会把 `\r\r\r\n` 变成一个 CRLF + 两个裸 CR ⇒ 行号翻倍。
    两步才是对的（这条是被坑两次才写下的）。
    """
    raw = path.read_bytes()
    text = re.sub(rb"\r+\n", b"\n", raw).replace(b"\r", b"\n")
    return text.decode("utf-8", errors="replace")


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert done.returncode == 0, f"git {args} 失败：{done.stderr}"
    return done.stdout


def _tree_entries(tree: str) -> list[str]:
    """`--name-only` 只吐路径、没有 tab 分隔 —— 别再 `split("\t")`。"""
    return [ln for ln in _git("ls-tree", "-r", "--name-only", tree).splitlines() if ln.strip()]


# --------------------------------------------------------------------------- 一：封存指纹

def test_old_rev_still_has_gates_stripped() -> None:
    """旧 rev（非 HEAD）上，封存指纹也必须是**真摘掉 gates** 的那棵树。

    反向验证过：把 `tree_without_gates()` 里的 `-f` 撤掉 ⇒ 本条红，
    报 `gates/ 没被摘掉 —— 封存指纹变成完整树的别名`。
    """
    sys.path.insert(0, str(ROOT))
    from scripts.run_gates import tree_without_gates  # noqa: PLC0415

    old = _git("rev-parse", "--short", "HEAD^").strip()
    assert old, "拿不到父提交（这条钉子要在真仓里跑）"

    fp = tree_without_gates(ROOT, old)
    full = _git("rev-parse", f"{old}^{{tree}}").strip()

    assert fp != full, (
        f"rev={old} 时封存指纹 == 完整树（{fp[:12]}）—— gates/ 没被摘掉，"
        "封存指纹退化成完整树的别名，自指解药失效（症状：git rm 缺 -f 时静默退 1）"
    )
    entries = _tree_entries(fp)
    leftovers = [e for e in entries if e == "gates" or e.startswith("gates/")]
    assert not leftovers, f"封存指纹里还有 gates/ 条目：{leftovers[:5]}（共 {len(leftovers)} 条）"
    assert entries, "封存指纹是空树？"


def test_the_force_flag_is_actually_there() -> None:
    """`-f` 不能只靠行为验证 —— 行为对了但写法换了，下一个人还会踩回去。"""
    src = _src(RUN_GATES)
    m = re.search(r"_git_i\(\s*\"rm\",(.*?)\)\s*$", src, re.S | re.M)
    assert m, "找不到 tree_without_gates 里那条 git rm"
    body = m.group(1)
    assert '"--cached"' in body and '"gates"' in body, body
    assert '"-f"' in body, (
        "git rm 少了 -f：read-tree 旧 rev 时 gates/ 与工作区/HEAD 都不一致，"
        "git 会拒删并退 1，而返回值没人看 ⇒ write-tree 返回含 gates/ 的整棵树"
    )


# --------------------------------------------------------------------------- 二：复核 vs 门禁

def _gates_ok(results: list[dict]) -> bool:
    from scripts.run_gates import gates_ok  # noqa: PLC0415

    return gates_ok(results)


def test_not_run_gate_is_not_red_but_a_real_red_still_is() -> None:
    """三档：NOT RUN 不算红 / 缺 `blocking` 字段按阻断算 / 显式 true 照报。"""
    mixed = [
        {"name": "ruff", "exit_code": 0},
        {"name": "web_live", "exit_code": 3, "blocking": False},
    ]
    assert _gates_ok(mixed) is True, "门禁侧把 NOT RUN 判红了？"

    legacy = [{"name": "audit", "exit_code": 1}]  # 老产物没有 blocking 字段
    assert _gates_ok(legacy) is False, "门禁侧漏了老产物里的真红？"

    explicit = [{"name": "audit", "exit_code": 1, "blocking": True}]
    assert _gates_ok(explicit) is False, "门禁侧漏了显式阻断的红？"

    # ★ 卡 E63（T-AG521）：NOT RUN 不算红，但**一条阻断门都没有**更不算绿 ——
    #   那时这趟什么都没证明过（`all()` 在空表上的真值不是判据）。判据本体在
    #   `tools/gate_verdict.py`；这一条与 `tests/test_no_vacuous_pass.py` 同一件事。
    only_not_run = [{"name": "web_live", "exit_code": 3, "blocking": False}]
    assert _gates_ok(only_not_run) is False, "全是 NOT RUN 也被判成绿了（卡 E63 判据 1）"
    assert _gates_ok([]) is False, "零门被判成绿了（卡 E63 判据 1）"


def test_real_last_json_reads_the_same_way_on_both_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """读**真** `gates/last.json`：复核侧的结论必须等于门禁侧 `gates_ok()`。

    这条是「两把尺子」的总闸 —— 只要两边口径再漂一次，它立刻红。
    反向验证过：撤掉 `wb_review` 的 `blocking` 判据 ⇒ 本条与上一条双双红。
    """
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    from tools import wb_review as wv  # noqa: PLC0415

    payload = json.loads((ROOT / "gates" / "last.json").read_text(encoding="utf-8"))
    gates = payload.get("gates", [])
    assert gates, "gates/last.json 里没有门读数"

    gate_side = _gates_ok(gates)
    # `check_gate_evidence` 是纯函数：只喂 payload 与「父提交」，不碰文件系统。
    # 为了让 rev/ok 这两条不相干的判据不干扰，把它们对齐到 payload 自称的值。
    monkeypatch.setattr(wv, "_resolve_commit", lambda sha: str(sha))
    problems = wv.check_gate_evidence(payload, str(payload.get("rev") or ""))
    review_side = not any("有门没过" in p for p in problems)

    assert review_side == gate_side, (
        f"两把尺子说不同的话：门禁侧 gates_ok={gate_side}、复核侧无 FAIL={review_side}；"
        f"非零门={[g.get('name') for g in gates if g.get('exit_code')]}"
    )


# --------------------------------------------------------------------------- 三：播种 vs 门禁

def _seed_script() -> str:
    """从 `run_gate.sh` 里抽出那段 heredoc 的 Python 判据，原样跑。"""
    src = RUN_GATE_SH.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    i = src.find("import json, sys")
    j = src.find("PYCHECK", i)
    assert i > 0 and j > i, "run_gate.sh 里找不到播种判据那段 heredoc（结构变了要同步改本钉子）"
    return src[i:j]


def _run_seed_check(tmp_path: Path, payload: dict) -> tuple[int, str]:
    path = tmp_path / "last.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "seedcheck.py"
    script.write_text(_seed_script(), encoding="utf-8", newline="\n")
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(script), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def test_seed_check_reads_the_same_way_as_the_gate(tmp_path: Path) -> None:
    """播种判定必须与 `gates_ok()` 同口径，否则一份真·全绿读数会让云机起不来。

    反向验证过：把判据改回「所有 exit_code != 0 都算红」⇒ 本条红。
    """
    real = json.loads((ROOT / "gates" / "last.json").read_text(encoding="utf-8"))
    if any(int(g.get("exit_code", 0)) != 0 for g in real.get("gates", [])) or real.get(
        "not_run"
    ):
        # ★ 卡 E63（T-AG521）：树上那份 last.json 现在不是绿的（上一次跑红 / 云机回传），
        #   「播种判定不许把真·全绿读数当红」这半没有判别力。软行那一条另有钉子
        #   （`test_the_real_reading_needs_a_not_run_gate_to_prove_anything`，改成合成读数）。
        pytest.skip("树上当前 gates/last.json 不是绿的 ⇒「真·全绿读数」这半无判别力")

    code, out = _run_seed_check(tmp_path, real)
    assert _gates_ok(real.get("gates", [])) is True, "真 last.json 在门禁侧竟然是红的？"
    assert code == 0, f"真·全绿读数被播种判定当成红（云机会起不来）：\n{out}"
    soft = [
        g["name"] for g in real.get("gates", [])
        if g.get("exit_code") and not g.get("blocking", True)
    ]
    for name in soft:
        assert name in out, f"非阻断非零门 {name} 没被点名（不许隐瞒）\n{out}"
    assert "阻断门" in out, "成功话术必须说「阻断门全绿」，不能说「全 exit_code=0」"

    hard = json.loads(json.dumps(real))
    for g in hard.get("gates", []):
        if g.get("blocking", True):
            g["exit_code"] = 1
            break
    code, out = _run_seed_check(tmp_path, hard)
    assert code != 0, f"阻断门红了播种判定却放行（真红会被吞掉）：\n{out}"


# --------------------------------------------------------------------------- 四：还有两处同样的尺子

#: 全仓所有「按 `exit_code` 判红」的地方。**每一处都必须说同一句话**。
#: 加新的一处而忘了看 `blocking` ⇒ 本表里那条覆盖它的钉子会红。
_EXIT_CODE_RULERS = {
    "scripts/run_gates.py": ("gates_ok()", "只数 blocking 门，这是**判据真源**"),
    "tools/wb_review.py": ("check_gate_evidence()", "复核侧"),
    "tools/wb_verify.py": ("check_gates()", "独立复算器"),
    "framework/src/framework/review.py": ("check_full_gate_run()", "framework 侧的同一判据"),
    "scripts/cloud/run_gate.sh": ("播种判定", "云机起不起得来的头一道闸"),
    "tools/gate_base.py": ("gate_base_drift(", "派生物差异分类器（卡 E123：门禁基点 vs 父提交）"),
}


#: 扫出但**不是**「判红」的行 —— 每条都必须写清为什么不是。少一条会红（漏判），
#: 多一条也会红（白名单不许悄悄膨胀成「什么都放行」，与 `test_ci_portability` 同规矩）。
#:
#: ★ 卡 E69（T-AG549）：键从**行号**换成 **(rel, 锚点原文)** —— 锚点 = 那一行 `.strip()`
#:   后的逐字原文。行号是**位置**不是**身份**：文件头加一行注释就整体错位（E67 给
#:   `scripts/run_gates.py` 加了 182 行，三条键当场假红，只能手工从 `:672/:1598/:2690`
#:   推到 `:854/:1780/:2872`）。内容不变时行号随便飘；内容一改立刻走「过期」分支并报真行号。
#:   三条理由文字一字未动，只换了键的形状。
_NOT_A_RED_RULER: dict[tuple[str, str], str] = {
    ("scripts/run_gates.py", "return exit_code not in (0, 3)"): (
        "`gate_failed()` —— 判的是**单道门自己**红不红，且已把 3（NOT RUN）显式排除；"
        "整趟过不过看 `gates_ok()`（只数 `blocking` 门）。它不看 `blocking` 是因为"
        "`blocking` 本身就是从这个口径派生的（`exit_code == 3` ⇒ 不阻断）"
    ),
    (
        "scripts/run_gates.py",
        "`exit_code = 124` 一样落进 `!= 0` → 整趟非 0，超时**不会被别的门的通过吞掉**。",
    ): "`gates_ok()` docstring 里的说明文字，不是可执行判据",
    (
        "scripts/run_gates.py",
        'if entry is None or int(str(entry["exit_code"])) != 0:',
    ): (
        "复用记账：只有 exit_code==0 的门才可复用 —— 比 blocking 更严，"
        "NOT RUN 不复用是对的，它不是在判红"
    ),
}


def _read_rel(rel: str) -> str:
    """按仓库相对的 `rel` 读源码（已归一化 CR）。测试要喂合成文本时替换这一个口。"""
    return _src(ROOT / rel)


def _anchor_hits(text: str, anchor: str) -> list[tuple[int, str]]:
    """锚点在该文件里逐字命中哪几行：每行 `.strip()` 后**全等**，不许子串/前缀匹配。"""
    return [
        (n, s)
        for n, s in enumerate((line.strip() for line in text.splitlines()), 1)
        if s == anchor
    ]


def _python_ruler_sites(
    read: Callable[[str], str] = _read_rel,
) -> dict[str, list[tuple[int, str]]]:
    """扫出「按 exit_code 判红」的可执行行，按文件归组（注释与白名单里的不算）。

    ★ 卡 E69：白名单按 `(rel, 这一行的原文)` 判，**不再**拼 `f"{rel}:{n}"` ——
      行号降级成报错里的展示信息，位置漂移不许改变判定（判据 2）。
    """
    out: dict[str, list[tuple[int, str]]] = {}
    for rel in _EXIT_CODE_RULERS:
        if not rel.endswith(".py"):
            continue
        text = read(rel)
        hits = []
        for n, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if "exit_code" in s and ("!= 0" in s or "not in (0" in s) and "blocking" not in s:
                if (rel, s) in _NOT_A_RED_RULER:
                    continue
                hits.append((n, s))
        if hits:
            out[rel] = hits
    return out


def _nearest_line(text: str, anchor: str) -> tuple[int, str] | None:
    """锚点 0 次时给一条**仅供参考**的真行号（最像的那一行），别让人自己去翻三千行。

    只用于报错定位，**不参与判定** —— 判定只认「`.strip()` 后逐字全等」（判据 3）。
    """
    best: tuple[float, int, str] | None = None
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        score = difflib.SequenceMatcher(None, s, anchor).ratio()
        if best is None or score > best[0]:
            best = (score, n, s)
    if best is None or best[0] < 0.5:
        return None
    return best[1], best[2]


def _allow_list_problems(
    allow: dict[tuple[str, str], str] | None = None,
    read: Callable[[str], str] = _read_rel,
) -> list[str]:
    """白名单自证：理由非空 / 锚点在该文件里**恰好 1 次** / rel 在扫描范围里（判据 3）。

    判据 4：「过期」（0 次）与「不唯一」（>1 次）必须**分得开**，且都报出真行号。
    """
    todo = _NOT_A_RED_RULER if allow is None else allow
    bad: list[str] = []
    for (rel, anchor), why in todo.items():
        if not str(why).strip():
            bad.append(f"({rel}, {anchor!r}): 没写理由")
        if rel not in _EXIT_CODE_RULERS:
            bad.append(f"({rel}, {anchor!r}): {rel} 不在扫描范围里（白名单写了没用）")
            continue
        text = read(rel)
        where = [n for n, _ in _anchor_hits(text, anchor)]
        if not where:
            near = _nearest_line(text, anchor)
            hint = (
                f"（最接近的是第 {near[0]} 行：{near[1][:80]!r}）"
                if near
                else f"（文件共 {len(text.splitlines())} 行，一行都不像）"
            )
            bad.append(f"白名单过期：这条原文已经不在 {rel} 里了{hint}")
        elif len(where) > 1:
            spots = "、".join(f"第 {n} 行" for n in where)
            bad.append(
                f"锚点不唯一：`{anchor}` 在 {rel} 里出现 {len(where)} 次（{spots}），"
                "分不清是哪一行"
            )
    return bad


def test_the_allow_list_is_not_stale_and_says_why() -> None:
    """白名单自己也要被钉住：每条都要写理由，锚点必须**逐字**在源码里恰好出现 1 次。

    ★ 卡 E69：不再读行号、不再要求「那一行还含 `exit_code`」—— 位置会漂，内容才是身份。
    锚点 0 次 ⇒「白名单过期」；>1 次 ⇒「锚点不唯一」（分不清钉的是哪一行）。
    """
    bad = _allow_list_problems()
    assert not bad, "白名单有不能自证的行：\n  " + "\n  ".join(bad)



def test_no_exit_code_ruler_forgets_blocking() -> None:
    """全仓扫一遍：凡「按 exit_code 判红」的行，都必须同时看 `blocking`。

    这条是**防复发**的：E60 一次就挖出五处，其中三处是修一处的过程中发现的。
    光把已知的修掉不够 —— 下一次有人再写一处，这里会拦住。

    反向验证：本轮实测挖出并修掉 4 处（`wb_review` / `wb_verify` /
    """
    leftovers = _python_ruler_sites()
    detail = "\n".join(
        f"  {rel}:{n}  {s}" for rel, hits in leftovers.items() for n, s in hits
    )
    assert not leftovers, (
        "这些地方按 exit_code 判红却**没看 blocking**（会把 NOT RUN 当成红，"
        "同一份 last.json 两边结论相反）：\n" + detail
        + f"\n\n已知会说同一句话的 {len(_EXIT_CODE_RULERS)} 处："
        + "、".join(f"`{rel}`（{why}）" for rel, (_, why) in _EXIT_CODE_RULERS.items())
    )


def test_a_shifted_line_number_no_longer_breaks_the_allow_list() -> None:
    """判据 6 的**判别力**：文件头插 3 行注释（行号整体 +3），白名单一条都不许漏跳。

    E67 的病根就在这里：键是行号，`scripts/run_gates.py` 加 182 行后三条全部错位 ⇒
    `_python_ruler_sites()` 漏跳那三行 ⇒ 假红，只能手工推行号。这里在**内存副本**上
    把行号真的挪 3 行（真文件一个字节都不动；真文件级的字节插入与恢复由
    `gates/diag/_rev_E69.py` 做并打印 sha256），要求扫出来的结论仍是「一条都不剩」。
    """
    base = _read_rel("scripts/run_gates.py")
    shifted = "".join(f"# [E69 行号漂移自证] 第 {i} 行\n" for i in (1, 2, 3)) + base

    def read(rel: str) -> str:
        return shifted if rel == "scripts/run_gates.py" else _read_rel(rel)

    anchors = [a for (rel, a) in _NOT_A_RED_RULER if rel == "scripts/run_gates.py"]
    at = sorted(n for a in anchors for n, _ in _anchor_hits(shifted, a))
    assert at and all(n > 3 for n in at), f"三条锚点没落在插行之后：{at}"

    candidates: list[int] = []
    for n, line in enumerate(shifted.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        if "exit_code" in s and ("!= 0" in s or "not in (0" in s) and "blocking" not in s:
            candidates.append(n)
    assert set(candidates) == set(at), (
        "行号整体 +3 之后「候选行」与白名单锚点对不上（锚点没落在被扫的那几行上）："
        f"多出来的候选={sorted(set(candidates) - set(at))}、"
        f"没被扫到的锚点={sorted(set(at) - set(candidates))}"
    )

    leftovers = _python_ruler_sites(read)
    assert leftovers == {}, (
        "行号整体 +3 后那三行又漏跳了（白名单还在靠行号站着，这正是 E67 的假红）："
        f"{leftovers}"
    )


def test_allow_list_anchor_must_be_unique() -> None:
    """判据 4：「锚点不唯一」必须报出**全部**命中行号，且与「过期」分得开。"""
    rel = "scripts/run_gates.py"
    dup = "with contextlib.suppress(OSError):"
    text = f"a = 1\n{dup}\nb = 2\n{dup}\nc = 3\n{dup}\n"
    allow = {(rel, dup): "（理由只在本用例里用，不进真白名单）"}

    many = _allow_list_problems(allow, read=lambda _rel: text)
    assert len(many) == 1, many
    msg = many[0]
    assert msg.startswith("锚点不唯一："), msg
    assert "出现 3 次" in msg, msg
    for n in (2, 4, 6):
        assert f"第 {n} 行" in msg, f"没报出第 {n} 行：{msg}"
    assert "过期" not in msg, f"两个分支分不开：「不唯一」的报错里出现了「过期」—— {msg}"

    gone = _allow_list_problems(allow, read=lambda _rel: "a = 1\nb = 2\nc = 3\n")
    assert len(gone) == 1, gone
    assert "白名单过期：这条原文已经不在" in gone[0], gone[0]
    assert "不唯一" not in gone[0], gone[0]

    once = _allow_list_problems(allow, read=lambda _rel: f"a = 1\n{dup}\nb = 2\n")
    assert once == [], f"恰好 1 次也被判成不能自证（过严）：{once}"


def _gate_payloads() -> list[tuple[str, dict]]:
    """三份读数的形制：真读数、老产物（无 blocking 字段）、只有 NOT RUN。

    一份真读数不够 —— 只有「非阻断非零门」存在时，错的判据才会露馅。
    """
    real = json.loads((ROOT / "gates" / "last.json").read_text(encoding="utf-8"))
    legacy = json.loads(json.dumps(real))
    for g in legacy.get("gates", []):
        g.pop("blocking", None)
    only_not_run = {"ok": True, "rev": real.get("rev"), "gates": [
        {"name": "web_live", "exit_code": 3, "blocking": False},
        {"name": "audit", "exit_code": 0},
    ]}
    return [
        ("真读数", real),
        ("老产物（无 blocking 字段）", legacy),
        ("只有 NOT RUN", only_not_run),
    ]


def test_wb_verify_and_framework_really_run_their_own_ruler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`wb_verify` 与 `framework/review` 的**真函数**跑真读数，结论必须等于 `gates_ok()`。

    不重抄判据、也不 eval 源码片断 —— 直接调那两个函数，让它们**自己**说话。
    反向验证过：把任一处 `and g.get("blocking", True)` 撤掉 ⇒ 本条红。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    sys.path.insert(0, str(ROOT / "framework" / "src"))
    from framework import review as fr  # noqa: PLC0415
    from tools import wb_verify as wv  # noqa: PLC0415

    for label, payload in _gate_payloads():
        want = _gates_ok(payload.get("gates", []))
        # `wb_verify.check_gates` 自己从 git 里读 `HEAD:gates/last.json`（不吃 payload 参数），
        # 所以这里把它的 git 口换成「就返回这份读数」。不改它的判据，只喂数据。
        body = json.dumps(payload, ensure_ascii=False)
        # `check_gates()` 是从 git 里 `show HEAD:gates/last.json` 取的；把那个口换成
        # 「就返回这份读数」—— 判据本身一个字不动，只喂数据。
        monkeypatch.setattr(wv, "_git", lambda *a, _b=body, **k: _b)

        # --- wb_verify：它把「有门没过」写进 Screen 的 bad 行 ---
        issues: list[str] = []
        screen = type("S", (), {
            "bad": lambda self, msg, _acc=issues: _acc.append(msg),
            "info": lambda self, msg: None,
            "ok": lambda self, msg: None,
        })()
        wv.check_gates(screen, ROOT, str(payload.get("rev") or ""))
        red_lines = [m for m in issues if "有门没过" in m]
        assert (not red_lines) == want, (
            f"[{label}] wb_verify 与 gates_ok 说不同的话："
            f"wb_verify 报红={bool(red_lines)}（{red_lines}）、gates_ok={want}"
        )

        # --- framework/review：check_gate_evidence 返回 problems 列表 ---
        problems = fr.check_gate_evidence(payload, str(payload.get("rev") or ""))
        fr_red = [p for p in problems if "有门没过" in p]
        assert (not fr_red) == want, (
            f"[{label}] framework/review 与 gates_ok 说不同的话："
            f"报红={bool(fr_red)}（{fr_red}）、gates_ok={want}"
        )


def test_the_real_reading_needs_a_not_run_gate_to_prove_anything() -> None:
    """前提守卫：真读数里必须真有一道「非阻断且非零」的门。

    没有它，上面那条同结论测试就是空真 —— 三处判据就算全错也照样绿。
    这也是本轮改判据时先踩的坑：本机读数里 `web_live` 是 exit 0，什么都证明不了。
    """
    # ★ 卡 E63（T-AG521）：这条前提**不能**再读真 last.json —— 判据改严之后，
    #   任何 `exit > 0` 或 `status=NOT RUN` 的门行（哪怕 `blocking=False`）都会让整趟变成
    #   「未验证」，所以一份**绿的**产物里不可能再有「非阻断非零门」。原来那句在绿树下
    #   只会退化成空真。改成在**合成读数**上钉同一件事：
    soft = {
        "name": "web_live",
        "exit_code": 3,
        "blocking": False,
        "status": "NOT RUN",
        "summary": "环境里没有浏览器：这一层没有验证，不算通过",
    }
    gates = [{"name": "ruff", "exit_code": 0}, soft]
    assert _gates_ok(gates) is True, "门禁侧把 blocking=False 的非零门当成红了（两把尺子又不一致）"

    sys.path.insert(0, str(ROOT / "tools"))
    from gate_verdict import judge  # noqa: PLC0415 —— 判据本体，按需导入

    verdict = judge({"ok": True, "host": "test-host", "gates": gates, "not_run": []})
    assert verdict.ok is False and verdict.state == "unverified", (
        f"软行居然算通过了（卡 E63 判据 ④：门行自己写着未验证）—— {verdict}"
    )
    assert "web_live" in " ".join(verdict.problems), verdict.problems


# --------------------------------------------------- 五：门禁基点差异分类器（卡 E123）

def test_base_drift_classifier_has_one_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 卡 E123 判据 5：同一 payload + 同一父提交 ⇒ **四处同分类**。

    分类器只写在 `tools/gate_base.py` 一份；复核器（`wb_review`）、独立复算器
    （`wb_verify`）、云侧回传校验（`gate_pool`）都调这一份；`framework` 是纯库
    （不 import 本仓模块）只能做镜像 —— 这条钉子钉的就是「镜像必须说同一句话」：
    同一份注入 ⇒ 同一个分类（LEDGER_ONLY / DRIFT 各测一遍）。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    sys.path.insert(0, str(ROOT / "framework" / "src"))
    import gate_base as gb  # noqa: PLC0415
    import gate_pool as gp  # noqa: PLC0415
    import wb_review as wr  # noqa: PLC0415

    from framework import review as fr  # noqa: PLC0415
    from tools import wb_verify as wv  # noqa: PLC0415

    payload = {
        "rev": "aaaaaaa",
        "ok": True,
        "sealed_at": "2099-01-01T00:00:00",
        "gates": [{"name": "pytest", "exit_code": 0}],
    }
    parent = "bbbbbbb"
    resolved = {"aaaaaaa": "a" * 40, "bbbbbbb": "b" * 40}
    common = {
        "resolve": lambda short: resolved.get(str(short), ""),
        "ancestor": lambda a, b: True,
        "commit_time": lambda rev: "2098-01-01T00:00:00+00:00",
    }
    cases = [
        ("只动台账", {**common, "diff": lambda a, b: ["docs/workbacklog.toml"]}, gb.LEDGER_ONLY),
        ("动了源码", {**common, "diff": lambda a, b: ["docs/workbacklog.toml", "tools/foo.py"]},
         gb.DRIFT),
    ]

    def _wb_verify_state(prov: dict) -> str:
        """让 **真函数** `wb_verify.check_gates` 自己说话（只换它的 git 口，不改判据）。"""
        body = json.dumps(payload, ensure_ascii=False)

        def _fake_git(tree: Path, *args: str) -> str:
            if args[:2] == ("show", "HEAD:gates/last.json"):
                return body
            if args[:1] == ("rev-parse",):
                return resolved.get(str(args[-1]).removesuffix("^{commit}"), "")
            if args[:1] == ("show",):
                return str(prov["commit_time"](args[-1]))
            return ""

        def _fake_run(cmd: list[str], cwd: Path) -> tuple[int, str]:
            if "merge-base" in cmd:
                return 0, ""
            if "diff" in cmd:
                return 0, "\n".join(prov["diff"](cmd[-2], cmd[-1]))
            return 0, ""

        seen: dict[str, list[str]] = {"bad": [], "info": []}
        screen = type("S", (), {
            "bad": lambda self, msg: seen["bad"].append(msg),
            "info": lambda self, msg: seen["info"].append(msg),
            "ok": lambda self, msg: None,
        })()
        monkeypatch.setattr(wv, "_git", _fake_git)
        monkeypatch.setattr(wv, "_run", _fake_run)
        wv.check_gates(screen, ROOT, parent)
        if any("rev != 父提交" in m for m in seen["bad"]):
            return gb.DRIFT
        if any("门禁基点" in m for m in seen["info"]):
            return gb.LEDGER_ONLY
        return gb.MATCH

    for label, prov, want in cases:
        got = {
            "wrap_review": wr.gate_base_drift(
                payload["rev"], parent, sealed_at=payload["sealed_at"], **prov)[0],
            "wb_verify": _wb_verify_state(prov),
            "gate_pool": gp.base_drift_category(
                payload["rev"], parent, payload, **prov)[0],
            "framework": fr.gate_base_drift(
                payload["rev"], parent, sealed_at=payload["sealed_at"],
                is_ledger=gb.is_ledger_path, **prov)[0],
        }
        assert set(got.values()) == {want}, f"[{label}] 四处分类不一致：{got}（应全为 {want}）"
