"""卡 E97：usage_in() 的模型名归一口径（别名 + 大小写不敏感）。

为什么值当测：gates/diag/wb-usage.jsonl 的「模型」字段写的是小写裸名 glm-5.2，
注册表里写的是 huaweicloud-maas/GLM-5.2；不归一的话 usage_in("huaweicloud-maas/GLM-5.2", ...)
恒回 0 —— 整窗估算的分子永远 0（不是「用量小」，是「没看见」）。
真机 2026-11-09 读：两种写法都回 143312742（测试用合成 JSONL 钉「同一份」，不钉这个
绝对值 —— 日志天天长）。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 三档别名 | model_aliases() 复用 id_names，不另写一套 | 若自创切分规则（多切一刀/少切一刀） |
| ② 大小写 | 大写行对小写查询、小写行对大写查询，双向命中 | 若只 lower() 了行没 lower() 查询 |
| ③ 任一别名命中 | usage_in() 的三种写法回同一个 tokens | 若仍在比字面 |
| ④ 注册表坏 | 退回字面相等（不是「一律 0」） | 若把 fail-open 写成 fail-closed |
| ⑤ 只读一次盘 | 连续调用只 load_registry() 一次 | 若每行读一次表 |

★ 一条真实钟表 / 真实日志都不碰：区间端点写死，JSONL 现造在 tmp_path 里。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import model_registry  # noqa: E402

TZ = timezone(timedelta(hours=8))

START = datetime(2026, 1, 1, 0, 0, tzinfo=TZ)
END = datetime(2027, 1, 1, 0, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def _fresh_alias_cache():
    """每条用例都从「没读过盘」开始（别名表是模块级缓存，会跨用例串味）。"""
    wb_dispatch.reset_model_aliases()
    yield
    wb_dispatch.reset_model_aliases()


def _row(model: str, tokens: int, began: str = "2026-06-01T10:00:00") -> dict:
    """一行最小可用的 wb-usage 记录（字段名照 append_usage_line() 写的）。"""
    return {
        "卡": "E97",
        "模型": model,
        "轮次": 1,
        "开始": began,
        "结束": "2026-06-01T10:05:00",
        "用时分钟": 5.0,
        "input_tokens": tokens,
        "output_tokens": 0,
        "cache_read": 0,
        "退出码": 0,
        "判决": "正常收工",
    }


def _write_usage(root: Path, rows: list[dict]) -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    (diag / "wb-usage.jsonl").write_text(text + "\n", encoding="utf-8")


# ---------------------------------------------------------------- ① 三档别名


def test_model_aliases_reuses_id_names_three_tiers():
    """① 别名就是 id_names 那三档（原样 / 最后一个斜杠后 / 第一个斜杠后）。"""
    tiers = model_registry.id_names("huaweicloud-maas/GLM-5.2")
    assert tiers == ("huaweicloud-maas/GLM-5.2", "GLM-5.2", "GLM-5.2")
    got = wb_dispatch.model_aliases("huaweicloud-maas/GLM-5.2")
    assert set(tiers) <= set(got), got
    assert len(got) == len(set(got))  # 重复档位只留一份
    assert wb_dispatch.model_aliases("glm-5.3-flash") == ("glm-5.3-flash",)
    assert wb_dispatch.model_aliases("") == ()  # 不给「空串命中一切」留门
    assert wb_dispatch.model_aliases("   ") == ()


# ---------------------------------------------------------------- ② 大小写双向


def test_matches_model_is_case_insensitive_both_ways():
    """② 注册表写大写、用量行写小写（以及反过来）都要算同一个模型。"""
    assert wb_dispatch._matches_model("glm-5.2", "huaweicloud-maas/GLM-5.2")
    assert wb_dispatch._matches_model("GLM-5.2", "glm-5.2")
    assert wb_dispatch._matches_model("huaweicloud-maas/glm-5.2", "GLM-5.2")
    assert not wb_dispatch._matches_model("glm-5.3", "glm-5.2")
    assert not wb_dispatch._matches_model("", "glm-5.2")
    assert not wb_dispatch._matches_model(None, "glm-5.2")


# ---------------------------------------------------------------- ③ 任一别名命中


def test_usage_in_counts_every_alias_of_the_same_model(tmp_path):
    """③ 同一个模型的三种写法在同一窗口里，三种查询回同一个 tokens。"""
    _write_usage(
        tmp_path,
        [
            _row("glm-5.2", 30),
            _row("GLM-5.2", 7),
            _row("huaweicloud-maas/GLM-5.2", 5),
            _row("glm-5.3", 1000),  # 别的模型：一个 token 都不许算进来
        ],
    )
    want = (42, 0.0)
    assert wb_dispatch.usage_in("huaweicloud-maas/GLM-5.2", START, END, root=tmp_path) == want
    assert wb_dispatch.usage_in("glm-5.2", START, END, root=tmp_path) == want
    assert wb_dispatch.usage_in("GLM-5.2", START, END, root=tmp_path) == want
    # 归一没有把「像的名字」也吞进来
    assert wb_dispatch.usage_in("glm-5.3", START, END, root=tmp_path) == (1000, 0.0)


# ---------------------------------------------------------------- ④ 注册表坏则字面相等


def test_registry_failure_falls_back_to_literal_equality(tmp_path, monkeypatch):
    """④ 注册表读不到就退回今天的字面相等，不许把用量一律算成 0。"""

    def boom():
        raise model_registry.ModelRegistryError("注册表坏了（本用例故意）")

    monkeypatch.setattr(wb_dispatch, "load_registry", boom)
    wb_dispatch.reset_model_aliases()
    # 别名只剩 id_names 三档（没有注册表可查，补不出别的写法）
    assert wb_dispatch.model_aliases("huaweicloud-maas/GLM-5.2") == (
        "huaweicloud-maas/GLM-5.2",
        "GLM-5.2",
    )
    # 匹配退回字面相等：同名命中，不同写法不命中
    assert wb_dispatch._matches_model("glm-5.2", "glm-5.2")
    assert not wb_dispatch._matches_model("glm-5.2", "huaweicloud-maas/GLM-5.2")
    # 关键：字面相等的行仍然算得出来（fail-open 的反面就是「注册表坏了则分子恒 0」）
    _write_usage(tmp_path, [_row("glm-5.2", 30)])
    assert wb_dispatch.usage_in("glm-5.2", START, END, root=tmp_path) == (30, 0.0)
    # 换个别名写法确实读不到 —— 这是「今天的口径」，不是静默错误
    assert wb_dispatch.usage_in("huaweicloud-maas/GLM-5.2", START, END, root=tmp_path) == (0, 0.0)


# ---------------------------------------------------------------- ⑤ 只读一次盘


def test_alias_table_reads_disk_only_once(monkeypatch):
    """⑤ 连续调用只 load_registry() 一次；清缓存钩子之后才重读。"""
    calls: list[int] = []
    real = wb_dispatch.load_registry

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(wb_dispatch, "load_registry", counting)
    wb_dispatch.reset_model_aliases()
    for _ in range(5):
        wb_dispatch.model_aliases("glm-5.2")
        wb_dispatch._matches_model("glm-5.2", "huaweicloud-maas/GLM-5.2")
    assert len(calls) == 1, f"别名表读了 {len(calls)} 次盘"
    wb_dispatch.reset_model_aliases()
    wb_dispatch.model_aliases("glm-5.2")
    assert len(calls) == 2
