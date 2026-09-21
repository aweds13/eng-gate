"""G 批 · T-G1：可配置词表（复习形式 / 热力图维度）—— SR-NF7「不改核心就能加」。

**口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §6）**：`SR-NF7` 说的"能加功能/字段/
复习形式/可视化/集成"，逐项看下来**真正不改核心就能加的只有词表**（一串 `id → 中文标签`）；
**加字段**要动 schema 迁移、**加功能**要写领域函数 + 路由 + 界面 —— 这两件如实标注做不到。

本卡落地的是**扩展点本身**：词表在 `timeflow/vocab.py` **声明一处**，配置校验、默认值、拒绝非法值、
界面增删、API 读写全都自动跟着走。同时把两处原来的写死换成词表驱动：
复习形式（`review._FORMATS` → 词表）与热力图维度（前端 `HM_METRICS` → 后端词表）。

覆盖：
- 校验：id 字符集 / 标签非空与长度 / 条数上下限 / `allowed` 名单 / 空表 / 非表输入；
- 三层默认：内置 → `config.toml` → `app_settings`（逐层优先），脏值退回默认不崩；
- **坏配置要出声**：config.toml 里写错当场报错（不静默回落）；
- 复习形式：自定义形式能建卡、不在词表里的被拒（带原话）、改名（同 id 换标签）、
  删掉某形式后**已有卡照旧可读**、`default_form` 的取法（qa 在就用它，删了就取第一项）；
- 热力图维度：单位/种类来自 `HEATMAP_FIELDS`、`allowed` 与之一致（算不出来的维度配不进去）、
  顺序 = 界面顺序；
- API：`GET/PUT /api/settings/vocab`、`POST …/reset`（非法值 400，本机页面限定）；
  改完 `/api/review/meta` 与 `/api/insights/heatmap-dimensions` 立刻跟着变；
- 界面：不再有写死的维度表（顺手修掉的老缺陷见 T-G3）。
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from timeflow import vocab
from timeflow.api.app import create_app
from timeflow.config import load_settings
from timeflow.core import facts as facts_mod
from timeflow.core import insights as ins
from timeflow.core import review as rv
from timeflow.storage import db as db_mod

KEY_FORMS = vocab.REVIEW_FORMS.key
KEY_DIMS = vocab.HEATMAP_DIMENSIONS.key


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "vocab.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


def _client(tmp_path, name: str = "vocab_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


def _items(client: TestClient, key: str) -> list[str]:  # type: ignore[no-untyped-def]
    body = client.get("/api/settings/vocab").json()
    table = next(t for t in body["items"] if t["key"] == key)
    return [x["id"] for x in table["items"]]


# ---------------------------------------------------------------- 校验


def test_parse_rejects_bad_ids_and_labels() -> None:
    """id 字符集 / 标签非空与长度 / 条数 —— 非法值**一律拒绝**（不静默回落）。"""
    table = vocab.REVIEW_FORMS
    with pytest.raises(ValueError, match="只能用小写英文"):
        vocab.parse({"菜谱": "菜谱卡"}, table)
    with pytest.raises(ValueError, match="只能用小写英文"):
        vocab.parse({"Qa": "大写"}, table)
    with pytest.raises(ValueError, match="标签不能为空"):
        vocab.parse({"recipe": "   "}, table)
    with pytest.raises(ValueError, match="最多 40 字"):
        vocab.parse({"recipe": "长" * 41}, table)
    with pytest.raises(ValueError, match="这样的表"):
        vocab.parse(["recipe"], table)
    with pytest.raises(ValueError, match="至少要留一项"):
        vocab.parse({}, table)


def test_parse_limits_count_and_normalizes_whitespace() -> None:
    """条数有上限；id 前后的空白会被规整，规整后撞车算重复。"""
    small = vocab.Vocabulary(
        key="t", title="测试表", question="?", builtin=(("a", "A"),), max_items=2
    )
    assert list(vocab.parse({"a": " A "}, small)) == ["a"]
    assert vocab.parse({"a": "A"}, small)["a"] == "A"  # 标签也会 strip
    with pytest.raises(ValueError, match="最多 2 项"):
        vocab.parse({"a": "A", "b": "B", "c": "C"}, small)
    with pytest.raises(ValueError, match="重复了"):
        vocab.parse({"qa": "问答", " qa ": "又一个"}, vocab.REVIEW_FORMS)


def test_allowed_list_is_enforced() -> None:
    """`allowed` 不为空时，id 必须是名单里的（热力图维度必须对应真算得出来的字段）。"""
    with pytest.raises(ValueError, match="不认识这个 id"):
        vocab.parse({"focus": "专注"}, vocab.HEATMAP_DIMENSIONS)
    assert list(vocab.parse({"focus_minutes": "专注"}, vocab.HEATMAP_DIMENSIONS)) == [
        "focus_minutes"
    ]


def test_heatmap_fields_and_allowed_agree() -> None:
    """`HEATMAP_FIELDS`（哪些数算得出来）与词表的 `allowed`（哪些 id 能配）必须一致 —— 少一个就会
    出现"配了但算不出来"的维度，多一个就是"能算但配不进去"。"""
    assert set(vocab.HEATMAP_DIMENSIONS.allowed or []) == set(ins.HEATMAP_FIELDS)


# ---------------------------------------------------------------- 三层默认与读写


def test_three_layer_defaults(conn) -> None:  # type: ignore[no-untyped-def]
    """内置 → config.toml → app_settings：逐层优先；`reset` 是**删掉本机那条**（回到配置/内置）。"""
    builtin = dict(vocab.REVIEW_FORMS.builtin)
    assert vocab.get(conn, vocab.REVIEW_FORMS) == builtin
    assert vocab.is_default(conn, vocab.REVIEW_FORMS) is True

    from_config = {"recipe": "菜谱卡", "qa": "问答卡"}
    assert vocab.get(conn, vocab.REVIEW_FORMS, from_config) == from_config

    ours = {"mine": "我的形式"}
    vocab.set_items(conn, vocab.REVIEW_FORMS, ours)
    assert vocab.get(conn, vocab.REVIEW_FORMS, from_config) == ours  # 本机优先
    assert vocab.is_default(conn, vocab.REVIEW_FORMS, from_config) is False

    vocab.reset(conn, vocab.REVIEW_FORMS)
    assert vocab.get(conn, vocab.REVIEW_FORMS, from_config) == from_config
    assert vocab.get(conn, vocab.REVIEW_FORMS) == builtin


def test_set_items_is_idempotent_and_validates(conn) -> None:  # type: ignore[no-untyped-def]
    """整张替换：设两次同一个值不会写出两行；非法值不落库。"""
    vocab.set_items(conn, vocab.REVIEW_FORMS, {"a": "A"})
    vocab.set_items(conn, vocab.REVIEW_FORMS, {"a": "A"})
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM app_settings WHERE key = ?",
        (vocab.REVIEW_FORMS.setting_key,),
    ).fetchone()
    assert int(rows["n"]) == 1
    with pytest.raises(ValueError):
        vocab.set_items(conn, vocab.REVIEW_FORMS, {"坏": "坏"})
    assert vocab.get(conn, vocab.REVIEW_FORMS) == {"a": "A"}  # 拒绝之后原值还在


def test_dirty_stored_value_falls_back(conn) -> None:  # type: ignore[no-untyped-def]
    """库里那条值坏了（手改过库/老版本）→ 退回默认，不让整个页面读不出来。"""
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?)",
        (vocab.REVIEW_FORMS.setting_key, "{不是 json"),
    )
    conn.commit()
    assert vocab.get(conn, vocab.REVIEW_FORMS) == dict(vocab.REVIEW_FORMS.builtin)

    vocab.set_items(conn, vocab.REVIEW_FORMS, {"a": "A"})
    conn.execute(
        "UPDATE app_settings SET value = ? WHERE key = ?",
        ('{"坏": "坏"}', vocab.REVIEW_FORMS.setting_key),
    )
    conn.commit()
    assert vocab.get(conn, vocab.REVIEW_FORMS) == dict(vocab.REVIEW_FORMS.builtin)


def test_by_key_rejects_unknown() -> None:
    """未知词表 → ValueError 带原话（界面拿到的是后端说法，不是 500）。"""
    with pytest.raises(ValueError, match="没有这张词表"):
        vocab.by_key("nope")
    with pytest.raises(ValueError):
        vocab.by_key(123)


# ---------------------------------------------------------------- 坏配置要出声


def test_bad_config_toml_is_rejected_loudly(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """config.toml 里词表写错 → **当场报错**（不静默回落成默认，否则用户以为配置生效了）。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[review]\nforms = { "菜谱" = "菜谱卡" }\n', encoding="utf-8"
    )
    with pytest.raises(Exception, match="只能用小写英文"):
        load_settings(cfg)

    cfg.write_text(
        '[insights]\nheatmap_dimensions = { focus = "专注" }\n', encoding="utf-8"
    )
    with pytest.raises(Exception, match="不认识这个 id"):
        load_settings(cfg)

    cfg.write_text('[review]\nforms = { recipe = "菜谱卡" }\n', encoding="utf-8")
    settings = load_settings(cfg)
    assert list(settings.review.forms) == ["recipe"]


# ---------------------------------------------------------------- 复习形式


def test_review_forms_drive_create_and_default(conn) -> None:  # type: ignore[no-untyped-def]
    """自定义形式能建卡；不在词表里的被拒（带原话）；默认形式 qa 在就用 qa。"""
    assert rv.default_form(conn) == "qa"
    assert rv.create_item(conn, "默认形式的卡")  # 不传 form → qa
    row = conn.execute("SELECT form FROM review_items ORDER BY created_at").fetchone()
    assert row["form"] == "qa"

    vocab.set_items(conn, vocab.REVIEW_FORMS, {"recipe": "菜谱卡"})
    assert rv.default_form(conn) == "recipe"  # qa 被删 → 取第一项
    rid = rv.create_item(conn, "菜谱")  # 用新的默认（recipe）
    assert rv.get_item(conn, rid)["form"] == "recipe"
    with pytest.raises(ValueError, match="非法复习形式"):
        rv.create_item(conn, "乱写", form="qa")  # qa 已不在词表里
    with pytest.raises(ValueError, match="现在能用的：recipe"):
        rv.create_item(conn, "乱写", form="nope")


def test_removing_a_form_keeps_existing_cards(conn) -> None:  # type: ignore[no-untyped-def]
    """删掉某个形式**不影响已有的卡**（它只是个标签；读出来照旧，界面照旧显示原标签）。"""
    rid = rv.create_item(conn, "老卡", form="cloze")
    vocab.set_items(conn, vocab.REVIEW_FORMS, {"qa": "问答卡"})
    assert rv.get_item(conn, rid)["form"] == "cloze"     # 读得到
    assert "cloze" not in rv.forms(conn)                 # 但不再能新建
    assert rv.update_item(conn, rid, form="qa")["form"] == "qa"  # 还是能改成词表里的


def test_meta_reflects_the_vocabulary(conn) -> None:  # type: ignore[no-untyped-def]
    """`meta()` 跟着词表走：界面拿它渲染下拉，中文标签仍然只在后端一处。"""
    vocab.set_items(conn, vocab.REVIEW_FORMS, {"recipe": "菜谱卡", "qa": "问答卡"})
    meta = rv.meta(conn)
    assert [f["value"] for f in meta["forms"]] == ["recipe", "qa"]
    assert [f["label"] for f in meta["forms"]] == ["菜谱卡", "问答卡"]
    assert meta["default_form"] == "qa"
    assert [s["value"] for s in meta["sources"]] == ["internal", "external"]


def test_rename_keeps_position(conn) -> None:  # type: ignore[no-untyped-def]
    """同 id 换标签 = 改名（位置不变）—— 界面「加一项」填已有 id 时就是这个行为。"""
    vocab.set_items(conn, vocab.REVIEW_FORMS, {"a": "甲", "b": "乙"})
    items = dict(vocab.get(conn, vocab.REVIEW_FORMS))
    items["a"] = "甲（改名）"
    vocab.set_items(conn, vocab.REVIEW_FORMS, items)
    assert list(vocab.get(conn, vocab.REVIEW_FORMS)) == ["a", "b"]
    assert vocab.get(conn, vocab.REVIEW_FORMS)["a"] == "甲（改名）"


# ---------------------------------------------------------------- 热力图维度


def test_heatmap_dimensions_carry_unit_and_kind(conn) -> None:  # type: ignore[no-untyped-def]
    """维度词表贴回"单位/种类"给界面 —— 顺序 = 界面按钮顺序，单位来自字段注册表。"""
    default = ins.heatmap_dimensions(conn)   # 没配置时用内置（专注排第一）
    assert [d["id"] for d in default["items"]] == [
        k for k, _ in vocab.HEATMAP_DIMENSIONS.builtin
    ]

    vocab.set_items(
        conn, vocab.HEATMAP_DIMENSIONS, {"review_count": "复习", "focus_minutes": "专注"}
    )
    assert ins.heatmap_dimensions(conn)["items"] == [
        {"id": "review_count", "label": "复习", "unit": "张", "kind": "count"},
        {"id": "focus_minutes", "label": "专注", "unit": "分钟", "kind": "minutes"},
    ]
    # 传 defaults 只影响"没配置时的兜底"，不影响"本机改过的优先"
    assert [d["id"] for d in ins.heatmap_dimensions(conn, {"debt_count": "债务"})["items"]] == [
        "review_count", "focus_minutes"
    ]


def test_heatmap_values_are_readable_by_dimension_id(conn) -> None:  # type: ignore[no-untyped-def]
    """**维度 id 必须就是数据字段名**（T-G3 的缺陷就是这里出过问题：前端拿 'focus' 去取
    `focus_minutes`，取不到 → 整张图永远是灰的）。这条把"词表里的 id"与"热力图的字段"钉在一起。"""
    cell = ins.heatmap(conn, days=1)[0]
    for field in ins.HEATMAP_FIELDS:
        assert hasattr(cell, field), field
        assert field in cell.model_dump(), field
    assert ins.heatmap(conn, days=1)[0].date == date.today().isoformat()


# ---------------------------------------------------------------- API


def test_api_vocab_roundtrip_and_errors(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """三条通用路由：读整表 / 改一张 / 回默认；非法值 400（不静默落默认值）。"""
    client = _client(tmp_path)
    body = client.get("/api/settings/vocab").json()
    assert {t["key"] for t in body["items"]} == {KEY_FORMS, KEY_DIMS}
    assert body["note"]
    table = next(t for t in body["items"] if t["key"] == KEY_FORMS)
    assert table["is_default"] is True and table["free_id"] is True

    ok = client.put("/api/settings/vocab",
                    json={"key": KEY_FORMS, "items": {"recipe": "菜谱卡", "qa": "问答卡"}})
    assert ok.status_code == 200
    assert _items(client, KEY_FORMS) == ["recipe", "qa"]
    assert [f["value"] for f in client.get("/api/review/meta").json()["forms"]] == ["recipe", "qa"]

    assert client.put("/api/settings/vocab",
                      json={"key": KEY_FORMS, "items": {"菜谱": "菜谱卡"}}).status_code == 400
    assert client.put("/api/settings/vocab",
                      json={"key": "nope", "items": {"a": "A"}}).status_code == 400
    assert client.put("/api/settings/vocab",
                      json={"key": KEY_FORMS, "items": {}}).status_code == 400
    assert client.put("/api/settings/vocab",
                      json={"key": KEY_DIMS, "items": {"focus": "专注"}}).status_code == 400

    back = client.post("/api/settings/vocab/reset", json={"key": KEY_FORMS})
    assert back.status_code == 200
    assert _items(client, KEY_FORMS) == [k for k, _ in vocab.REVIEW_FORMS.builtin]
    assert client.post("/api/settings/vocab/reset", json={"key": "nope"}).status_code == 400


def test_api_heatmap_dimensions_follow_settings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """统计页的维度按钮由这个接口给 —— 设置页改完立刻跟着变。"""
    client = _client(tmp_path, "dims.db")
    first_two = [d["id"] for d in client.get("/api/insights/heatmap-dimensions").json()["items"]]
    assert first_two[:2] == ["focus_minutes", "manual_minutes"]
    client.put("/api/settings/vocab",
               json={"key": KEY_DIMS, "items": {"debt_count": "债务", "focus_minutes": "专注"}})
    got = client.get("/api/insights/heatmap-dimensions").json()["items"]
    assert [(d["id"], d["unit"], d["kind"]) for d in got] == [
        ("debt_count", "项", "count"), ("focus_minutes", "分钟", "minutes")
    ]


def test_api_review_create_with_custom_form(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """自定义形式从建卡到读回整条链都通（这就是"不改核心就能加"要证明的事）。"""
    client = _client(tmp_path, "custom.db")
    client.put("/api/settings/vocab", json={"key": KEY_FORMS, "items": {"recipe": "菜谱卡"}})
    created = client.post("/api/review/items", json={"title": "红烧肉", "form": "recipe"})
    assert created.status_code == 200
    rid = created.json()["id"]
    assert client.get(f"/api/review/items/{rid}").json()["form"] == "recipe"
    # 不在词表里的形式照样 400（不因为"能自己加"就什么字符串都收）
    bad = client.post("/api/review/items", json={"title": "乱写", "form": "nope"})
    assert bad.status_code == 400
    assert "现在能用的：recipe" in bad.json()["detail"]


def test_api_patch_body_cannot_smuggle_domain_params(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """PATCH 的 body 先按 `EDITABLE_FIELDS` 过滤：body 里塞领域参数名（`forms_defaults`）既不该
    500，也不该改变任何东西。"""
    client = _client(tmp_path, "smuggle.db")
    rid = client.post("/api/review/items", json={"title": "卡", "form": "qa"}).json()["id"]
    resp = client.patch(f"/api/review/items/{rid}",
                        json={"title": "改名了", "forms_defaults": None, "reps": 99})
    assert resp.status_code == 200
    got = client.get(f"/api/review/items/{rid}").json()
    assert got["title"] == "改名了"
    assert got["reps"] == 0
    assert set(rv.EDITABLE_FIELDS) == {"title", "form", "source", "ref_handle"}


# ---------------------------------------------------------------- 界面（顺手修的缺陷见 T-G3）


def test_frontend_has_no_hardcoded_dimension_table() -> None:
    """界面不再写死维度表：按钮/取值都走 `/api/insights/heatmap-dimensions` 给的 id。"""
    html = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "src" / "web" / "index.html"
    ).read_text(encoding="utf-8")
    assert "HM_METRICS" not in html, "维度表必须从后端拿，不许在前端再写一份"
    assert "'/api/insights/heatmap-dimensions'" in html
    assert "'/api/settings/vocab'" in html
