r"""文档归位迁移器的钉子（卡 F1 · T-AG449）。

一张迁移脚本最容易骗人的地方有四个，这里每个都配一条**会失败**的断言：

| 钉子 | 判什么 |
|---|---|
| ① dry-run 不动盘 | 整棵树的 `rel → sha256` 快照前后**完全相同**（只算不写） |
| ② apply 只改路径 | 搬过去的卡正文 = 原文把新前缀换回旧前缀（内容一个字不动） |
| ③ 幂等 | 第二次 apply 退出 0、快照不变、journal 不被重写 |
| ④ revert 逐字节还原 | 整棵树（路径 + 内容）回到 apply 之前；有人偷偷改过一个字就**拒跑** |
| ⑤ 自检会咬人 | 改写根之外的残留 → 退出 3；跳过清单里的残留 → 只报「需人工」，不误判成功 |
| ⑥ 裸目录引用与反斜杠 | `"复盘/卡"`（不带尾斜杠）要改；`复盘/卡.md` / `复盘/卡-095.md` **不许**改 |

★ 为什么要有 ⑤：迁移的最后一道防线是「搬完再扫一遍」，没有这条断言它就是一段
永远返回 0 的装饰代码（本仓的反空转口径：新判据要配一条"故意坏掉"的用例）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import migrate_docs as md  # noqa: E402 —— tools/ 已在 sys.path 上

MAP_REL = "docs/migration-map.json"
JOURNAL_REL = "gates/diag/doc-migration.json"


def _snapshot(root: Path) -> dict[str, str]:
    """整棵树：`posix 相对路径 → sha256`（不含 journal —— 那是账，本来就该留）。"""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if rel == JOURNAL_REL:
                continue
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _strip_paths(text: str) -> str:
    """把两种路径写法都抹掉 —— 剩下的部分就是「正文本身」。"""
    needles = ("复盘\\\\卡", "复盘\\卡", "docs\\\\cards", "docs\\cards", "复盘/卡", "docs/cards")
    for needle in needles:
        text = text.replace(needle, "")
    return text


def _write(root: Path, rel: str, text: str, *, crlf: bool = False) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n").encode("utf-8") if crlf else text.encode("utf-8")
    path.write_bytes(data)
    return path


def _make_repo(tmp_path: Path) -> Path:
    """一棵最小仓：两份卡规格 + 六类引用 + 一条跳过 + 一条三期候选。"""
    root = tmp_path / "repo"
    root.mkdir()

    _write(root, "复盘/卡/卡001-a.md", "# 卡 001\n\n见 `复盘/卡/卡002-b.md`。\n")
    _write(root, "复盘/卡/卡002-b.md", "# 卡 002\n\n没有引用。\n", crlf=True)
    _write(root, "复盘/INDEX.md", "- [卡001](复盘/卡/卡001-a.md)\n")
    _write(root, "复盘/方案-x.md", "# 方案（三期候选，未批准）\n")
    _write(root, "docs/workbacklog.toml", 'spec = "复盘/卡/卡001-a.md"\n')
    _write(
        root,
        "docs/traceability.d/T-1.toml",
        '"file:复盘/卡/卡001-a.md",\n"test:tests/test_keep.py",\n',
    )
    _write(root, "docs/changelog.md", "- `复盘/卡/卡002-b.md` 入库\n")
    _write(root, "skills/demo/SKILL.md", "--spec 复盘/卡/卡001-a.md \\\n")
    _write(
        root,
        "tools/demo.py",
        'SPEC_DIR = "复盘/卡"\nNOTE = "复盘/卡.md"\nOLD = "复盘/卡-095.md"\n'
        'WIN = "复盘\\\\卡\\\\卡001-a.md"\nCARD_DIR = ROOT / "复盘" / "卡"\n',
    )
    _write(root, "tests/test_keep.py", 'assert find("复盘/卡/卡001-a.md")\n')
    _write(root, "tests/test_skip.py", 'assert path == "复盘/卡/卡001-a.md"  # 拓扑数据\n')
    _write(root, "src/y.md", "能写：`src/**`、`复盘/卡/卡D*.md`。\n")

    _write(
        root,
        MAP_REL,
        json.dumps(
            {
                "version": 1,
                "moves": [
                    {
                        "phase": "二期",
                        "glob": "复盘/卡/*.md",
                        "to_dir": "docs/cards",
                        "why": "卡规格是在飞的工作定义，不是历史",
                    }
                ],
                "rewrite": {
                    "roots": ["docs", "skills", "tools", "tests", "src", "复盘", "AGENTS.md"],
                    "suffixes": [".md", ".toml", ".py"],
                    "skip": [MAP_REL, "tests/test_skip.py"],
                },
                "code_probes": [
                    {
                        "path": "tools/demo.py",
                        "pattern": '"复盘" / "卡"',
                        "why": "找卡规格的搜索根（路径串改不动它，必须人手改）",
                    }
                ],
                "candidates": [
                    {"path": "复盘/方案-x.md", "verdict": "pending", "group": "docs/decisions/"}
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return root


def _run(root: Path, *args: str) -> int:
    return md.main(["--root", str(root), *args])


def _apply(root: Path) -> int:
    return _run(root, "--apply")


def test_dry_run_does_not_touch_disk(tmp_path: Path, capsys) -> None:
    root = _make_repo(tmp_path)
    before = _snapshot(root)
    rc = _run(root, "--dry-run")
    assert rc == 0
    assert _snapshot(root) == before, "dry-run 改了盘"
    out = capsys.readouterr().out
    assert "2" in out and "docs/cards" in out
    assert not (root / "docs/cards").exists()


def test_apply_moves_and_rewrites(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    card_before = (root / "复盘/卡/卡001-a.md").read_text(encoding="utf-8")
    assert _apply(root) == 0

    # ① 文件真的搬了
    assert (root / "docs/cards/卡001-a.md").is_file()
    assert not (root / "复盘/卡").exists()

    # ② 正文只改路径：把新前缀换回旧前缀，必须和原文逐字相等
    card_after = (root / "docs/cards/卡001-a.md").read_text(encoding="utf-8")
    assert card_after.replace("docs/cards/", "复盘/卡/") == card_before

    # ③ 六类引用都改了
    assert 'spec = "docs/cards/卡001-a.md"' in (root / "docs/workbacklog.toml").read_text("utf-8")
    assert "file:docs/cards/卡001-a.md" in (
        root / "docs/traceability.d/T-1.toml"
    ).read_text("utf-8")
    assert "`docs/cards/卡002-b.md`" in (root / "docs/changelog.md").read_text("utf-8")
    assert "--spec docs/cards/卡001-a.md" in (
        root / "skills/demo/SKILL.md"
    ).read_text("utf-8")
    assert "(docs/cards/卡001-a.md)" in (root / "复盘/INDEX.md").read_text("utf-8")
    assert 'find("docs/cards/卡001-a.md")' in (root / "tests/test_keep.py").read_text("utf-8")
    assert "`docs/cards/卡D*.md`" in (root / "src/y.md").read_text("utf-8")

    # ④ 裸目录引用 / 反斜杠要改；`复盘/卡.md`、`复盘/卡-095.md` 不许动
    code = (root / "tools/demo.py").read_text("utf-8")
    assert 'SPEC_DIR = "docs/cards"' in code
    assert 'NOTE = "复盘/卡.md"' in code
    assert 'OLD = "复盘/卡-095.md"' in code
    assert 'WIN = "docs\\\\cards\\\\卡001-a.md"' in code

    # ⑤ CRLF 原样保留
    assert b"\r\n" in (root / "docs/cards/卡002-b.md").read_bytes()

    # ⑥ 跳过清单原样、三期候选不动
    assert '复盘/卡/卡001-a.md' in (root / "tests/test_skip.py").read_text("utf-8")
    assert (root / "复盘/方案-x.md").is_file()

    # ⑦ journal 先写全表
    journal = json.loads((root / JOURNAL_REL).read_text("utf-8"))
    assert journal["status"] == "applied"
    assert [(m["old"], m["new"]) for m in journal["moves"]] == [
        ("复盘/卡/卡001-a.md", "docs/cards/卡001-a.md"),
        ("复盘/卡/卡002-b.md", "docs/cards/卡002-b.md"),
    ]
    assert all(len(m["sha256"]) == 64 for m in journal["moves"])

    # ⑧ 只改路径：把两边的路径字样都抹掉，正文必须逐字相同（卡判据 5）
    for item in journal["rewrites"]:
        path = root / item["path"]
        with open(path, encoding="utf-8", newline="") as fh:
            current = fh.read()
        assert _strip_paths(item["before_text"]) == _strip_paths(current), item["path"]


def test_apply_is_idempotent(tmp_path: Path, capsys) -> None:
    root = _make_repo(tmp_path)
    assert _apply(root) == 0
    after_first = _snapshot(root)
    journal_one = (root / JOURNAL_REL).read_bytes()
    capsys.readouterr()

    assert _apply(root) == 0
    assert _snapshot(root) == after_first, "第二次 apply 又改了盘"
    assert (root / JOURNAL_REL).read_bytes() == journal_one, "第二次 apply 重写了 journal"
    assert "已迁移" in capsys.readouterr().out


def test_revert_restores_byte_for_byte(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    before = _snapshot(root)
    assert _apply(root) == 0
    assert _run(root, "--revert") == 0

    assert _snapshot(root) == before, "revert 没把树还原"
    journal = json.loads((root / JOURNAL_REL).read_text("utf-8"))
    assert journal["status"] == "reverted"


def test_revert_refuses_when_someone_edited_after_apply(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert _apply(root) == 0
    drifted = root / "docs/changelog.md"
    drifted.write_text(drifted.read_text("utf-8") + "- 手改了一行\n", encoding="utf-8")

    rc = _run(root, "--revert")
    assert rc == 2, "有人改过还照样还原 = 悄悄盖掉别人的改动"
    # 拒跑时不许有半截动作：文件仍在迁移后的位置
    assert (root / "docs/cards/卡001-a.md").is_file()
    assert not (root / "复盘/卡").exists()


def test_apply_refuses_when_destination_exists(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write(root, "docs/cards/卡001-a.md", "旧的一版\n")
    before = _snapshot(root)
    assert _apply(root) == 2
    assert _snapshot(root) == before, "拒跑了还改了盘"


def test_residual_outside_rewrite_roots_makes_apply_loud(tmp_path: Path, capsys) -> None:
    root = _make_repo(tmp_path)
    _write(root, "notes/遗留.md", "这里还有 `复盘/卡/卡001-a.md` 没清\n")

    assert _apply(root) == 3, "改写根之外的残留必须让 apply 退 3，不许报成功"
    out = capsys.readouterr().out
    assert "残留" in out and "notes/遗留.md" in out

    # 之后单独跑一遍自检也照样咬
    capsys.readouterr()
    assert _run(root, "--check") == 3
    assert "notes/遗留.md" in capsys.readouterr().out


def test_skip_list_is_reported_not_fatal(tmp_path: Path, capsys) -> None:
    root = _make_repo(tmp_path)
    assert _apply(root) == 0, "跳过清单里的残留不该让 apply 变红"
    out = capsys.readouterr().out
    assert "需人工" in out and "tests/test_skip.py" in out


def test_code_probe_reports_unhandled_code_point(tmp_path: Path, capsys) -> None:
    root = _make_repo(tmp_path)
    assert _apply(root) == 0
    capsys.readouterr()
    _run(root, "--check")
    out = capsys.readouterr().out
    assert "tools/demo.py" in out
    assert "找卡规格的搜索根" in out


def test_json_output_is_machine_readable(tmp_path: Path, capsys) -> None:
    root = _make_repo(tmp_path)
    assert _run(root, "--dry-run", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run"
    assert payload["moves"] == 2
    assert payload["rewrite_files"] >= 6
    assert payload["problems"] == []


def test_missing_source_and_empty_destination_is_a_problem(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    for path in (root / "复盘/卡").glob("*.md"):
        path.unlink()
    assert _apply(root) == 2, "源头一张都没匹配到、目标也是空的 ⇒ 不许当成功"
