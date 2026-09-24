"""挤压体检（T-G45）—— 从渲染清单里找「文字被压成好几行」的地方。

## 它是什么、不是什么（先说清边界）

它是**诊断工具，不是门禁**：判据里有一步是"这条文字一行要占多宽"的**估算**
（CJK/全角按 `0.95em`、其余按 `0.5em`），估不准就会误报。把它做成硬门，迟早要为
一个误报把某个视图加进白名单 —— 然后这张表就没人看了。所以：**人读，不改门禁**。

## 判据（两条同时成立才算）

1. **这条文字一行放不下**：需要宽（按字形估算）> 可用宽（元素宽 − 左右内边距 − 2px 边框）；
2. **它真的换行了**：`(高 − 上下内边距 − 2) / 行高 ≥ 1.5`。

第 2 条是用来**去噪**的：字宽是估的，差几个像素很常见；真换行了才会高出来。
（第一版只拿「宽 < 容器 60%」当信号 → 一行里的小按钮全被报；第二版只拿「换行了」→
所有段落都被报，因为段落本来就该按容器宽换行。**两条一起**才是"旁边有地方却被压成一条"。）

## 为什么值得留着

它是量出来的，不是想出来的：T-G45 用它从 42 份清单里找出 **11 处**真挤压
（习惯页摘要卡 68×80、三个按钮各断两行、分组名被压到 19px），而此前 16 道门**没有一道**
看得见这类问题 —— 渲染层把几何采下来了，但没有人**判**它。

用法（步 2 / 步 3 改版式前后各跑一次）：
    python -X utf8 tools/squeeze_scan.py              # 全部视图
    python -X utf8 tools/squeeze_scan.py phone__habit.txt narrow__habit.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = ROOT / "gates" / "render"
# 全角/宽字形（CJK、全角标点、破折号、省略号）按 0.95em 算前进宽度
WIDE = re.compile(r"[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef\u2014\u2026]")
# 「拿到的宽 < 容器宽的 70%」才叫被挤 —— 段落按容器宽换行是正常的，不算
SQUEEZE_RATIO = 0.7


def _numbers(value: str) -> list[float]:
    return [float(m.group(1)) for m in re.finditer(r"(-?[\d.]+)px", value)]


def _paddings(padding: str) -> tuple[float, float]:
    """(左右和, 上下和) —— 1/2/3/4 值写法都按 CSS 规则展开。"""
    v = _numbers(padding)
    if not v:
        return 0.0, 0.0
    if len(v) == 1:
        return v[0] * 2, v[0] * 2
    if len(v) == 2:
        return v[1] * 2, v[0] * 2
    if len(v) == 3:
        return v[1] * 2, v[0] + v[2]
    return v[1] + v[3], v[0] + v[2]


def _needed(text: str, size: float) -> float:
    return sum(0.95 * size if WIDE.match(ch) else 0.5 * size for ch in text)


class Row:
    """清单里的一行。字段：选择器 / 文字 / 几何 / 字体 / 颜色 / 圆角;内边距。"""

    def __init__(self, selector: str, text: str, box: str, font: str, tail: str) -> None:
        self.selector, self.text = selector, text
        x, y, w, h = (float(v) for v in box.split(","))
        self.x, self.y, self.w, self.h = x, y, w, h
        size, line_height, _weight = font.split("/")
        self.size = float(size)
        self.line_height = (
            float(line_height) if re.match(r"[\d.]+$", line_height) else self.size * 1.2
        )
        _radius, _, padding = tail.partition(";")
        self.pad_lr, self.pad_tb = _paddings(padding)
        self.available = self.w - self.pad_lr - 2
        self.content_w = self.w - self.pad_lr

    @property
    def lines(self) -> float:
        return max(self.h - self.pad_tb - 2, 0.0) / self.line_height if self.line_height else 0.0


def _parent_content_width(row: Row, rows: list[Row]) -> float:
    """**最近的**祖先容器宽。

    用「最近的」而不是「最宽的」：最宽会退化成整个 shell，于是左栏 168px / 右栏 300px
    这种「本来就该窄」的定宽列会被全部报成挤压（第一版就是这么误报的）。
    """
    parts = row.selector.split(">")
    for cut in range(len(parts) - 1, 0, -1):
        ancestor = ">".join(parts[:cut])
        found: Row | None = None
        for other in rows:
            if other is row:
                continue
            same = other.selector == ancestor or other.selector.endswith(">" + ancestor)
            if same and (found is None or len(other.selector) > len(found.selector)):
                found = other
        if found is not None:
            return found.content_w
    return 0.0


def scan(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    viewport = float(re.search(r"(\d+)x\d+", lines[0]).group(1))
    rows: list[Row] = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) < 6:
            continue
        try:
            rows.append(Row(fields[0], fields[1], fields[2], fields[3], fields[5]))
        except Exception:  # 清单里偶尔有空行/异常行，跳过就好
            continue

    out: list[str] = []
    for row in rows:
        if row.x + row.w > viewport + 1:  # 横向溢出：手机上就是横向滚动条
            edge, where = row.x + row.w, row.selector[:70]
            out.append(f"  [溢出] 右边缘 {edge:.0f} > 视口 {viewport:.0f}  {where}")
        text = row.text.strip()
        if not text or "YYYY" in text or row.available <= 0:
            continue
        need = _needed(text.replace("(text)", ""), row.size)
        if need <= row.available or row.lines < 1.5:
            continue
        room = _parent_content_width(row, rows)
        if room and row.content_w < SQUEEZE_RATIO * room:
            out.append(
                f"  [挤压] {row.w:>5.0f}×{row.h:<4.0f} 可用 {row.available:>5.0f}/{room:>5.0f} "
                f"需要 {need:>5.0f}  {text[:26]!r}  ← {row.selector[:70]}"
            )
    return out


def main() -> int:
    wanted = sys.argv[1:]
    files = [MANIFESTS / w for w in wanted] if wanted else sorted(MANIFESTS.glob("*.txt"))
    total = 0
    for path in files:
        hits = scan(path)
        if hits:
            print(f"--- {path.stem} ---")
            print("\n".join(hits))
            total += len(hits)
    print(f"\n合计 {total} 处（判据是估算，人读用；不是门禁 —— 见文件头）")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
