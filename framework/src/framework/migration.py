"""可转换性分类 + 回滚手段（卡 186 · G5）。

> 依据 [arXiv:2606.24598]：**可逆迁移路径 + 可转换性分类** —— 把冻结的专家工作流
> 拆成**可组合、可审计**的阶段，每一样要搬的东西标「**可逆 / 一次性 / 不可逆**」
> + **回滚手段**，零业务逻辑改动。

本模块把 G5 落成**代码 + 产物字段 + 钉子**：

- 每条迁移项必须有 `convertibility`（可逆 / 一次性 / 不可逆）+ `rollback`（回滚手段）；
- `validate_checklist()` 逐行检查：缺分类 ⇒ 红；可逆 / 一次性缺回滚手段 ⇒ 红；
  不可逆必须**显式**写「无」（空着 = 没想过 = 红）；
- `FRAMEWORK_MIGRATION`：**框架自己**从本仓抽离成独立仓的迁移清单（白名单内的实例）。

本模块是**纯库**：不 print、不 `sys.exit`、不写死本仓路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Convertibility(str, Enum):
    """可转换性分类（照 [arXiv:2606.24598] 的 taxonomy）。"""

    REVERSIBLE = "reversible"
    """可逆：搬过去能搬回来（如复制体、可 git revert 的改动）。"""

    ONE_SHOT = "one_shot"
    """一次性：做完不能逐字撤销，但有明确的「再做一遍」手段（如重跑生成）。"""

    IRREVERSIBLE = "irreversible"
    """不可逆：做完回不去了（如删原件、改台账路径）。必须显式写「无」回滚。"""


@dataclass(frozen=True)
class MigrationItem:
    """迁移清单的一行：要搬什么 + 可转换性 + 回滚手段。"""

    name: str
    convertibility: Convertibility
    rollback: str   # 回滚手段；不可逆的必须显式写「无」
    notes: str = ""


@dataclass(frozen=True)
class MigrationViolation:
    """G5 一条违规（产物字段）。"""

    item: str
    detail: str

    def to_dict(self) -> dict:
        return {"item": self.item, "detail": self.detail}


# ---------------------------------------------------------------------------
# G5 · 逐行校验
# ---------------------------------------------------------------------------

_NONE_TOKENS = frozenset({"无", "none", "None", "不可逆，无回滚"})


def validate_checklist(items: list[MigrationItem]) -> list[MigrationViolation]:
    """G5 每行都要标可转换性 + 回滚手段，否则红。

    判据：
      - 可逆 / 一次性：`rollback` 必须非空（说清怎么撤）；
      - 不可逆：`rollback` 必须显式写「无」（空着 = 没想过 = 红）；
      - `name` 必须非空（没名字的迁移项没法审计）。
    """
    out: list[MigrationViolation] = []
    for item in items:
        if not item.name.strip():
            out.append(MigrationViolation(item="(无名)", detail="迁移项没名字 —— 没法审计"))
            continue
        if item.convertibility in (Convertibility.REVERSIBLE, Convertibility.ONE_SHOT):
            if not item.rollback.strip():
                out.append(MigrationViolation(
                    item=item.name,
                    detail=f"「{item.convertibility.value}」项缺回滚手段 —— "
                           "可逆/一次性必须说清怎么撤（依据 [2606.24598]）",
                ))
        elif item.convertibility == Convertibility.IRREVERSIBLE:
            if not item.rollback.strip():
                out.append(MigrationViolation(
                    item=item.name,
                    detail="「不可逆」项的回滚手段空着 —— 必须显式写「无」"
                           "（空着 = 没想过 = 红）",
                ))
            elif item.rollback.strip() not in _NONE_TOKENS:
                out.append(MigrationViolation(
                    item=item.name,
                    detail=f"「不可逆」项的回滚手段写了「{item.rollback}」—— "
                           "不可逆就该显式写「无」，写了别的说明分类标错",
                ))
    return out


def checklist_to_dict(items: list[MigrationItem]) -> dict:
    """产物字段：整张清单 + 校验结果。"""
    violations = validate_checklist(items)
    return {
        "items": [
            {"name": it.name, "convertibility": it.convertibility.value,
             "rollback": it.rollback, "notes": it.notes}
            for it in items
        ],
        "violations": [v.to_dict() for v in violations],
        "ok": not violations,
    }


# ---------------------------------------------------------------------------
# 框架自己的迁移清单（从本仓抽离成独立仓 —— 白名单内的实例）
# ---------------------------------------------------------------------------

FRAMEWORK_MIGRATION: tuple[MigrationItem, ...] = (
    MigrationItem(
        name="framework/ 目录搬到独立仓",
        convertibility=Convertibility.REVERSIBLE,
        rollback="git revert 搬回那一笔；目录是新增的，删掉即回原状",
        notes="整目录是新增物，不依赖本仓既有路径",
    ),
    MigrationItem(
        name="pipeline.toml 的 JSON Schema 抽离",
        convertibility=Convertibility.REVERSIBLE,
        rollback="schema 是新文件，删掉回退到无 schema 校验",
        notes="additionalProperties=false 的严格校验是新增能力",
    ),
    MigrationItem(
        name="三值判决 gates.classify 抽成纯库函数",
        convertibility=Convertibility.REVERSIBLE,
        rollback="纯函数无副作用，搬回原位即等价（G9 钉子证等价）",
        notes="classify 的拒绝点活性由 G7 扫描覆盖",
    ),
    MigrationItem(
        name="把检查面（域比对/门数/trailer 真伪/分支/脏树）抽空进库",
        convertibility=Convertibility.ONE_SHOT,
        rollback="删库里的 review.py，调用方回到各写一份；原件仍在项目侧不动",
        notes="抽空进配置（照缝层手法）：路径由调用方传，库里不写死",
    ),
    MigrationItem(
        name="删掉框架对本仓运行时的隐式依赖（sys.path 挂载）",
        convertibility=Convertibility.IRREVERSIBLE,
        rollback="无",
        notes="一旦独立，本仓不再能 import 框架内部；要回退只能重新 vendoring",
    ),
    MigrationItem(
        name="框架自带测试 + 自带门禁（pipe gate / pipe doctor）",
        convertibility=Convertibility.REVERSIBLE,
        rollback="测试是新文件，删掉回退",
        notes="P5：在框架里跑 pipe gate 全绿、pipe doctor 每门有牙",
    ),
)


def framework_migration_report() -> dict:
    """框架自己的迁移清单报告（G5 产物）。"""
    return checklist_to_dict(list(FRAMEWORK_MIGRATION))
