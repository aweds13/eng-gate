"""卡 E62（T-AG520）：`--only` 零匹配的判据 —— 三道门必须说同一句话。

为什么值得开一张卡钉这四条：`--only` 看起来只是个调试入口，可它**拼错一个字的代价是
"这条门等于没跑，却报通过"**。`not_run` 至少会被 `gates_ok()` 与播种校验看见（卡 E60 刚把
那条修对），**假绿连看见的机会都没有**。这与卡 E60（两把尺子）、E61（翻不动就不出声）
是同一个病：判不出来的时候当没事。

四条判据（见 `复盘/卡/卡E62-一条都没挑中的时候不许说全绿.md`）：
1. `render_check.mjs --only <零匹配>` ⇒ 退非零，且**点名**（打出现有全部视图名）。
2. `--only <真视图>` ⇒ 真采到（`pass1.size > 0`）且退 0 ——「红」和「绿」两侧都要有读数，
   否则撤掉判据 1 时判据 2 靠旧行为也能过（空真钉子自己也会空真，见卡 E61 的教训）。
3. 两道门的判据写在一处、被一条钉子钉住一致（本文件 + `_ONLY_SELECTORS`）。
4. `--force --update --only <零匹配>` 不许写出 `gates/render/LAST_UPDATE.md` 的空记录。

★★ 反向验证要求（照卡 E61 的教训）：每条「退非零」都必须**先记录撤回前的基线读数**，
撤回后再看它翻成非零。两次读数都要进卡里 —— 只断言「非零」可能被邻近的别的守卫喂饱
（`render_check.mjs` 里还有 node 不在、假时钟没钉住、确定性自检失败等早退路径）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "tools" / "render_check.mjs"
FLOW = ROOT / "tools" / "ui_flow_check.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="环境里没有 node（这两道门本来就跑不了）")

#: 两道门里「`--only` 零匹配 ⇒ 退 1」的**唯一**判定点。每处都必须写清是什么。
#: 扫出但**不是**这条语义的行进 `_NOT_A_ONLY_SELECTOR`，每条也要写理由 ——
#: 少一条会红（漏判），多一条也会红（白名单不许悄悄膨胀成「什么都放行」）。
_ONLY_SELECTORS = {
    "tools/render_check.mjs": ("selectedViews", "渲染层：`--only` 挑视图的唯一判定点"),
    "tools/ui_flow_check.mjs": ("selectedFlows", "行为流层：`--only` 挑流的唯一判定点"),
}

#: 扫出但**不是**「挑哪几个」这种判定点的行 —— 每条都必须写清为什么不是。
_NOT_A_ONLY_SELECTOR: dict[str, str] = {}

#: 两道门对「零匹配」的退出码必须相同。为什么是 1 而不是 3：3 是 NOT RUN，它在这一档门里
#: 会被 `REUSABLE` 与播种校验当成「不算红」—— 那正是本卡要消灭的静默。
_EXPECTED_CODE = 1


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def run_render(*args: str) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(RENDER), *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


# ---------------------------------------------------------------- 判据 1：零匹配必须红

def test_render_only_with_no_match_exits_nonzero() -> None:
    """★ 判据 1：`--only` 一个视图都没匹配上 ⇒ 退非零，并且**点名**。

    病灶原文（HEAD `ab66da19`，主控 2026-10-28 亲自复现，不是转述）：
        [OK ] 0 份清单与黄金逐字节一致（3 档宽度 × 14 个视图 + 1 个浮层）
        渲染验证层通过 ✅
        退出码=0
    一行里既说「0 份」又说「14 个视图」。断言必须含**那句报错原文**与**至少一个真视图名**，
    不许只断言「有报错」—— 否则任何别的守卫提前退非零都能喂饱这条。
    """
    proc = run_render("--only", "根本没有这个视图")
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"零匹配必须退非零（病灶：退 0 还打 OK 行）：{out}"
    assert proc.returncode == _EXPECTED_CODE, (
        f"退出码要与 ui_flow 一致（{_EXPECTED_CODE}）：{proc.returncode}"
    )
    assert "根本没有这个视图" in out, f"报错要点名原样参数：{out}"
    assert "一个视图都没匹配上" in out, f"要有一句人话说明发生了什么：{out}"
    # 点名：至少一个**真实**视图名要出现（照 ui_flow_check.mjs:2069 的体例逐行列出）
    real_views = ("today", "tasks", "important", "setting", "offline", "palette")
    assert any(v in out for v in real_views), f"要列出全部现有视图名（否则用户还得去翻源码）：{out}"
    # 反向：那句自相矛盾的 OK 行**不许**再出现
    assert "份清单与黄金逐字节一致" not in out, f"零匹配时不许打「逐字节一致」的 OK 行：{out}"


def test_render_only_zero_match_never_writes_the_update_log() -> None:
    """★ 判据 4：`--force --update --only <零匹配>` 不许写出 `LAST_UPDATE.md` 的空记录。

    为什么必须 `--force`：`:124` 本来就禁止 `--update` 与 `--only` 合用（T-G51 实测采到过
    错黄金）。但 `--force` 放行之后，零匹配会走到 `:552 if (ARGS.update)` 分支：
    `changed` 与 `gone` 都空（`--only` 时 `gone` 被跳过）⇒ 往日志里追加一条「0 份改动」
    的假记录并退 0。判据 = 零匹配在**写之前**就拦下。

    用「字节一字不变」而不是「新版块没出现」：后者要解析 markdown，前者骗不了人。
    """
    log = ROOT / "gates" / "render" / "LAST_UPDATE.md"
    before = log.read_bytes() if log.exists() else None

    proc = run_render(
        "--force", "--update", "--only", "根本没有这个视图", "--reason", "本卡的反向验证"
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"零匹配 + --update 也不许退 0：{out}"

    after = log.read_bytes() if log.exists() else None
    if before is None:
        assert after is None, "零匹配时不许**新建** LAST_UPDATE.md"
    else:
        assert after == before, (
            "零匹配时不许往 LAST_UPDATE.md 追加「0 份改动」的假记录 —— "
            f"前 {len(before)} B / 后 {len(after) if after else 0} B"
        )


# ---------------------------------------------------------------- 判据 2：匹配到必须真采到
#
# 这条要真起服务 + 真起浏览器（约 10 秒）。它与判据 1 配对：**「红」和「绿」两侧都要有
# 真读数**。为什么绿侧不能省：撤掉判据 1 时，判据 2 靠 `--only today` 的旧行为也能过 ——
# 一个只测「红的会红」的钉子，在有人把整段判据删掉时**不会响**。
def _golden_host_reason() -> str | None:
    """金样本绑在哪台机器上？不是本机 ⇒ 返回理由。

    ★ 与 `scripts/run_gates.py` 的 `golden_host_reason()` **同一份判据**（卡 E63）：金样本
      `gates/render/*.txt` 是采集机的显示栈渲出来的，字形度量随 Edge 版本 / 字体 / DPI 变。
      在别的机器上比逐字节**没有意义** —— 那不是回归，是「这台机器做不到这件事」。
    """
    import run_gates as rg

    return rg.golden_host_reason("render")


@pytest.mark.parametrize("view", ["today"])
def test_render_only_with_a_real_view_captures_at_least_one(view: str) -> None:
    """★ 判据 2：`--only <真视图>` ⇒ 采到 ≥1 份（3 档宽度 ⇒ 3 份）且退 0。"""
    why = _golden_host_reason()
    if why:
        pytest.skip(f"金样本主机专用（卡 E63）：{why}")
    proc = run_render("--only", view)
    out = proc.stdout + proc.stderr
    if "找不到真浏览器" in out or "CDP 端点连不上" in out:
        pytest.skip("这台机器起不了真浏览器（render 层本来就 NOT RUN）—— 绿侧读数不成立，不算失败")
    assert proc.returncode == 0, f"挑中真视图必须退 0：{out}"
    assert "份清单与黄金逐字节一致" in out, f"绿侧必须有真实的「逐字节一致」读数：{out}"
    # 采到的是 3 档宽度 × 1 个视图 = 3 份。不许是 0（那正是本卡要消灭的空真）。
    assert "(3 档宽度" in out or "3 档" in out, f"挑中 today 应采 3 份（3 档宽度）：{out}"
    assert "0 份清单与黄金" not in out, f"挑中了却采到 0 份 —— 空真又回来了：{out}"


# ---------------------------------------------------------------- 判据 3：两道门必须一致

def _selector_lines(rel: str, name: str) -> list[tuple[int, str]]:
    """在 `rel` 里找 `name` 的定义行与它内部 `return ...filter(...)` 的行。"""
    lines = _src(ROOT / rel).splitlines()
    hits: list[tuple[int, str]] = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        if f"function {name}(" in s or (".filter(" in s and not s.startswith("//")):
            hits.append((n, s))
    return hits


def test_both_doors_have_an_only_selector() -> None:
    """★ 判据 3（a）：两道门都要有「挑哪几个」的**唯一**判定点。

    为什么这算判据：E62 之前 `render_check.mjs` 是**内联过滤**（`:335` 的
    `if (ARGS.only && ARGS.only !== view) continue`），而 `ui_flow_check.mjs` 早就抽出了
    `selectedFlows()`。一处有名字、一处内联 —— 于是「零匹配怎么办」只能各写各的。
    抽成同名同形的函数，才谈得上「必须说同一句话」。
    """
    missing: list[str] = []
    for rel, (name, what) in _ONLY_SELECTORS.items():
        if not (ROOT / rel).is_file():
            missing.append(f"{rel} 不存在（{what}）")
            continue
        if f"function {name}(" not in _src(ROOT / rel):
            missing.append(f"{rel} 里找不到 function {name}(（{what}）")
    assert not missing, "两道门都要有挑视图/流的唯一判定点：\n  " + "\n  ".join(missing)


def test_both_doors_return_the_same_code_on_zero_match() -> None:
    """★ 判据 3（b）：零匹配的退出码两边都必须是 1。

    病灶：一道门说「一条都没挑中就红」，另一道门说「挑中 0 个就绿」——
    **没有任何一处钉住这两道门对同一件事说同一句话**，这与卡 E60 挖出的五处同型。

    读法：判定点是「挑中的数量 === 0 ⇒ result.code = 1」，写在 `main()` 开头
    （**不在**选择器函数里 —— 选择器只负责挑，不负责判）。所以这里扫的是
    「`selectedXxx().length === 0` + `code = 1`」这一对，两个文件都要有。
    """
    problems: list[str] = []
    for rel, (name, what) in _ONLY_SELECTORS.items():
        src = _src(ROOT / rel)
        # ① 必须存在「挑中的数量 === 0」这个形状
        if f"{name}().length === 0" not in src and f"{name}().length == 0" not in src:
            problems.append(f"{rel}：没有 `{name}().length === 0` 这个零匹配判定（{what}）")
        # ② 该判定之后必须真的退 _EXPECTED_CODE
        idx = src.find(f"{name}().length === 0")
        if idx >= 0:
            window = src[idx : idx + 1200]
            # 两种写法都认：`result.code = 1` 后 return，或 `return { ...result, code: 1 }`。
            # 判的是语义（这个分支真的给了 1），不是某一种语句形状 —— 两道门本来就
            # 各有各的返回体例，硬统一成一种形状属于「为了钉子改产品」，不值当。
            shapes = (f"code = {_EXPECTED_CODE}", f"code: {_EXPECTED_CODE}")
            if not any(s in window for s in shapes):
                problems.append(
                    f"{rel}：零匹配分支之后 1200 字符内没有 `code = {_EXPECTED_CODE}`"
                    f" 或 `code: {_EXPECTED_CODE}`（读到：{window[:100]!r}）"
                )
    assert not problems, (
        f"两道门对「--only 零匹配」必须说同一句话（都退 {_EXPECTED_CODE}）：\n  "
        + "\n  ".join(problems)
    )


def test_the_allow_list_says_why() -> None:
    """判据 3（c）：白名单自己也要被钉住 —— 每条都要写理由，且必须**真的**出现在源码那一行。

    照卡 E60 判据 6 的 `_NOT_A_RED_RULER` 体例。白名单为空是合法的（现在就是空，
    因为 AST/正则层面没有别的行长得像这条语义），但一旦填了就必须是活的。
    """
    bad: list[str] = []
    for key, why in _NOT_A_ONLY_SELECTOR.items():
        rel, _, num = key.rpartition(":")
        if rel not in _ONLY_SELECTORS:
            bad.append(f"{key}: 不在扫描范围里（白名单写了没用）")
            continue
        if not str(why).strip():
            bad.append(f"{key}: 没写理由")
        lines = _src(ROOT / rel).splitlines()
        if not (num.isdigit() and 1 <= int(num) <= len(lines)):
            bad.append(f"{key}: 行号越界（文件共 {len(lines)} 行）")
            continue
        if not lines[int(num) - 1].strip():
            bad.append(f"{key}: 那一行是空的 —— 白名单过期")
    assert not bad, "白名单有不能自证的行：\n  " + "\n  ".join(bad)


# ---------------------------------------------------------------- 判据 4：--update 位置

def test_zero_match_check_sits_before_the_update_branch() -> None:
    """★ 判据 4（静态侧）：零匹配检查必须**在** `if (ARGS.update)` 分支之前。

    动态侧由 `test_render_only_zero_match_never_writes_the_update_log` 证明
    （真的没写）。这条静态钉子加一道：把检查挪到后面时，动态那条也能抓 —— 但静态这条
    会**点名说「位置错了」**，而动态那条只会说「日志被写了」。两条都留，理由同卡 E60：
    能诊断的失败比只说「失败了」值钱。
    """
    src = _src(RENDER)
    check = src.find("一个视图都没匹配上")
    update = src.find("if (ARGS.update) {")
    assert check > 0, "找不到零匹配检查段"
    assert update > 0, "找不到 --update 分支"
    assert check < update, (
        f"零匹配检查（第 {src[:check].count(chr(10)) + 1} 行）必须在 --update 分支"
        f"（第 {src[:update].count(chr(10)) + 1} 行）**之前** —— 否则会先写出空记录再红"
    )
