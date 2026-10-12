"""`tools/tf_cardgen.py` 的三态与「不掺真数据」（卡 096 / 台账号 `T-G191`）。

钉的是**会咬人的那几条**：

1. ★ 缺 `--id/--task/--title/--tree/--base` 任一 → **明确报错退 2**，不许生成半份；
2. ★ `--dry-run` 只打印到 stdout，**不落盘**（目录都不建）；
3. 正常 → 两份文件都生成，文件名口径对，且**含 `Task:` 行与「不要 commit」那一段**；
4. ★ 生成物**不含**真台账里的任何真实 `T-G` 条目正文（防把真数据带进模板）。

全程在 `tmp_path` 里产出，绝不动真仓库。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "tf_cardgen.py"
REAL_LEDGER = ROOT / "docs" / "traceability.toml"

BASE_ARGS = [
    "--id", "096", "--task", "T-G191", "--title", "机器替代③归类④卡样板",
    "--tree", ".wt/mech2", "--base", "5db2aa1", "--pool", "codebuddy",
    "--files", "tools/tf_group.py", "--forbid", "scripts/x.py",
]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOL), *args],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )


@pytest.mark.parametrize("drop", ["--id", "--task", "--title", "--tree", "--base"])
def test_missing_required_param_exits_2(tmp_path: Path, drop: str) -> None:
    args: list[str] = []
    skip_next = False
    for tok in BASE_ARGS:
        if skip_next:
            skip_next = False
            continue
        if tok == drop:
            skip_next = True
            continue
        args.append(tok)
    out = tmp_path / "out"
    done = run(*args, "--out-dir", str(out))
    assert done.returncode == 2, done.stdout
    assert "required" in done.stderr
    assert not out.exists()  # 不许生成半份


def test_dry_run_prints_but_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = run(*BASE_ARGS, "--out-dir", str(out), "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "dry-run" in done.stdout
    # 必备两段都在打印里
    assert "Task: T-G191" in done.stdout
    assert "小步提交" in done.stdout          # ★ 卡 192：小步提交到 card/<号>（不是"不要 commit"）
    assert "card/096" in done.stdout
    assert "不要 commit" not in done.stdout   # ★ 旧规矩已废
    assert not out.exists()  # ★ 不落盘（连目录都不建）


def test_normal_run_writes_two_files_with_markers(tmp_path: Path) -> None:
    out = tmp_path / "out"
    done = run(*BASE_ARGS, "--out-dir", str(out))
    assert done.returncode == 0, done.stderr
    card = out / "卡096-机器替代③归类④卡样板.md"
    brief = out / "brief-096.md"
    assert card.is_file(), sorted(p.name for p in out.iterdir())
    assert brief.is_file()
    for p in (card, brief):
        text = p.read_text(encoding="utf-8")
        assert "Task: T-G191" in text          # ★ 必备一：Task: 行
        assert "小步提交" in text              # ★ 卡 192：小步提交到 card/<号>
        assert "card/096" in text
        assert "不要 commit" not in text       # ★ 旧规矩已废
    assert ".wt/mech2" in card.read_text(encoding="utf-8")
    assert "5db2aa1" in card.read_text(encoding="utf-8")


def test_generated_docs_carry_no_real_ledger_body(tmp_path: Path) -> None:
    """★ 生成物里不许出现真台账任何真实条目正文（防把真数据带进模板）。"""
    real = tomllib.loads(REAL_LEDGER.read_text(encoding="utf-8"))["entries"]
    real_titles = [str(e.get("title", "")) for e in real.values() if e.get("title")]
    assert real_titles  # 台账非空，这条断言才有意义

    out = tmp_path / "out"
    done = run(*BASE_ARGS, "--out-dir", str(out))
    assert done.returncode == 0, done.stderr
    blob = (out / "卡096-机器替代③归类④卡样板.md").read_text(encoding="utf-8")
    blob += (out / "brief-096.md").read_text(encoding="utf-8")
    # 取几条有辨识度的真标题，逐条断言「不在生成物里」
    for title in real_titles[:20] + real_titles[-20:]:
        assert title not in blob, f"生成物混入了真条目正文：{title[:30]}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
