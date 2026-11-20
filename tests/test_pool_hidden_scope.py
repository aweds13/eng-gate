r"""F95 的两条 SKIP：本仓**没有**这两个宿主（卡 A383 · T-AG671）—— 钉成会响的闹钟。

原件 F95 的完整三步是「图像模型 deny list / `listed=no` 的路由组 / 隐藏图像模型仍能画」。
本卡只搬了第三步那句**「列出来的必须能用」**（`/v1/models` 每条带 `disabled` 读数，
判据与 `_model_block` 同一份 `model_registry.model_disabled`）。前两步**不移植**，
理由不是「原件不对」，而是**本仓没有它们的宿主**：

- 图像模型 deny list（`hiddenDrawers` / `OfferedDrawers`）—— **没有宿主** ⇒ SKIP ①。
  清单是**文本模型**的批准集（`tools/pool/models.py:127` 取 `row.get("model")`），
  没有「聊天选择器被图像模型污染」这个场景；`PATHS` 恰四条路由、没有图像面。
- `magpie group set <id> listed=no` 的路由组 —— **没有这一层** ⇒ SKIP ②。
  注册表只有 `[[model]]` 与 `[pool.codearts]`，没有 `[group]` 段；
  `ModelEntry` 的字段里没有 `listed` / `hidden`。

★ 这两条是**闹钟**：哪天本仓长出 `/v1/images` 面（或注册表出现 `[group]` / `ModelEntry`
  长出 `listed` 字段），它们会红 —— 那时候该重开对应的 SKIP，而不是把断言放宽。

| 钉子 | 钉哪一位 |
|---|---|
| `test_no_image_denylist_host_exists` | `tools/**/*.py` 无三件套名，`PATHS` 无 image / draw |
| `test_no_routing_group_layer_exists` | 无 `[group` 段，`ModelEntry` 无 listed / hidden |
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool.gateway as gateway  # noqa: E402
import pool.model_registry as pool_model_registry  # noqa: E402

# 原件图像层三件套的名字：本仓一个都不该有（有 = 那个宿主长出来了）
DRAWER_NAMES = ("hiddenDrawers", "OfferedDrawers", "drawingModel")


def test_no_image_denylist_host_exists() -> None:
    """★ SKIP ①：本仓没有图像模型 deny list 的宿主（没有绘图件名、没有图像路由面）。

    ★ 为什么是「找宿主」而不是「找开关」：`hiddenDrawers` 是 `providers.json` 里的
      deny list，它的语义绑在**图像模型**这一层。本仓连图像面都没有，抄一个 deny list
      过来只会是一条谁也不读的死配置 —— 把「没有宿主」钉住，比留一段「以后可能用」更诚实。
    ★ 反向（怎么知道它会响）：在 `tools/pool/gateway.py` 的 `PATHS` 里加一条
      `"/v1/images"` ⇒ 这条红。
    """
    hits: list[str] = []
    for path in (ROOT / "tools").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in DRAWER_NAMES:
            if needle in text:
                hits.append(f"{path.relative_to(ROOT)}:{needle}")
    assert hits == [], f"本仓长出图像 deny list 的宿主了 ⇒ 重开 F95 SKIP ①：{hits}"
    image_paths = [k for k in gateway.PATHS if "image" in k or "draw" in k]
    assert image_paths == [], (
        f"网关多出图像 / 绘图路由 {image_paths} —— 图像模型面的宿主长出来了，"
        "重开 F95 SKIP ① 再决定要不要搬 deny list"
    )


def test_no_routing_group_layer_exists() -> None:
    """★ SKIP ②：本仓没有「路由组」这一层（没有 `[group]` 段，`ModelEntry` 没有 listed 字段）。

    ★ `listed=no` 的语义是「在**路由组**里不列出」。本仓的分组是 `[pool.*]`（号池），
      不是路由组；给 `ModelEntry` 硬加一个 `listed` 字段会造出第二个「列不列出来」的开关，
      与本卡的 `disabled`（**拒绝**维度）语义打架 —— 那正是要避免的第二份判据。
    ★ 反向（怎么知道它会响）：在 `tools/pool/model-registry.toml` 里加一段 `[[group]]`，
      或给 `ModelEntry` 加 `listed` 字段 ⇒ 这条红。
    """
    text = (ROOT / "tools" / "pool" / "model-registry.toml").read_text(encoding="utf-8")
    assert "[group" not in text, (
        "model-registry.toml 里出现 [group 段 ⇒ 路由组这一层长出来了，重开 F95 SKIP ②"
    )
    fields = {f.name for f in dataclasses.fields(pool_model_registry.ModelEntry)}
    for bad in ("listed", "hidden"):
        assert bad not in fields, (
            f"ModelEntry 长出 {bad} 字段 ⇒ 「列不列出来」这个维度出现了，"
            "先回答它与 disabled（拒绝维度）谁说了算，再重开 F95 SKIP ②"
        )


