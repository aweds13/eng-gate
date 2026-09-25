"""对比度审美门（T-G27）—— 令牌层的 WCAG 对比度「棘轮」。

## 为什么是"棘轮"而不是一把硬门

`SR-NF1`（视觉美感）在 2026-09-23（T-G26）钉住了 workbench 判据之后，第一次能量出：
**亮色主题有一批「字在底上看不清」的组合**（最糟的是徽标里用同一个状态色写字，1.96:1）。
但那些值**不能在本卡里改** —— 改令牌就是改视觉，而视觉重构那条线用户还没开。

于是这里做一个**棘轮**：现状**一条不放过地登记**（`tools/contrast_baseline.toml`，
逐条写清"为什么现在是这样、打算怎么修"），然后**只许变好、不许变坏**：

- 出现**没登记过**的对比度不足 → **FAIL**（新欠账必须走登记，不许悄悄加）
- 登记过的组合**比登记值还差** → **FAIL**（悄悄改坏了会被抓）
- 登记过的组合**已经达标** → 提示"这条可以从登记表里删掉了"（不 FAIL）

这样它现在就能挡住"改令牌把字改糊"，等视觉线把颜色修完，登记表逐条清空，
`--strict` 就变成一把真门（见"怎么收紧"）。

## 为什么不用浏览器

对比度是**纯计算**（WCAG 相对亮度公式），只需要令牌值。本环境没有浏览器 GUI，
这条是本项目第一条**不需要浏览器就能自动验**的审美门槛。

## 口径

- 阈值：正文 ≥ 4.5、大字（≥18.66px 粗体 或 ≥24px）≥ 3.0（WCAG AA）。
  应用里强调色**既当 44px 计时器又当 12px 小字**，所以按**最小的那个用法**取 4.5 —— 保守取法。
- 徽标（`.badge.*`）里的「底 + 字」**从 CSS 真读**：`color-mix(...)` 合成的底要先合成再算，
  直接写 `background: var(--某令牌)` 的也算（T-G42 之后状态徽标改用令牌底/圆点了）——
  这个函数存在的意义是**别漏抓**：一个原子换了个写法就整条从表里消失，那是最坏的一种"绿"。
- 令牌值只从 `src/web/app.css` 的令牌区读，**不抄表**；`var(--x)` 递归解析。
- ★ T-G45 起**悬停态也真读**（`state_pairs`）：`:hover` 规则里的「底 + 字」从 CSS 现算 ——
  底认 `var(--x)` 与两令牌 `color-mix(…)` 两种写法，字优先取同一条规则、否则取基础选择器那条。
  为什么必须自动读：悬停就是"同一条规则换个背景"，最容易加了没人算（T-G42 的同一类教训）。
  带 `transparent` 的合成底**算不了**（得知道它铺在什么上面）—— 如实跳过，不猜。
- ★ T-G42 起状态徽标把颜色交给 **8px 圆点**（workbench 的 StatusDot）。点是**非文字**
  （WCAG 只要 3.0），它借令牌级组合的地板：`--ok` / `--danger` / `--accent` 落在 `--panel` 上
  按 4.5 登记着 —— 令牌一旦被改浅，先把那三条打红，圆点自然也不够。
- ★★ T-G70 起**非文字图形自己有一张 3.0 表**（`AA_NONTEXT_PAIRS`，WCAG 1.4.11）：控制边界（输入框 /
  下拉 / 文本域的边框）、状态点、勾选圈、图表数据笔、逾期红条 —— 逐对 ≥3.0，**没有登记表**：
  控制边界看不见是缺陷不是欠账（与 T-G27 对 toast 的说法一致）。
  旁边还有一张 **`AA_NONTEXT_EXEMPT`（纯装饰）**：分隔线、卡片边、图表网格 / 环轨道 / 空格、
  悬停描边、toast 按钮边框 —— **照样把实测值打出来**，但不当判据用，理由逐条写在表里
  （`复盘/非文字对比度-T-G70.md` 列了"若用户不认，这几行是要复议的清单"）。
  ⚠️ 仍然算不了的（如实记，不假装看过）：**半透明填充**（`.chart-area` 10% /
  `.chart-fill-soft` 18% —— 合成结果取决于底下是什么，那要渲染层）、
  **悬停/选中态下的非文字**、**浏览器自己画的 checkbox/radio**（黄金里它们的 fg/bg 是空的：
  `#000000/#000000@0.00`），以及 `color-mix(…, transparent)` 那种底。

用法
  python -X utf8 tools/contrast_audit.py            # 人读（全表 + 结论）
  python -X utf8 tools/contrast_audit.py --json     # 机器读
  python -X utf8 tools/contrast_audit.py --check    # 门禁用：有新欠账/变差就退 1
  python -X utf8 tools/contrast_audit.py --strict   # 收紧后：任何不达标都退 1
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "src" / "web" / "app.css"
BASELINE = ROOT / "tools" / "contrast_baseline.toml"

AA_NORMAL = 4.5
AA_LARGE = 3.0
AA_NONTEXT = 3.0  # WCAG 1.4.11「非文字对比度」：图形与控件边界的地板
EPS = 0.02  # 四舍五入容忍：小于这个差不算"变坏"

_TOKEN = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
_VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*\)")
# `.badge.done { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok) }`
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_MIX = re.compile(r"color-mix\(\s*in\s+srgb\s*,\s*var\(\s*(--[a-z0-9-]+)\s*\)\s*([\d.]+)%")
_COLOR = re.compile(r"color\s*:\s*var\(\s*(--[a-z0-9-]+)\s*\)")
# `.badge { background: var(--panel); color: var(--muted) }` —— T-G42 起的令牌底
_BG_VAR = re.compile(r"background\s*:\s*var\(\s*(--[a-z0-9-]+)\s*\)")


@dataclass(frozen=True)
class Pair:
    """一条要算的「前景 / 背景」组合。`key` 是登记表里的稳定标识。"""

    theme: str
    fg: str
    bg: str
    minimum: float
    where: str
    # `text` = 字在底上（4.5）；`图形` = 非文字图形与控件边界（3.0，T-G70）；
    # `装饰` = 纯装饰（只量不判）
    kind: str = "text"

    @property
    def key(self) -> str:
        """登记表与报错里的稳定标识。★ 文字的 key **不带前缀**（历史行与测试都按它写），
        非文字那两类带前缀 —— 否则 `--accent on --panel` 这种"同一个令牌对既是文字又是图形"
        会被去重掉一条（而这两条量的根本不是一回事）。"""
        prefix = "" if self.kind == "text" else f"{self.kind} "
        return f"{self.theme}:{prefix}{self.fg} on {self.bg}"


@dataclass
class Row:
    pair: Pair
    ratio: float
    verdict: str  # PASS / KNOWN / FIXED / WORSE / NEW
    known: float | None = None
    why: str = ""


# ------------------------------------------------------------------ 颜色计算
def _rgb(value: str) -> tuple[float, float, float]:
    v = value.strip().lower()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise ValueError(f"看不懂的颜色：{value!r}")
        return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.fullmatch(r"rgba?\(([^)]+)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")][:3]
        return tuple(float(p) / 255 for p in parts)  # type: ignore[return-value]
    raise ValueError(f"看不懂的颜色：{value!r}")


def _hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (round(min(max(c, 0.0), 1.0) * 255) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _luminance(rgb: tuple[float, float, float]) -> float:
    def lin(x: float) -> float:
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    """WCAG 对比度（1.0 ~ 21.0）。"""
    a, b = _luminance(_rgb(fg)), _luminance(_rgb(bg))
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def mix_over(color: str, base: str, pct: float) -> str:
    """`color-mix(in srgb, color pct%, transparent)` 铺在 `base` 上的实际颜色。"""
    c, b = _rgb(color), _rgb(base)
    blended = tuple(pct * ci + (1 - pct) * bi for ci, bi in zip(c, b, strict=True))
    return _hex(blended)  # type: ignore[arg-type]


# ------------------------------------------------------------------ 令牌解析
def token_blocks(css: str) -> dict[str, dict[str, str]]:
    """从 `app.css` 抽两个令牌区（亮 `:root` / 暗 `[data-theme="dark"]`）。

    ★ **先剥注释再抽**（T-G39 踩到）：`_TOKEN` 是"从头到第一个 `;`"的正则，而注释里只要出现
    「`--某令牌: 某个值`」这种形状（写文档句时很容易），它就会把注释当声明吞下去 ——
    实测把 `--accent-ink` 的值污染成一大段说明文字，门禁报「看不懂的颜色」。
    `badge_pairs` 早就因为同一类原因剥过注释，这里补上（别再靠"注释别那么写"这种记性）。
    """
    light_m = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    dark_m = re.search(r'\[data-theme="dark"\]\s*\{(.*?)\n\}', css, re.S)
    if light_m is None or dark_m is None:
        raise SystemExit("contrast_audit：app.css 里找不到 :root / [data-theme=\"dark\"] 令牌区")
    strip = lambda block: re.sub(r"/\*.*?\*/", "", block, flags=re.S)  # noqa: E731
    light = {
        m.group(1): m.group(2).split("/*")[0].strip()
        for m in _TOKEN.finditer(strip(light_m.group(1)))
    }
    dark_delta = {
        m.group(1): m.group(2).split("/*")[0].strip()
        for m in _TOKEN.finditer(strip(dark_m.group(1)))
    }
    return {"light": light, "dark": {**light, **dark_delta}}


def resolve(name: str, tokens: dict[str, str], depth: int = 4) -> str:
    """把令牌解析成字面色值（`var(--x)` 递归，最多 4 层）。"""
    value = tokens.get(name)
    if value is None:
        raise SystemExit(f"contrast_audit：令牌区里没有 {name}")
    for _ in range(depth):
        m = _VAR.fullmatch(value.strip())
        if m is None:
            break
        value = tokens.get(m.group(1))
        if value is None:
            raise SystemExit(f"contrast_audit：{name} 引用的 {m.group(1)} 不存在")
    return value.strip()


# ------------------------------------------------------------------ 组合清单
# 令牌级组合：只登记**样式表里真出现**的搭配，`where` 写明是哪些规则造出来的。
# ★ T-G42 撤掉了三行（都写在 `contrast_baseline.toml` 的销账记录里）：
#   - `--muted on --panel-2` / `--muted on --panel-2`：那是旧徽标的底，
#     徽标改用"卡片底 + 1px 边框"之后，**这两种搭配在样式表里已经不存在了**（僵尸行必须删，
#     `tests/test_contrast_audit.py` 有一条"登记表不许有对不上的行"钉着）。
#   - `--accent on --bg`：唯一实现处是 h1 里那个装饰性 `·`（4.37，过不了 4.5），
#     T-G42 把那个类连用法一起删了 —— **样式表里没有"强调色当小字"这种搭配了**。
#     ⚠️ 残留风险如实记在 `复盘/视觉线第0.5步-对比度与状态色-T-G42.md`：静态表看不见
#        "以后有人又写一处强调色小字在页面底上"（那要有渲染层才知道谁坐在什么底上）。
TOKEN_PAIRS: tuple[tuple[str, str, float, str], ...] = (
    ("--ink", "--bg", AA_NORMAL, "body 继承色 / 页面底"),
    ("--ink", "--panel", AA_NORMAL, "卡片内正文"),
    ("--ink", "--panel-2", AA_NORMAL, "浅底上的正文（热力图空格外 等）"),
    ("--muted", "--bg", AA_NORMAL, ".sub / .hint / .empty 在页面底"),
    ("--muted", "--panel", AA_NORMAL, ".sub / .hint / 徽标（芯片底是 --panel）在卡片里"),
    ("--muted", "--panel-2", AA_NORMAL, "静音面（读数卡，T-G51）上的 .meta / .sub"),
    ("--accent", "--panel", AA_NORMAL, ".prio.mid / .flag（12px 小字）与状态点：都在卡片底上"),
    ("--accent-ink", "--accent", AA_NORMAL, ".prio.high 与主按钮：实心强调底上的字"),
    ("--danger", "--bg", AA_NORMAL, "危险色当文字（设置页「上次导出失败」那几行）"),
    ("--danger", "--panel", AA_NORMAL, "卡片里的危险色文字 / 硬考核状态点"),
    ("--ok", "--bg", AA_NORMAL, "完成色当文字"),
    ("--ok", "--panel", AA_NORMAL, "卡片里的完成色文字 / 完成状态点"),
    ("--toast-ink", "--toast-bg", AA_NORMAL, ".toast：toast 底上的字"),
)
PRESET_TOKENS = ("--accent-1", "--accent-2", "--accent-3", "--accent-4", "--accent-5", "--accent-6")


def declared_pairs() -> list[Pair]:
    """令牌级 + 强调色预设级（两套主题各来一遍）。"""
    out: list[Pair] = []
    for theme in ("light", "dark"):
        for fg, bg, minimum, where in TOKEN_PAIRS:
            out.append(Pair(theme, fg, bg, minimum, where))
        if theme == "light":  # 预设只在设置页给亮色挑（暗色另有一套 ink 色）
            # ★ T-G39 起每个预设**各自带 ink 色**：原来一律配那唯一的白色，
            #   而白字在 6 个预设上没有一个过 4.5（最差 #f59e0b 2.15）。这里改成配它自己那个，
            #   才是界面上真正会出现的搭配（不然门禁量的是一对**不存在**的组合）。
            for idx, preset in enumerate(PRESET_TOKENS, start=1):
                out.append(
                    Pair(
                        theme,
                        f"--accent-{idx}-ink",
                        preset,
                        AA_NORMAL,
                        "设置页换成这个预设后，实心强调底上的字（.prio.high / 主按钮）",
                    )
                )
    return out


def badge_pairs(css: str) -> list[Pair]:
    """从 `.badge.*` 规则里读出「底 + 字」这种搭配。

    两种底都认：
      - `color-mix(in srgb, <状态色> N%, transparent)` —— 合成底（T-G27 的第一版配方）；
      - `background: var(--某令牌)` —— 令牌底（T-G42 起的配方）。
    ★ **为什么要两种都认**：这个函数是"别漏抓"的那道保险。一个原子换了写法就整条从表里消失，
      门会显得是绿的 —— 那正是最坏的一种绿（T-G27 自己就在注释被吃进选择器上栽过一次）。
    """
    out: list[Pair] = []
    # 先把注释去掉：否则注释会被算进选择器里（`.badge.done` 头上正好有一行注释，
    # 第一版就是这么漏掉 done/doing 的 —— 只抓到 .hard，因为只有它头上没有注释）。
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selector, body in _RULE.findall(stripped):
        sel = selector.strip().split(",")[-1].strip().replace("\n", " ")
        if not re.fullmatch(r"\.badge\.[a-z-]+", sel):
            continue
        m_color = _COLOR.search(body)
        if m_color is None:
            continue
        m_mix = _MIX.search(body)
        m_bg = _BG_VAR.search(body)
        if m_mix is not None:
            pct = float(m_mix.group(2))
            bg = f"mix({m_mix.group(1)} {m_mix.group(2)}% over --panel)"
            where = f"{sel}：底是 {pct:.0f}% 状态色合成的浅底，字却用同一个状态色"
        elif m_bg is not None:
            bg = m_bg.group(1)
            where = f"{sel}：底是令牌 {m_bg.group(1)}，字用 {m_color.group(1)}"
        else:
            continue
        for theme in ("light", "dark"):
            out.append(Pair(theme, m_color.group(1), bg, AA_NORMAL, where))
    return out


# `color-mix(in srgb, var(--a) N%, var(--b))` —— **两个令牌**的合成（T-G45 的悬停底）。
# 与上面 `_MIX` 的区别：那种写法带 `transparent`，得知道它铺在什么上面才算得出来（要渲染层）；
# 这种是两个不透明色相掺，**自己就是最终颜色**，所以静态算得了。
_MIX2 = re.compile(
    r"color-mix\(\s*in\s+srgb\s*,\s*var\(\s*(--[a-z0-9-]+)\s*\)\s*([\d.]+)%\s*,"
    r"\s*var\(\s*(--[a-z0-9-]+)\s*\)\s*\)"
)
_STATE_SUFFIX = re.compile(r":hover|:focus-visible|:not\([^)]*\)")


def _selectors(rule_selector: str) -> list[str]:
    """一条规则可能写了好几个选择器（`,` 分组）—— 拆开逐个看，别当成一个怪名字。"""
    return [s.strip().replace("\n", " ") for s in rule_selector.split(",") if s.strip()]


def state_pairs(css: str) -> list[Pair]:
    """从 `:hover` 规则里读出「悬停态的字 / 底」组合（T-G45）。

    为什么要有这个函数、而不是再手写一张表：**T-G42 的血泪** —— 一个原子换个写法就整条从
    表里消失，门会显得是绿的（那是最坏的一种绿）。悬停态恰恰是"同一条规则里换个背景"，
    最容易加了没人算。所以这里**从 CSS 真读**：

      - 底只认两种写法：`background: var(--x)`，或 `color-mix(in srgb, var(--a) N%, var(--b))`
        （两令牌 = 不透明，算得了）。`…%, transparent` 那种算不了 —— 如实跳过，不假装看过。
      - 字优先取**同一条规则**里的 `color`；没写就取**基础选择器**（剥掉 `:hover` / `:not(...)`）
        那条规则的字 —— 因为悬停只换底、字是从基础规则继承来的，那正是真正会出现的搭配。
    """
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    parsed = [(s, body) for sel, body in _RULE.findall(stripped) for s in _selectors(sel)]

    base_fg: dict[str, str] = {}
    for sel, body in parsed:
        if ":hover" in sel:
            continue
        m = _COLOR.search(body)
        if m is not None:
            base_fg.setdefault(_STATE_SUFFIX.sub("", sel).strip(), m.group(1))

    out: list[Pair] = []
    for sel, body in parsed:
        if ":hover" not in sel:
            continue
        m_color = _COLOR.search(body)
        fg = m_color.group(1) if m_color else base_fg.get(_STATE_SUFFIX.sub("", sel).strip())
        if fg is None:
            continue
        m_mix, m_bg = _MIX2.search(body), _BG_VAR.search(body)
        if m_mix is not None:
            bg = f"mix({m_mix.group(1)} {m_mix.group(2)}% over {m_mix.group(3)})"
        elif m_bg is not None:
            bg = m_bg.group(1)
        else:
            continue
        for theme in ("light", "dark"):
            out.append(Pair(theme, fg, bg, AA_NORMAL, f"{sel}：悬停时的字 / 底"))
    return out


# ---------------- 非文字图形（T-G70，WCAG 1.4.11）
# 为什么单列一张表、而不是把阈值改成 3.0 混进上面那张：**管的东西不一样**。
#   · 上面那张管「字读不读得出来」（1.4.3，4.5）；这张管「**不看字**能不能认出控件、
#     读懂图形」（1.4.11，3.0）。
#   · 同一对令牌可能两边都要（`--accent on --panel` 既是"强调色小字"又是"勾选圈的边"），
#     而它们的**角色不同、失败后的修法也不同**，所以 `key` 带 `图形` 前缀、分开判、分开报。
# ★ 这张表**没有登记表**：控制边界看不见是**缺陷**不是欠账（T-G27 对 toast 用的是同一句话）。
AA_NONTEXT_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "--border-control",
        "--panel",
        "输入框 / 下拉 / 文本域（`.new input` / 元素级 `input:not(...)` / `select` / "
        "`.field input` / `.textarea`）：框的底与卡片底**同为 `--panel`**，"
        "边框是「这里能输入」的**唯一**线索",
    ),
    (
        "--border-control",
        "--bg",
        "模态与命令面板里的输入框（`.modal-box input` / `.palette-box input`）：底是 `--bg`，"
        "边框要同时与外面的 `--panel` 分得开",
    ),
    (
        "--accent",
        "--panel",
        "完成勾选圈 `.check`（2px 边 + 选中填充）、状态点 `.badge .dot`、"
        "图表数据笔（`.chart-line` / `.chart-ring-progress` / `.chart-mark` / `.chart-cell-done`）",
    ),
    (
        "--accent",
        "--panel-2",
        "落在静音面（读数卡）上的图表数据笔：`.chart-cell-done` / `.chart-cell-missed` / "
        "`.chart-fill-soft` / `.bar-fill` 落在 `.bar-track` 上",
    ),
    ("--ok", "--panel", "「已完成」的 8px 状态点（`.badge.done .dot`）"),
    (
        "--danger",
        "--panel",
        "「逾期 / 硬考核」的左红条（`.card.overdue` / `.card.hard`）与危险按钮的边框（`.danger`）",
    ),
    ("--ink", "--panel", "已选中的强调色取样圈（`.swatch.on` 的 2px 描边）"),
    (
        "--muted",
        "--panel",
        "拖拽手柄 `.grab`（T-G79 今天清单的顺序）：它是个**控件级**提示 —— 看不见这三根竖条，"
        "就不知道这里能按住拖（与 `.check` 那条同一个道理：不看字也得认出控件）",
    ),
)

# 纯装饰：**照样量、照样打印实测值，但不当判据**。
# WCAG 1.4.11 明文把这些排在范围外（"pure decoration"）；而把它们全提到 3.0 会毁掉界面本身
# （最直接的一例：把 365 个热力图空格画成 3.0 的灰）。**这一列是判断不是测量** ——
# 每条的「为什么不算」都写在行里，`复盘/非文字对比度-T-G70.md` 里也列了复议清单。
# ★ `tests/test_contrast_nontext.py` 有两条钉着它：① 条数被冻结（加一条必须动断言）；
#   ② 每条**必须真的低于 3.0**（哪天它够了，就得从这张表里删掉，别留着当"假豁免"）。
# ★★ 这张表比上面那张**多一栏 `themes`**：豁免是**逐条**的判断，而判断可能只在某一个主题成立。
#    第一版就在这儿踩了一次 —— 亮色的 toast 底是 `--ink`（9.37，本来就过），只有**暗色**的 toast
#    底才退到 `--panel-2`（1.48）；不写清主题，就会对着一个**亮色里不存在**的搭配写一行豁免
#    （僵尸行的另一种长相：不是搭配没了，是**那个搭配在那一套主题里从来不存在**）。
AA_NONTEXT_EXEMPT: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "--border",
        "--panel",
        ("light", "dark"),
        "卡片 / 面板 / 模态 / 命令面板 / 芯片（`.badge`）/ 键位徽标（`.kbd`）/ "
        "ghost 按钮 的 1px 描边：内容自己说明这是什么，"
        "边框只做分组 —— WCAG 说的 pure decoration",
    ),
    (
        "--border",
        "--bg",
        ("light", "dark"),
        "左栏右分隔线（`.rail`）/ 底部 Tab 上边 / 离线提示条底边：纯装饰分隔",
    ),
    (
        "--border",
        "--panel-2",
        ("light", "dark"),
        "图表网格与轴基线 / 环轨道 / 空格描边（`.chart-grid` / `.chart-axis` / `.ring-track` / "
        "`.chart-cell-off-state`）：这些是**背景结构**，数据由 `--accent` 那几笔承担"
        "（它们在 3.0 表里）",
    ),
    (
        "--panel-2",
        "--panel",
        ("light", "dark"),
        "热力图空格与条形体底（`.chart-cell-off` / `.cell-off` / `.bar-track`）："
        "空格是「没有活动」，不是一个数据点；读数由有色格承担",
    ),
    (
        "--border-strong",
        "--toast-bg",
        ("dark",),
        "暗色 toast 里动作按钮的边框：按钮的**字**是识别线索（13.04），边界不承担识别"
        "（亮色的 toast 底是 `--ink`，那条边框 9.37 本来就过，所以只有暗色这一行）",
    ),
    (
        "--border-strong",
        "--panel",
        ("light", "dark"),
        "取样圈的悬停描边（`.swatch:not(.on):hover`）：悬停是辅助线索，"
        "静态下已经看得见（那条在 3.0 表里）",
    ),
)


def nontext_pairs() -> list[Pair]:
    """非文字图形的 3.0 表（两套主题各来一遍）。"""
    return [
        Pair(theme, fg, bg, AA_NONTEXT, where, kind="图形")
        for theme in ("light", "dark")
        for fg, bg, where in AA_NONTEXT_PAIRS
    ]


def exempt_pairs() -> list[Pair]:
    """纯装饰：只量不判（判据是 `AA_NONTEXT_EXEMPT` 的行内理由，不是数字）。

    每条只在自己声明的那几套主题上生成 —— 见上面 `themes` 那一栏的理由。
    """
    return [
        Pair(theme, fg, bg, AA_NONTEXT, where, kind="装饰")
        for fg, bg, themes, where in AA_NONTEXT_EXEMPT
        for theme in themes
    ]


def dedupe(pairs: list[Pair]) -> list[Pair]:
    """同一对「字 / 底」只留一条：悬停那一组里有三条规则落在同一个组合上
    （`.ghost:hover` / `nav button:hover` / `.bottom-nav button:hover` 都是 `--ink on --panel-2`），
    不去重的话 `where` 说明会互相盖掉，报出来的条数也会虚高。
    ★ T-G70 起 `key` 带 `图形` / `装饰` 前缀，所以"同一对令牌既是文字又是图形"的
    **两条都留得住**（它们量的不是一回事）。"""
    seen: set[str] = set()
    out: list[Pair] = []
    for pair in pairs:
        if pair.key in seen:
            continue
        seen.add(pair.key)
        out.append(pair)
    return out


# ------------------------------------------------------------------ 求值
def load_baseline() -> dict[str, dict[str, object]]:
    if not BASELINE.exists():
        return {}
    data = tomllib.loads(BASELINE.read_text(encoding="utf-8"))
    known = data.get("known", {})
    return dict(known) if isinstance(known, dict) else {}


def evaluate(
    pairs: list[Pair], tokens: dict[str, dict[str, str]], known: dict[str, dict[str, object]]
) -> list[Row]:
    rows: list[Row] = []
    for pair in pairs:
        table = tokens[pair.theme]
        if pair.bg.startswith("mix("):
            inner = re.fullmatch(r"mix\((--[a-z0-9-]+) ([\d.]+)% over (--[a-z0-9-]+)\)", pair.bg)
            assert inner is not None
            bg = mix_over(
                resolve(inner.group(1), table),
                resolve(inner.group(3), table),
                float(inner.group(2)) / 100,
            )
        else:
            bg = resolve(pair.bg, table)
        ratio = contrast(resolve(pair.fg, table), bg)
        entry = known.get(pair.key)
        recorded = float(str(entry["ratio"])) if entry else None
        why = str(entry.get("why", "")) if entry else ""
        if ratio >= pair.minimum:
            verdict = "FIXED" if entry else "PASS"
        elif entry is None:
            verdict = "NEW"
        elif ratio < recorded - EPS:  # type: ignore[operator]
            verdict = "WORSE"
        else:
            verdict = "KNOWN"
        rows.append(Row(pair, ratio, verdict, recorded, why))
    return rows


def summarize(rows: list[Row]) -> dict[str, int]:
    counts = {"PASS": 0, "KNOWN": 0, "FIXED": 0, "WORSE": 0, "NEW": 0}
    for row in rows:
        counts[row.verdict] += 1
    return counts


MARK = {
    "PASS": "[OK  ]",
    "KNOWN": "[欠账]",
    "FIXED": "[已修]",
    "WORSE": "[FAIL]",
    "NEW": "[FAIL]",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="对比度审美门（令牌层 WCAG 棘轮）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="有新欠账 / 比登记值更差 → 退出码 1")
    ap.add_argument("--strict", action="store_true", help="任何不达标都退 1（登记表清空后才可用）")
    args = ap.parse_args()

    css = CSS.read_text(encoding="utf-8")
    tokens = token_blocks(css)
    known = load_baseline()
    pairs = dedupe(declared_pairs() + badge_pairs(css) + state_pairs(css))
    nt_pairs = nontext_pairs()
    ex_pairs = exempt_pairs()
    rows = evaluate(pairs, tokens, known)
    nt_rows = evaluate(nt_pairs, tokens, {})
    ex_rows = evaluate(ex_pairs, tokens, {})
    counts = summarize(rows)
    text_keys = {(p.theme, p.fg, p.bg) for p in pairs}

    if args.json:
        print(
            json.dumps(
                {
                    "counts": counts,
                    "rows": [
                        {
                            "key": r.pair.key,
                            "where": r.pair.where,
                            "ratio": r.ratio,
                            "minimum": r.pair.minimum,
                            "verdict": r.verdict,
                            "recorded": r.known,
                        }
                        for r in rows
                    ],
                    "nontext": [
                        {
                            "key": r.pair.key,
                            "where": r.pair.where,
                            "ratio": r.ratio,
                            "minimum": r.pair.minimum,
                            "verdict": r.verdict,
                            "text_table_covers": (r.pair.theme, r.pair.fg, r.pair.bg) in text_keys,
                        }
                        for r in nt_rows
                    ],
                    "exempt": [
                        {"key": r.pair.key, "where": r.pair.where, "ratio": r.ratio}
                        for r in ex_rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    for theme, label in (("light", "亮色 :root"), ("dark", "暗色 [data-theme=dark]")):
        print(f"\n=== {label} ===")
        print(f"{'对比度':>6} {'阈值':>5}  {'判定':<7} 说明")
        for row in [r for r in rows if r.pair.theme == theme]:
            detail = row.pair.where
            if row.verdict == "KNOWN":
                detail = f"{detail}（登记 {row.known}）"
            print(
                f"{row.ratio:>6} {row.pair.minimum:>5}  "
                f"{MARK[row.verdict]} {row.pair.fg} on {detail}"
            )

        print(f"\n--- {label}：非文字图形（WCAG 1.4.11，阈值 3.0）---")
        for row in [r for r in nt_rows if r.pair.theme == theme]:
            same = (
                "  ← 同一对在文字表里按 4.5 管着"
                if (theme, row.pair.fg, row.pair.bg) in text_keys
                else ""
            )
            print(
                f"{row.ratio:>6} {row.pair.minimum:>5}  {MARK[row.verdict]} "
                f"{row.pair.fg} on {row.pair.bg}：{row.pair.where}{same}"
            )

    print(
        f"\n=== 纯装饰（WCAG 1.4.11 明文不适用；实测值只作记录，共 {len(ex_rows)} 条）==="
    )
    for row in ex_rows:
        print(
            f"{row.ratio:>6}     装饰  {row.pair.theme} {row.pair.fg}"
            f" on {row.pair.bg}：{row.pair.where}"
        )

    fixed = [r for r in rows if r.verdict == "FIXED"]
    if fixed:
        print("\n=== 这" + str(len(fixed)) + "条已经达标了 —— 从登记表里删掉 ===")
        for row in fixed:
            print(f"  {row.pair.key}（{row.ratio}）")

    bad = [r for r in rows if r.verdict in {"NEW", "WORSE"}] + [
        r for r in nt_rows if r.verdict in {"NEW", "WORSE"}
    ]
    print(
        f"\n合计：文字达标 {counts['PASS']} / 已登记欠账 {counts['KNOWN']} / "
        f"可销账 {counts['FIXED']} ｜ 非文字 {len(nt_rows)} 条 ｜ 装饰 {len(ex_rows)} 条（只记录）"
        f" / **新欠账或变差 {len(bad)}**"
    )
    if bad:
        print("\n对比度审美门 FAIL —— 有没登记的不足、或比登记值更差（见上）。")
        print(
            "文字那档要么补进 tools/contrast_baseline.toml（写明为什么、打算怎么办），"
            "要么改回去；"
        )
        print("非文字那档**没有登记表**：控制边界/图形看不见是缺陷，改令牌或者改这一行判据：")
        for row in bad:
            tag = (
                "新欠账"
                if row.verdict == "NEW"
                else f"变差（登记 {row.known} → 现在 {row.ratio}）"
            )
            print(f"  {row.pair.key}  {row.ratio} < {row.pair.minimum}  {tag} ｜ {row.pair.where}")
        return 1
    if args.strict and counts["KNOWN"]:
        print(f"\n--strict：还有 {counts['KNOWN']} 条登记欠账没修，不算通过。")
        return 1
    print(
        f"对比度审美门 PASS（文字达标 {counts['PASS']} / 已登记欠账 {counts['KNOWN']} / "
        f"新欠账或变差 0；非文字 {len(nt_rows)} 条全过 3.0；装饰 {len(ex_rows)} 条只记录；"
        f"共 {len(rows)} 条文字组合 + {len(nt_rows)} 条非文字）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
