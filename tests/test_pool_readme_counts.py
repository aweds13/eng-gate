"""钉子：`scripts/gen_pool_readme.py` 的生成与判据（卡 F11 · `T-AG559`）。

## 为什么这些用例存在

`docs/subsystems/pool/README.md` 的体量表曾经是**手抄**的，于是必然过期：卡 F11 开卡时
表里写 17 个 py / 7143 行，实测 36 个 py / 13817 行，40 个文件里 21 个一个都没进表。
「改成机器生成」只是修一次；这些用例钉的是**它不会再退回去**：

- 一条**正向**：真仓现在就是一致的（`--check` 退 0）。这条会随 `tools/pool/` 变动而红 ——
  那是设计意图：加了模块就得进清单、行数就得重算。
- 六条**反向**：每条都真改坏一处（多一个模块不记账、职责写空、手改数字、手改标记外、
  行尾不是 CRLF），真跑生成器，看它是不是真红在**该红的地方**（点名 / 行号 / 退码）。

反向用例全部跑**合成树**（`--root`），因为要故意把仓改坏；正向那条跑**真仓**。
一律走子进程：生成器判据的任何变化都得先落盘再被观察到，防止「测自己」。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "gen_pool_readme.py"
README_REL = "docs/subsystems/pool/README.md"
MODULES_REL = "docs/subsystems/pool/modules.toml"
BEGIN = "<!-- pool-margin:begin -->"
END = "<!-- pool-margin:end -->"

MANIFEST = """[[module]]
name = "__init__.py"
duty = "包说明与模块地图"
cli = "无"

[[module]]
name = "alpha.py"
duty = "把名字映射成稳定 id（纯函数）"
cli = "无（被 `wb_dispatch` 调）"
"""

BACKLOG = """cards = [
  { id = "A1", status = "done" },
  { id = "A2", status = "done" },
  { id = "A3", status = "pending" },
]
"""

D1 = "- **D1 守卫写成纯函数、只有一份**：吃数据回问题，不写文件不起进程。"

#: 合成树里的项目书。两处标记之间的内容是占位（生成器一跑就整块替换），
#: 标记之外的两段（文件头、§3 决策、口径句）是**人手写的**，生成器不许动。
README = f"""# 合成树里的项目书

> 文件头在标记外，生成器不许碰它。

## 1. 它现在是什么（代码边际）

{BEGIN}
这里原本是手抄的表，生成器会整块换掉。
{END}

口径两条（别读错）：① 只统计有 ≥2 个 `__timestamp` 的日志；② 耗时是工人进程墙钟。

## 3. 决策（D1–D7，指回卡号）

{D1}

## 5. 边界

**越界判据**：把门禁判据抄进 pool 文档；出现"未来会做"。
"""


def _write(root: Path, rel: str, text: str, newline: str = "\n") -> Path:
    """落一份文件：文本里只写 `\\n`，行尾交给 `newline=`（两处都写会变成 `\\r\\r\\n`）。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)
    return path


def _build(root: Path, newline: str = "\n") -> Path:
    """铺一棵最小可跑的合成树：README + 两个 py + 清单 + 队列。"""
    _write(root, "tools/pool/__init__.py", '"""包。"""\n')
    _write(root, "tools/pool/alpha.py", "def solve() -> int:\n    return 1\n")
    _write(root, MODULES_REL, MANIFEST)
    _write(root, "docs/workbacklog.toml", BACKLOG)
    return _write(root, README_REL, README, newline=newline)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """子进程跑生成器（真落盘、真退出码，不 import 它 —— 防止「测自己」）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_real_readme_matches_recount() -> None:
    """正向：真仓现在一致。`tools/pool/` 一变动、或手改了表里的数字，这条就红。"""
    done = _run("--check")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "[OK  ]" in done.stdout


def test_unknown_module_is_named(tmp_path: Path) -> None:
    """仓里有、清单没写 ⇒ 退 1 且点名。漏一个模块，读者就以为它不存在。"""
    root = tmp_path / "tree"
    _build(root)
    _write(root, "tools/pool/zzz_new.py", "x = 1\n")

    done = _run("--root", str(root), "--check")

    assert done.returncode == 1, done.stdout
    assert "zzz_new.py" in done.stdout


def test_empty_duty_is_named(tmp_path: Path) -> None:
    """`duty` 空串 ⇒ 退 1 且点名。空职责等于没写：读者没法据此判断该不该改它。"""
    root = tmp_path / "tree"
    _build(root)
    _write(root, MODULES_REL, MANIFEST.replace("把名字映射成稳定 id（纯函数）", ""))

    done = _run("--root", str(root), "--check")

    assert done.returncode == 1, done.stdout
    assert "alpha.py" in done.stdout
    assert "duty" in done.stdout


def test_hand_edited_count_reports_line(tmp_path: Path) -> None:
    """手改表里一行的行数 ⇒ 退 1，且报到**文件里那一行的行号**（不是块内序号）。"""
    root = tmp_path / "tree"
    readme = _build(root)
    assert _run("--root", str(root)).returncode == 0, "先让树是绿的"
    lines = readme.read_text(encoding="utf-8").split("\n")
    target = next(index for index, line in enumerate(lines) if line.startswith("| `alpha.py` |"))
    assert "| 2 |" in lines[target], lines[target]
    lines[target] = lines[target].replace("| 2 |", "| 999 |")
    readme.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    done = _run("--root", str(root), "--check")

    assert done.returncode == 1, done.stdout
    assert f"第 {target + 1} 行" in done.stdout, done.stdout
    assert "999" in done.stdout


def test_outside_marker_is_untouched(tmp_path: Path) -> None:
    """标记外的字（§3 决策）不是生成器的：手改它 `--check` 仍退 0，重写后逐字未变。"""
    root = tmp_path / "tree"
    readme = _build(root)
    assert _run("--root", str(root)).returncode == 0, "先让树是绿的"
    edited = D1.replace("不起进程。", "不起进程（人手改过这句）。")
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(D1, edited), encoding="utf-8", newline="\n"
    )

    checked = _run("--root", str(root), "--check")
    assert checked.returncode == 0, checked.stdout

    written = _run("--root", str(root))
    assert written.returncode == 0, written.stdout
    assert edited in readme.read_text(encoding="utf-8")


def test_crlf_target_keeps_line_endings(tmp_path: Path) -> None:
    """CRLF 目标重算后：`\\r\\n` 数不变形、没有裸 `\\n`（行尾跟随目标，不写死常量）。"""
    root = tmp_path / "tree"
    readme = _build(root, newline="\r\n")
    assert _run("--root", str(root)).returncode == 0, "先写一次"
    first = readme.read_bytes()
    assert first.count(b"\r\n") == first.count(b"\n") > 0
    assert b"\r\r\n" not in first

    again = _run("--root", str(root))

    assert again.returncode == 0, again.stdout
    assert readme.read_bytes() == first, "第二遍必须一个字节都不动"
    assert first.count(b"\r\n") == first.count(b"\n")
