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
- ★ T-G42 起状态徽标把颜色交给 **8px 圆点**（workbench 的 StatusDot），点是**非文字**（3.0 即可）。
  它没有被单列成一对组合，而是**借令牌级组合的地板**：`--ok` / `--danger` / `--accent`
  落在 `--panel` 上都按 4.5 登记着 —— 令牌一旦被改浅，先把那三条打红，圆点自然也不够。
  （"非文字图形"这个维度本身仍未系统覆盖，这一点如实写在 `复盘/审美门-对比度-T-G27.md` §6。）

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

    @property
    def key(self) -> str:
        return f"{self.theme}:{self.fg} on {self.bg}"


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


def dedupe(pairs: list[Pair]) -> list[Pair]:
    """同一对「字 / 底」只留一条：悬停那一组里有三条规则落在同一个组合上
    （`.ghost:hover` / `nav button:hover` / `.bottom-nav button:hover` 都是 `--ink on --panel-2`），
    不去重的话 `where` 说明会互相盖掉，报出来的条数也会虚高。"""
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
    rows = evaluate(pairs, tokens, known)
    counts = summarize(rows)

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

    fixed = [r for r in rows if r.verdict == "FIXED"]
    if fixed:
        print("\n=== 这" + str(len(fixed)) + "条已经达标了 —— 从登记表里删掉 ===")
        for row in fixed:
            print(f"  {row.pair.key}（{row.ratio}）")

    bad = [r for r in rows if r.verdict in {"NEW", "WORSE"}]
    print(
        f"\n合计：达标 {counts['PASS']} / 已登记欠账 {counts['KNOWN']} / "
        f"可销账 {counts['FIXED']} / **新欠账或变差 {len(bad)}**（共 {len(rows)} 条组合）"
    )
    if bad:
        print("\n对比度审美门 FAIL —— 有没登记的不足、或比登记值更差（见上）。")
        print("要么补进 tools/contrast_baseline.toml（写明为什么、打算怎么办），要么改回去：")
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
        f"对比度审美门 PASS（达标 {counts['PASS']} / 已登记欠账 {counts['KNOWN']} / "
        f"新欠账或变差 0；共 {len(rows)} 条组合）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
