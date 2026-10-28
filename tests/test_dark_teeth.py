"""暗色护栏自证（T-G175）：把 069 的**一次性**反证变成**常驻**自证。

## 为什么要这一份

只读复核 RI10（`gates/diag/复核报告-RI10-集成八张.md:111`）明写它**没能验证**的第一条：
「流㉚『改坏会红』的动态实证」—— 复核禁令**不许改文件**，只做了静态判读 + 采信 069 台账的反证读数。
也就是说：「有人把暗色改坏 → 门禁会红」这件事，之后**没人能独立复现**（复核者不许改文件）。

这份自证让**任何只读的人**都能跑出「改坏 → 必红」，而且**全程不动仓库**：
变异只落在 `tmp_path` 的**临时副本**里（静态层，见下），活体层由
`tools/dark_probe.mjs --mutate <令牌>=<值>` 在**运行期**注入（不改任何文件）。

## 五条自证（每条都先断言「变异确实生效」—— 变异后文本 ≠ 原文，否则会出假红/假绿）

1. **不恒真（基线）**：真 `app.css` → 暗色零欠账（证明这套自证不是「永远红」的摆设）；
2. **对比度变异必红**：暗色 `--ink` 改成与暗色 `--bg` **同值** → 暗色必出现不达标；
3. **令牌缺失变异**：删掉暗色块里某个令牌 → 由**哪一层**的真入口抓到（实测两条，见函数注释）；
4. **整块消失变异**：删掉整个 `[data-theme="dark"] { … }` 块 / 清空它 → 实测两副面孔（见函数注释）；
5. **自证不许动仓库**：跑前/跑后 `sha256(src/web/app.css)` 一致、
   `git status --porcelain` 不多出文件。

★ 判据一律用**真工具的同一批函数**（`contrast_audit.token_blocks` / `evaluate` /
  `declared_pairs` …）与**真入口**
  （`test_web_frontend.test_css_tokens_exist_and_cover_both_themes`），**不复刻一份判据**。
★ 抓不到的格**如实记**（见 `复盘/暗色护栏自证-T-G175.md`）；**不为让它变绿而放宽任何判据**。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import contrast_audit as ca  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
import test_web_frontend as twf  # noqa: E402 —— 存在性层的**真入口**就在这个测试模块里
import web_live_check as wlc  # noqa: E402 —— 暗色必需令牌集合 / 取真暗色块的切法（T-G177 共用一份）

# `contrast_audit.token_blocks` 用的同一条正则 —— 真暗色规则就是它。
DARK_RULE = re.compile(r'\[data-theme="dark"\]\s*\{(.*?)\n\}', re.S)


# ---------------------------------------------------------------- 零件：改坏（全部只作用于字符串）
def _real_css() -> str:
    """真 `app.css` 的**文本**（只读，不写）。"""
    return ca.CSS.read_text(encoding="utf-8")


def _dark_rule(css: str) -> re.Match[str]:
    m = DARK_RULE.search(css)
    assert m is not None, "真 app.css 里找不到 [data-theme=dark] 令牌块"
    return m


def _set_dark_token(css: str, token: str, value: str) -> str:
    """把暗色块里 `token` 的值改成 `value`（只改字符串，丢弃返回值即无痕）。"""
    m = _dark_rule(css)
    body, n = re.subn(rf"(?m)^(\s*{re.escape(token)}\s*:)[^;]+;", rf"\g<1> {value};", m.group(1))
    assert n == 1, f"暗色块里 {token} 应恰好有一处声明，实测 {n} 处"
    out = css[: m.start(1)] + body + css[m.end(1) :]
    assert out != css, "变异没生效（文本没变）—— 会出假红/假绿"
    return out


def _del_dark_token(css: str, token: str) -> str:
    """删掉暗色块里 `token` 那一行声明。"""
    m = _dark_rule(css)
    body, n = re.subn(rf"(?m)^\s*{re.escape(token)}\s*:[^;]+;\s*\n", "", m.group(1))
    assert n == 1, f"暗色块里 {token} 应恰好有一处声明，实测 {n} 处"
    out = css[: m.start(1)] + body + css[m.end(1) :]
    assert out != css, "变异没生效"
    return out


def _empty_dark_block(css: str) -> str:
    """把暗色块**清空**（保留选择器 `[data-theme="dark"] {}`）—— 比整块删掉更阴的一种改坏。"""
    m = _dark_rule(css)
    out = css[: m.start(1)] + "\n" + css[m.end(1) :]
    assert out != css and len(out) < len(css), "变异没生效"
    return out


def _remove_dark_block(css: str) -> str:
    """删掉**整个** `[data-theme="dark"] { … }` 规则（连选择器一起）。"""
    m = _dark_rule(css)
    out = css[: m.start()] + css[m.end() :]
    assert out != css and DARK_RULE.search(out) is None, "变异没生效"
    return out


# ---------------------------------------------------------------- 零件：跑真判据
def _dark_shortfalls(css: str) -> list[str]:
    """跑**真对比度判据**（`token_blocks` + `evaluate` + 真登记表），返回暗色不达标的 key。"""
    tokens = ca.token_blocks(css)
    pairs = ca.dedupe(ca.declared_pairs() + ca.badge_pairs(css) + ca.state_pairs(css))
    rows = ca.evaluate(pairs, tokens, ca.load_baseline())
    return [r.pair.key for r in rows if r.pair.theme == "dark" and r.ratio < r.pair.minimum]


def _existence_layer_catches(tmp_path: Path, css: str) -> bool:
    """跑**真入口** `test_web_frontend.test_css_tokens_exist_and_cover_both_themes`，
    把它读的 `WEB_CSS` 常量指到临时副本上 → True = 它抓到了（红），False = 它放过了（绿）。

    ★ 不复制它的判据：直接调它那个测试函数本体，只是换了它读的文件。
    """
    p = tmp_path / "app.css"
    p.write_text(css, encoding="utf-8")
    old = twf.WEB_CSS
    twf.WEB_CSS = p
    try:
        twf.test_css_tokens_exist_and_cover_both_themes()
    except AssertionError:
        return True
    finally:
        twf.WEB_CSS = old
    return False


def _git_status() -> set[str]:
    """★ T-G194：只看**已跟踪、且不在 `gates/` 下**的改动。

    为什么不是「`git status --porcelain` 全文」：这一层要证的是「**变异实验没动仓库里的真文件**」，
    而 `git status` 是个**全局可变视图** —— 满载并行跑门禁时，`gates/**`（门禁自己的产物：
    `gates/last.json` / `gates/reuse.json`）与工作区里的**未跟踪残留**（`data/` 之类）会在
    **两次快照之间**变来变去，于是这条断言以「**差集是空的**」这种说不出道理的方式假红
    （实测 2026-10-01：断言失败但 `after - before == []`，即"少了"而不是"多了"）。
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        check=True,
    )
    out = set()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')          # porcelain 是「XY <path>」
        if path.startswith("gates/"):
            continue
        out.add(line)
    return out


# ---------------------------------------------------------------- 自证①：不恒真（基线）
def test_1_baseline_dark_theme_is_clean() -> None:
    """自证①不恒真：真 `app.css` 的暗色**零欠账** —— 证明这套自证不是「永远红」的摆设。"""
    assert _dark_shortfalls(_real_css()) == []


# ---------------------------------------------------------------- 自证②：对比度变异必红
def test_2_contrast_mutation_turns_dark_red() -> None:
    """自证②：把暗色 `--ink` 改成与暗色 `--bg` **同值**（字和底一个色 → 看不见）→ 暗色必不达标。"""
    css = _real_css()
    dark = ca.token_blocks(css)["dark"]
    assert dark["--ink"] != dark["--bg"], "前提不成立：暗色的字色与底色本来就一样"
    bad = _dark_shortfalls(_set_dark_token(css, "--ink", dark["--bg"]))
    assert "dark:--ink on --bg" in bad, f"改坏没被抓到：{bad}"


# ---------------------------------------------------------------- 自证③：令牌缺失变异
def test_3_missing_dark_token_is_caught_by_contrast_layer() -> None:
    """自证③a：删掉暗色块的 `--panel-2`（它落在被判的暗色组合里）→ **对比度层**抓得到。

    为什么是 `--panel-2`：删掉它之后暗色块会**回落到亮色的** `--panel-2`（近白），
    而暗色的字色是浅色 —— `--ink on --panel-2` 等组合当场不达标。正是「改坏必红」。
    """
    bad = _dark_shortfalls(_del_dark_token(_real_css(), "--panel-2"))
    assert "dark:--ink on --panel-2" in bad, f"删了暗色 --panel-2 却没红：{bad}"


def test_3b_decoration_only_token_deletion_is_now_caught_by_existence_layer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """自证③b（★ T-G177 把 080 的「抓不到」**翻面**：记录保留，判据反过来）：删掉暗色
    只被「纯装饰」表用到的 `--border`。

    ★ **修之前（080 实测）**：删掉 `--border` → 对比度层**绿**（`--border` 只在
    `AA_NONTEXT_EXEMPT` 装饰档，只记录不判）**且存在性层也绿**（它读错了区域）→
    「今日没有任何静态层抓得到删掉一个装饰类暗色令牌」——080 如实登记在
    `复盘/暗色护栏自证-T-G175.md` §二·抓不到的格 D。
    ★ **修之后（本卡 T-G177 实测）**：存在性层改用令牌层同一条切法取**真暗色块**、
      且只看暗色块**自己声明**的令牌 → `--border` 一被删就红（见下断言）。
    对比度层这半仍是绿（它的口径没变）——两段都留在这里，作为这条"假护栏"的证据链。
    """
    css = _real_css()
    mutated = _del_dark_token(css, "--border")
    assert mutated != css, "变异没生效"
    # 080 的记录：对比度层抓不到（`--border` 是装饰档，只记录不判）—— 口径没变，保留
    assert _dark_shortfalls(mutated) == [], "对比度层居然抓到了 —— 记录该更新"
    # ★ 本卡翻面：存在性层**现在必须抓到**
    assert _existence_layer_catches(tmp_path, mutated), (
        "存在性层没抓到删掉的 --border —— 假护栏又回来了"
    )


# ---------------------------------------------------------------- 自证④：整块消失变异
def test_4_whole_dark_block_removed_makes_contrast_audit_error_not_silently_green() -> None:
    """自证④a —— ★ **实测推翻卡里的预判**：删掉整个 `[data-theme="dark"] { … }` 块后，
    `contrast_audit` **不是绿** —— `token_blocks` 直接 `SystemExit`（找不到暗色令牌区）。

    卡 §2.2.4 预判「`contrast_audit` 这一层仍然会绿（暗色 = `{**light, **dark_delta}`，
    块没了 = 全用亮色令牌）」—— **预判错了**：块**连选择器一起没了**，正则在第一步就找不到它，
    于是报错退出（非零），不是悄悄绿。真正会「悄悄绿」的是**清空块体**那种（见 ④b）。
    """
    with pytest.raises(SystemExit):
        ca.token_blocks(_remove_dark_block(_real_css()))


def test_4b_emptied_dark_block_is_now_caught_by_existence_layer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """自证④b（★ T-G177 翻面：记录保留，判据反过来）：把暗色块**清空**
    （保留选择器 `[data-theme="dark"] {}`）。

    这是比「整块删掉」**更阴**的一种改坏（选择器还在，看着像暗色还接线着）。
    ★ **修之前（080 实测）**：`contrast_audit` 拿到的暗色 = 亮色（本来就全过）→ **绿**；
      存在性层也**绿**（它的暗色块取法撞上文件头注释，切到的是 `:root` 亮色块）→
      「今日没有任何静态层抓得到暗色块被清空」——080 如实登记在
      `复盘/暗色护栏自证-T-G175.md` §二·抓不到的格 E。
    ★ **修之后（本卡 T-G177 实测）**：存在性层取真暗色块 → 清空后块里零令牌，必需令牌全缺 → 红。
    对比度层这半仍是绿（暗色 = `{**light}` 全用亮色令牌，亮色本来就全过）——两段都留作证据链。
    """
    css = _real_css()
    emptied = _empty_dark_block(css)
    assert emptied != css, "变异没生效"
    assert _dark_shortfalls(emptied) == [], "对比度层居然抓到了 —— 记录该更新"
    # ★ 本卡翻面：存在性层**现在必须抓到**
    assert _existence_layer_catches(tmp_path, emptied), (
        "存在性层没抓到被清空的暗色块 —— 假护栏又回来了"
    )


def test_4c_existence_layer_now_reads_the_real_dark_block() -> None:
    """★ 修前 / 修后对照（T-G177 翻面；历史痕迹保留）。

    ★ 修前（080 实测）：存在性层取暗色块写的是
        dark = css.split('[data-theme="dark"]', 1)[1].split("}", 1)[0]
      但 `app.css` 的**文件头注释**（第 6 行）先出现了 `[data-theme="dark"]` 这句话，
      于是它切到的是"注释之后到第一个 `}`" = 整个 `:root` **亮色**块 ——
      真暗色块的令牌区永远不在其中（④b 从行为上证过：清空暗色块它仍绿）。
    ★ 修后（本卡实测）：改用令牌层同在用的切法取真暗色块；下面对"它现在取到的是真暗色块"直接取证。
    """
    css = _real_css()
    # —— 反例（保留）：旧的 split 确实落在亮色 :root 块上，且不含真暗色块的令牌区
    old_region = css.split('[data-theme="dark"]', 1)[1].split("}", 1)[0]
    assert ":root {" in old_region, "旧切法的反例失效了 —— 请更新这条记录"
    first_decl = _dark_rule(css).group(1).strip().splitlines()[0].strip()
    assert first_decl not in old_region, "旧切法居然切到了真暗色块 —— 记录不成立，请更新"

    # —— 修后：新切法取到的是真暗色块（含暗色专属的 color-scheme: dark、不含 :root {）
    dark_text = wlc.dark_block_text(css)
    assert ":root {" not in dark_text, "新切法又切到亮色块了 —— 修真失败"
    assert "color-scheme: dark" in dark_text, "新切法没取到真暗色块"
    assert first_decl in dark_text, "新切法没取到真暗色块的令牌区"

    # 现跑证据：真暗色块的令牌数 + 必需令牌都在（`--panel-2` 就在其中）
    declared = wlc.dark_declared_tokens(css)
    assert set(wlc.DARK_REQUIRED_TOKENS) <= declared, f"真暗色块令牌不全：{sorted(declared)}"
    assert len(declared) >= 10, f"真暗色块令牌数异常偏少：{len(declared)}，可能切错了块"
    print(
        f"[T-G177 现跑] 旧切法区域含 ':root {{' = {':root {' in old_region}；"
        f"真暗色块令牌数 = {len(declared)}（含 --panel-2 = {'--panel-2' in declared}）"
    )


# ---------------------------------------------------------------- 自证⑤：自证不许动仓库
def test_5_self_proof_never_touches_the_repo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """自证⑤：跑自证前后 `sha256(src/web/app.css)` 一致、`git status --porcelain` 不多出文件。

    把五种变异都在临时副本上做一遍（并真的跑判据），最后证明**真文件与工作区一个字节没动**。
    """
    before_hash = hashlib.sha256(ca.CSS.read_bytes()).hexdigest()
    before_status = _git_status()

    css = _real_css()
    dark_bg = ca.token_blocks(css)["dark"]["--bg"]
    variants = {
        "set": _set_dark_token(css, "--ink", dark_bg),
        "del_judged": _del_dark_token(css, "--panel-2"),
        "del_decoration": _del_dark_token(css, "--border"),
        "empty": _empty_dark_block(css),
        "remove": _remove_dark_block(css),
    }
    for name, text in variants.items():
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "app.css").write_text(text, encoding="utf-8")
        if name != "remove":  # remove 后 token_blocks 会 SystemExit，跳过（④a 单独验过）
            _dark_shortfalls(text)

    assert hashlib.sha256(ca.CSS.read_bytes()).hexdigest() == before_hash, "自证改了真 app.css！"
    after_status = _git_status()
    assert after_status == before_status, (
        "自证动了工作区（只看已跟踪、非 gates/ 的改动）："
        f"多了 {sorted(after_status - before_status)}；"
        f"少了 {sorted(before_status - after_status)}"
    )


def test_6_the_status_snapshot_ignores_gate_artifacts_and_untracked() -> None:
    """★ T-G194：快照口径本身要有钉子 —— 不许把 `gates/**` 与 `??`（未跟踪）算进来。

    这条是**反空转**：口径一旦被改回“全文 `git status`”，下面两条断言会当场红
    （本仓 `gates/last.json` / `gates/reuse.json` 在门禁跑动中本来就被改着）。
    """
    snap = _git_status()
    assert all("gates/" not in ln for ln in snap), f"快照里混进了门禁产物：{snap}"
    assert all(not ln.startswith("??") for ln in snap), f"快照里混进了未跟踪文件：{snap}"
