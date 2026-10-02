r"""对抗复核生成器 `tools/wb_advcard.py` 的钉子（卡 143 · `T-G242`）。

为什么有它：用户把对抗复核从「**闸**」（挡收口）改成「**审计**」（**提交之后**、**异步**、
**不挡**流水线）。方法有效但依赖人临时写开场白 —— 本卡把它变成一条命令（生成器）。
下面这几条钉子就是「它会咬人」的证明：

| 钉子 | 钉什么 |
|---|---|
| ④ | `--commit <真sha>` ⇒ 含**四问** + **改动清单** + 三项硬要求（只读/证据指针/找不到就说） |
| ⑤ | **复用影响面**：桩 `wb_impact.py` ⇒ 输出跟着变；拿不到 ⇒ **明确降级** |
| ⑥ | **规矩可查**：`复盘/外包-卡表与规矩.md` 那一节含「提交之后/异步/不挡/不同族/不可逆」五词 |
| ⑦ | `--task <任务号>`：从任务栅栏状态取「新能力（成员 what + claim why）」与落地 commit |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_advcard as adv  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import task as pool_task  # noqa: E402

#: 产物里必须出现的「四问」关键词（每条问句的抓手）。
FOUR_PROBE = ("看着绿其实没查", "存在性", "自报清单", "退出码")
#: 硬要求三件（只读 / 证据指针 / 找不到就说）。
HARD_PROBE = ("只读", "证据指针", "找不到")


def _head_sha() -> str:
    rc, out = adv.git_out("rev-parse", "HEAD")
    assert rc == 0, out
    return out.strip()


def _read_draft(batch: Path, name: str) -> str:
    target = batch / f"{name}.advcard.md"
    assert target.exists(), f"没生成产物：{target}"
    return target.read_text(encoding="utf-8")


def test_nail143_04_commit_draft_has_four_questions_and_hard_rules(tmp_path, monkeypatch):
    """④ `--commit <真 sha>` ⇒ 产物含四问 + 改动文件清单 + 三项硬要求。"""
    batch = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(batch))
    sha = _head_sha()

    rc = adv.main(["--commit", sha])
    assert rc == 0, f"rc={rc}"
    text = _read_draft(batch, sha[:12])
    for probe in FOUR_PROBE:
        assert probe in text, f"产物缺四问里的「{probe}」"
    for probe in HARD_PROBE:
        assert probe in text, f"产物缺硬要求里的「{probe}」"
    assert "改动文件清单" in text, "缺改动文件清单小标题"
    assert "跟进卡清单" in text, "缺『产出是跟进卡清单』这句"
    # 真 sha 的改动文件清单不该是空的（这一笔确实改了文件）
    assert ".md" in text or ".py" in text, "改动文件清单看着是空的"


def test_nail143_05_reuses_impact_tool_when_present(tmp_path, monkeypatch):
    """⑤-a 真复用影响面：桩掉 `wb_impact.py`（`TF_IMPACT_TOOL`）⇒ 产物里出现桩的输出。"""
    batch = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(batch))
    stub = tmp_path / "fake_impact.py"
    stub.write_text("import sys\nprint('IMPACT-STUB ' + ' '.join(sys.argv[1:]))\n",
                    encoding="utf-8")
    monkeypatch.setenv("TF_IMPACT_TOOL", str(stub))

    sha = _head_sha()
    assert adv.main(["--commit", sha]) == 0
    text = _read_draft(batch, sha[:12])
    assert "IMPACT-STUB" in text, "没复用影响面工具（桩的输出没进产物）"


def test_nail143_05b_degrades_when_impact_missing(tmp_path, monkeypatch):
    """⑤-b 拿不到影响面 ⇒ **明确降级**说「拿不到影响面」，**不硬编门表**。"""
    batch = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(batch))
    monkeypatch.setenv("TF_IMPACT_TOOL", str(tmp_path / "没有这个工具.py"))

    sha = _head_sha()
    assert adv.main(["--commit", sha]) == 0
    text = _read_draft(batch, sha[:12])
    assert "拿不到影响面" in text, "拿不到影响面时没有明确降级"
    # 反证：降级时**不许**自己编一张门表（不该出现门禁工具名之类的"硬编"痕迹）
    assert "DOOR_INPUTS" not in text, "降级时还硬编了门表"


def test_nail143_06_rules_section_has_five_keywords():
    """⑥ 规矩可查：对抗复核那一节含「提交之后 / 异步 / 不挡 / 不同族 / 不可逆」五词。"""
    text = (ROOT / "复盘" / "外包-卡表与规矩.md").read_text(encoding="utf-8")
    marker = "## §25 对抗复核（外包验收）"
    start = text.find(marker)
    assert start != -1, "规矩文档里没有对抗复核那一节（§25）"
    # 到下一个一级/二级标题（`\n## ` / `\n### ` 之外的平级节）为止
    rest = text[start + len(marker):]
    end = rest.find("\n## ")
    section = rest if end == -1 else rest[:end]
    for word in ("提交之后", "异步", "不挡", "不同族", "不可逆"):
        assert word in section, f"对抗复核那一节缺关键词「{word}」"


def _register_task_with_commit(tmp_path, commit: str) -> None:
    """建一个真任务（一成员一提交）：register → claim → landed。"""
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    man = src / "T-ADV.toml"
    man.write_text(
        'id = "T-ADV"\nwhy = "生成器自证任务"\non_complete = ["draft"]\n'
        '\n[[member]]\nid = "M-1"\nlayer = "后端"\nwhat = "干了点活"\n'
        'paths = ["tools/a/*"]\n', encoding="utf-8", newline="\n")
    assert pool_task.main(["register", str(man)]) == 0
    assert pool_task.main(["claim", "T-ADV", "M-1", "--evidence", "pytest ok",
                           "--files", "tools/a/x.py", "--why", "新能力：加了一条守卫"]) == 0
    assert pool_task.main(["landed", "T-ADV", "--commit", commit]) == 0


def test_nail143_07_task_form_pulls_abilities_and_commit(tmp_path, monkeypatch):
    """⑦ `--task <任务号>` ⇒ 产物含成员 claim 的 why（新能力）+ 落地的 commit 与改动清单。"""
    batch = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(batch))
    sha = _head_sha()
    _register_task_with_commit(tmp_path, sha)

    assert adv.main(["--task", "T-ADV"]) == 0
    text = _read_draft(batch, "T-ADV")
    assert "新能力：加了一条守卫" in text, "没从成员 claim 抽出新能力"
    assert sha[:12] in text, "没带上落地的 commit"
    assert "改动文件清单" in text
