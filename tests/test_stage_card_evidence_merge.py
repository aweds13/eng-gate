"""卡 E25（T-AG479）：`stage_card.py` 写台账片段时必须**合并**证据，不许覆盖。

真现场（两轮白跑 240 s/趟）：`docs/traceability.d/T-AG477.toml` 里人手补过
`file:tests/test_wb_verify_profiles.py` 与两条 `test:`，落地链 ② 跑一次
`tools/pool/stage_card.py --evidence <卡规格> <batch.toml>` 之后只剩那两条
⇒ 审计 ⑫「这一笔改了 X 但台账没有指针」当场红。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "tools" / "pool" / "stage_card.py"


def _tree(tmp_path: Path) -> Path:
    """造一棵够 stage_card 跑起来的最小树（片段模式：三个 .d 目录都在）。"""
    wt = tmp_path / "wt"
    (wt / "docs" / "changelog.d").mkdir(parents=True)
    (wt / "docs" / "traceability.d").mkdir(parents=True)
    (wt / "复盘" / "交接.d").mkdir(parents=True)
    (wt / "docs" / "traceability.toml").write_text("", encoding="utf-8", newline="\r\n")
    (wt / "docs" / "changelog.md").write_text(
        "## 2026-10-01\n", encoding="utf-8", newline="\r\n")
    (wt / "复盘" / "交接-重构进度.md").write_text(
        "# 交接\n\n" + "CHECKPOINT-PLACEHOLDER\n", encoding="utf-8", newline="\r\n")
    # ★ 卡 E100：证据指针在**写盘之前**就要按审计同一口径求值 ⇒ 这棵树必须有 tests/ 真文件
    (wt / "tests").mkdir()
    (wt / "tests" / "whatever.py").write_text(
        "def test_x():\n    pass\n", encoding="utf-8", newline="\n")
    # stage_card 的片段模式会调 `tools/sync_docs.py`（相对 wt 找）⇒ 把真脚本与它的依赖铺进来
    (wt / "tools").mkdir()
    for rel in ("tools/sync_docs.py", "tools/pool/__init__.py", "tools/pool/no_window.py"):
        src = ROOT / rel
        if src.is_file():
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    return wt


def _run(wt: Path, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    narrative = tmp_path / "text.md"
    narrative.write_text(
        "=== gaps ===\n- 无\n\n=== changelog ===\n## 测试卡（T-AG999）\n\n- 一行\n\n"
        "=== checkpoint ===\n- 一段\n",
        encoding="utf-8", newline="\n")
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(STAGE), "--tree", str(wt), "--id", "T-AG999",
         "--title", "测试卡", "--group", "ENGINEERING", "--evidence", *extra,
         "--text-file", str(narrative)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_existing_fragment_evidence_survives_a_restage(tmp_path: Path) -> None:
    """片段里已有人补的指针 ⇒ 重跑 stage_card 之后它们必须还在。"""
    wt = _tree(tmp_path)
    spec = tmp_path / "spec.md"
    spec.write_text("# 卡\n", encoding="utf-8")
    batch = tmp_path / "batch.toml"
    batch.write_text('id = "T-AG999"\n', encoding="utf-8")
    # 先写一份「人手补过指针」的片段
    (wt / "docs" / "traceability.d" / "T-AG999.toml").write_text(
        '[entries."T-AG999"]\nid = "T-AG999"\ntitle = "测试卡"\ngroup = "ENGINEERING"\n'
        'status = "done"\nevidence = [\n  "file:tools/x.py",\n'
        '  "test:test_x.py::test_it",\n]\ngaps = ""\n',
        encoding="utf-8", newline="\n")

    # 合成小树里 `sync_docs` 写出来的 CRLF 纯正性过不了 stage_card 的「纯 CRLF」自检 ——
    # 与本卡判据无关（片段在自检之前就已经写好），所以只看片段内容，不看退出码。
    r = _run(wt, tmp_path, str(spec), str(batch))
    assert (wt / "docs" / "traceability.d" / "T-AG999.toml").is_file(), r.stdout + r.stderr
    frag_path = wt / "docs" / "traceability.d" / "T-AG999.toml"
    data = tomllib.loads(frag_path.read_text(encoding="utf-8"))
    got = list(data["entries"]["T-AG999"]["evidence"])
    assert "file:tools/x.py" in got, f"人手补的指针被覆盖了：{got}"
    assert "test:test_x.py::test_it" in got, f"test: 指针被覆盖了：{got}"
    assert any(x.endswith("spec.md") for x in got), f"本次 --evidence 没写进去：{got}"
    assert len(got) == len(set(got)), f"合并后有重复：{got}"


def test_restage_does_not_duplicate_an_identical_pointer(tmp_path: Path) -> None:
    """同一份 --evidence 连跑两次 ⇒ 片段里的条目数不许翻倍。"""
    wt = _tree(tmp_path)
    spec = tmp_path / "spec.md"
    spec.write_text("# 卡\n", encoding="utf-8")
    first = _run(wt, tmp_path, str(spec))
    assert (wt / "docs" / "traceability.d" / "T-AG999.toml").is_file(), first.stdout + first.stderr
    path = wt / "docs" / "traceability.d" / "T-AG999.toml"
    first_data = tomllib.loads(path.read_text(encoding="utf-8"))
    n1 = len(first_data["entries"]["T-AG999"]["evidence"])
    second = _run(wt, tmp_path, str(spec))
    assert path.is_file(), second.stdout + second.stderr
    second_data = tomllib.loads(path.read_text(encoding="utf-8"))
    n2 = len(second_data["entries"]["T-AG999"]["evidence"])
    assert n1 == n2, f"重复 --evidence 把条目写重了：{n1} → {n2}"


def test_kinded_evidence_keeps_its_kind(tmp_path: Path) -> None:
    """卡 E89 现场：`--evidence test:…` / `text:…` 不许被加成 `file:test:…`。

    audit 会把 `file:test:…` 判成「文件不存在」。
    """
    wt = _tree(tmp_path)
    # 合成小树里 `sync_docs` 写出来的 CRLF 纯正性过不了 stage_card 的自检 —— 与本卡判据无关
    # （片段在自检之前就已写好），所以只看片段内容，不看退出码。
    r = _run(wt, tmp_path, "tests/whatever.py",
             "test:tests/whatever.py::test_x",
             "text:tools/wb_plan.py::图案例")
    path = wt / "docs" / "traceability.d" / "T-AG999.toml"
    assert path.is_file(), r.stdout + r.stderr
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    got = list(data["entries"]["T-AG999"]["evidence"])
    assert "file:tests/whatever.py" in got, f"裸路径必须仍补 file:：{got}"
    # ★ 卡 E100（T-AG609）：`test:` 的**形态**归一到裸文件名（审计自己补 `tests/`）；
    #   前缀本身仍必须是 `test:`，不许被加成 `file:test:`。
    assert "test:whatever.py::test_x" in got, f"test: 被加了 file: 前缀或没归一：{got}"
    assert "text:tools/wb_plan.py::图案例" in got, f"text: 被加了 file: 前缀：{got}"
    bad = [x for x in got if x.startswith("file:test:") or x.startswith("file:text:")]
    assert not bad, f"出现 file:test: / file:text: 双重前缀：{bad}"
