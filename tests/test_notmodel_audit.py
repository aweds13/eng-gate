"""钉子测试：`tools/notmodel_audit.py`（卡 219 · 批 B-20261016 · T-G333）。

判据（先红后绿）：
- 每条四样齐 + 出处 ⇒ 绿；缺一样（如「替代做法」）⇒ **红并点名**是哪条、缺哪样；
- ★ 反向保护：清单文件不存在 ⇒ 报「没有」，**不许当通过**；
  解析到 0 条 ⇒ 报「0 条」，同样不许当通过；
- ★ 判据要能证明自己看得见东西：同一条缺「替代做法」⇒ 必红（本文件的 `test_*_is_red` 就是那一步）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import notmodel_audit as audit  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

# 一条「四样 + 出处」齐的条目（绿）。
_ITEM_OK = """\
### NM-01 不建独立「目标」实体
- **不建什么**：独立的目标实体。
- **为什么不做**：伪需求，避免过度抽象。
- **谁拍的**：N3 结算。
- **替代做法**：目标 = 任务分组 / 项目，用 N8 自定义分组涵盖。
- **出处**：docs/intention/needs.md N3 结算。
"""

# 同一条，**故意缺「替代做法」**（必红）。
_ITEM_MISSING_REPLACEMENT = """\
### NM-01 不建独立「目标」实体
- **不建什么**：独立的目标实体。
- **为什么不做**：伪需求，避免过度抽象。
- **谁拍的**：N3 结算。
- **出处**：docs/intention/needs.md N3 结算。
"""


# ---------------------------------------------------------- 绿：四样齐
def test_complete_item_is_green(tmp_path):
    doc = tmp_path / "清单.md"
    doc.write_text(_ITEM_OK, encoding="utf-8")
    assert audit.check_doc(doc) == []


# ---------------------------------------------------------- 红：缺「替代做法」
def test_missing_replacement_is_red_and_names_it(tmp_path):
    doc = tmp_path / "清单.md"
    doc.write_text(_ITEM_MISSING_REPLACEMENT, encoding="utf-8")
    problems = audit.check_doc(doc)
    assert problems, "缺「替代做法」没被抓住 —— 判据没看见东西"
    assert any("NM-01" in p and "替代做法" in p for p in problems), problems


def test_missing_any_of_the_four_is_red(tmp_path):
    """四样缺任意一样都要红（不只「替代做法」那一格）。"""
    for field in ("不建什么", "为什么不做", "谁拍的", "替代做法"):
        body = "\n".join(
            f"- **{f}**：x。" for f in audit.REQUIRED_FIELDS if f != field
        )
        doc = tmp_path / f"缺{field}.md"
        doc.write_text(f"### NM-07 一条\n{body}\n", encoding="utf-8")
        problems = audit.check_doc(doc)
        assert any(field in p and "NM-07" in p for p in problems), (field, problems)


# ---------------------------------------------------------- 反向保护（不许当通过）
def test_missing_file_is_red_not_pass(tmp_path):
    problems = audit.check_doc(tmp_path / "没有这份.md")
    assert problems, "文件不存在竟然当通过了 —— 反向保护失效"
    assert any("没有" in p for p in problems), problems


def test_zero_items_is_red_not_pass(tmp_path):
    doc = tmp_path / "空清单.md"
    doc.write_text("# 标题\n\n只有一段话，没有 `### NM-` 条目。\n", encoding="utf-8")
    problems = audit.check_doc(doc)
    assert problems, "0 条竟然当通过了"
    assert any("0 条" in p for p in problems), problems


# ---------------------------------------------------------- 只管结论区，不判「找不到出处」节
def test_unverified_section_is_not_judged(tmp_path):
    doc = tmp_path / "清单.md"
    tail = (
        "## 四、我记得、但找不到出处（不作为结论）\n\n"
        "- **不测精力 / 情绪**：只有一句约束，找不到为什么/谁拍的/替代做法。\n"
    )
    doc.write_text(_ITEM_OK + "\n" + tail, encoding="utf-8")
    assert audit.check_doc(doc) == [], "「找不到出处」那节的散列表被误判了"


# ---------------------------------------------------------- CLI 接线
def test_main_returns_1_on_bad_and_0_on_good(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text(_ITEM_MISSING_REPLACEMENT, encoding="utf-8")
    good = tmp_path / "good.md"
    good.write_text(_ITEM_OK, encoding="utf-8")
    assert audit.main(["--path", str(bad)]) == 1
    assert audit.main(["--path", str(good)]) == 0


# ---------------------------------------------------------- 真实仓库回归
def test_real_doc_exists_and_passes():
    """真清单必须存在且全过 —— 这是本卡的产物，不是合成样例。"""
    assert audit.DEFAULT_PATH.exists(), f"真清单没建：{audit.DEFAULT_PATH}"
    assert audit.check_doc() == [], audit.check_doc()


def test_real_doc_actually_has_items_with_sources():
    """判据确实看得见东西：真清单里条目数是正的，且每条都带「出处」。"""
    items = audit.split_items(audit.DEFAULT_PATH.read_text(encoding="utf-8"))
    assert len(items) >= 10, f"真清单条目太少：{len(items)}"
    assert {it["id"] for it in items} >= {"NM-01", "NM-02"}
    for it in items:
        assert "出处" in it["body"], f"{it['id']} 没有出处"
