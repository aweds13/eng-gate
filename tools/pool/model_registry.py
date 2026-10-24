r"""模型注册表 —— 一层统一，按池分流（卡 166 · T-G266）。

## 为什么有它（用户 2026-10-03 裁定）

用户问「为什么白名单会变成……就是那两个部分会有不同的、不能用的 id 体系是吗？
你可以把它做成一个同一层，然后分流到不同层吗？」

**现场（卡 146 踩坏的地方）**：卡 146 把 ``wb_dispatch.py`` 的硬编码白名单删掉、
改读 ``infra/pool/models.whitelist.toml``。而那份"唯一权威"**只描述华为码道池**
（``huaweicloud-maas/GLM-5.2``，provider/model 形式）；派活器在用的是 **CodeBuddy 池**，
id 是**裸名**（``deepseek-v4.1-flash`` / ``glm-5.3-flash``）⇒ 合并后裸名全被拒、
``--model`` 默认值取到"首项" = 一个 CodeBuddy CLI 不认的名字 ⇒ 不带 ``--model`` 的派活全挂。

**两个池连 id 体系都不同**，所以"挑一份当真源"这条路本身是错的。

## 本模块做什么

一层注册表（唯一可写"跨池统一层"）= ``tools/pool/model-registry.toml``：

  · CodeBuddy 池的真源 = 注册表里的 ``[[model]]`` 条目（``pool = "codebuddy"``）
  · 码道池的真源 = ``infra/pool/models.whitelist.toml``（注册表 ``[pool.codearts]`` 引用它、不复制）

每条记录声明 ``alias / pool / id / default / note``：
  - ``alias``  逻辑名（工人/主控用的名字，``--model`` 给它）
  - ``pool``   池名（``codebuddy`` / ``codearts``）
  - ``id``     该池内的真实 id（codebuddy 用裸名；codearts 用 provider/model 形式）
  - ``default`` 是否该池默认（每池至多一条 ``default = true``）
  - ``note``   备注

派活时拿逻辑名 → ``resolve_model(alias, pool)`` 查出 ``(pool, per-pool id)`` →
交给**该池的适配器**（``get_adapter(pool)``）。

## 边界（如实写）

- 本卡**不实现**码道池的真实调用（只留适配器接口 + 拒绝路径）—— 真要接，另立卡。
- 本卡**不动** ``infra/pool/models.whitelist.toml`` 的既有条目语义（它仍描述码道池那一侧）；
  注册表引用它（``[pool.codearts].source``），加载时读它派生码道条目。
- 迁移期间 CodeBuddy 池**行为不变**是硬要求（判据 ⑥）⇒ 注册表 codebuddy 段与旧
  ``MODEL_WHITELIST`` 逐字相同；``models.whitelist.toml`` 找不到/坏掉**不阻止** codebuddy 派活。
"""

from __future__ import annotations

try:
    import pipe_root
except ImportError:
    try:
        from tools import pipe_root
    except ImportError:  # pragma: no cover —— 落地桩/独立拷贝的树里没有 pipe_root
        pipe_root = None  # type: ignore[assignment]

import os
import pathlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

from pool.models import find_pool_dir, load_switches

#: 本模块所在的仓库根（``tools/pool/`` 上两级）。
_FILE_ROOT = pathlib.Path(__file__).resolve().parents[2]
ROOT = pipe_root.data_root() if pipe_root is not None else _FILE_ROOT
#: 注册表文件名（与本模块同目录）。
REGISTRY_FILE = "model-registry.toml"
#: 覆盖注册表路径的环境变量（★ 只给测试与离线用）。
REGISTRY_ENV = "TF_MODEL_REGISTRY"
#: 覆盖码道引用源路径的环境变量（复用 ``TF_MODEL_WHITELIST``，与 ``pool.models`` 同口径）。
CODEARTS_SOURCE_ENV = "TF_MODEL_WHITELIST"

#: 已知的池（★ 未知池 ⇒ ``UnknownPoolError``，不静默降级）。
KNOWN_POOLS: tuple[str, ...] = ("codebuddy", "codearts")
#: 默认池（今天在用的；``--pool`` 缺省取它）。
DEFAULT_POOL = "codebuddy"


# ---------------------------------------------------------------- 异常
class ModelRegistryError(RuntimeError):
    """注册表**找不到或坏掉** —— 带路径（解析失败再带行号）。

    ★ 为什么单独一个异常类、且**绝不退回内置名单**：悄悄退回一份内置名单 = 又造了第二份
    真源（正是本卡要消灭的东西）。缺真源 ⇒ **拒绝派活**并说清去哪儿找/怎么指。
    """


class PoolMismatchError(RuntimeError):
    """**跨池串用** —— 给的模型名属于别的池（id 体系不同，不许串用）。

    ★ 为什么单列一类：跨池串用不是"未知模型"，是"模型在、但不在你说的那个池里"，
    拒单理由要**点清**它属于哪个池、当前池是什么（判据 ③）。
    """

    def __init__(self, alias: str, asked_pool: str, belongs_to: str) -> None:
        super().__init__(
            f"跨池串用被拒：模型「{alias}」属于「{belongs_to}」池，不在当前「{asked_pool}」池。"
            "两个池的 id 体系不同（codebuddy 用裸名、codearts 用 provider/model 形式），"
            "不许串用。请用 ``--pool {belongs_to}`` 切到那个池，或换一个"
            f"「{asked_pool}」池的模型。")


class UnknownPoolError(RuntimeError):
    """**未知池** —— 注册表/适配器里没有这个池。

    ★ 不静默降级到别的池（判据 ④）：派活前响亮拒绝并点名已接的池。
    """

    def __init__(self, pool: str) -> None:
        super().__init__(
            f"未知池：{pool}（已接的池：{', '.join(KNOWN_POOLS)}）。"
            f"请用 ``--pool <{'|'.join(KNOWN_POOLS)}>`` 指定。")


class PoolNotWiredError(RuntimeError):
    """该池的**调用还没接**（卡 166：只留接口 + 拒绝路径）。

    ★ 不许静默回落到别的池，也不许拿裸名去试（判据 ④ / 边界）。
    """


# ---------------------------------------------------------------- 注册表条目
@dataclass(frozen=True)
class ModelEntry:
    """一条注册表记录：``alias / pool / id / default / note``。"""
    alias: str
    pool: str
    id: str
    default: bool
    note: str = ""


def registry_path() -> Path:
    """注册表路径：``TF_MODEL_REGISTRY`` 覆盖 > 本模块同目录的 ``model-registry.toml``。"""
    override = os.environ.get(REGISTRY_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / REGISTRY_FILE


def _codearts_source_path() -> Path | None:
    """码道引用源路径：``TF_MODEL_WHITELIST`` 覆盖 > 号池目录下的 ``source`` 文件名。"""
    override = os.environ.get(CODEARTS_SOURCE_ENV)
    if override:
        return Path(override)
    return None


def _parse_model_entries(path: Path, data: dict[str, Any]) -> list[ModelEntry]:
    """解析注册表里的 ``[[model]]`` 条目（内联条目，非引用）。"""
    raw = data.get("model")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ModelRegistryError(
            f"注册表坏：{path} 的 ``[[model]]`` 必须是数组，实际是 {type(raw).__name__}")
    out: list[ModelEntry] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ModelRegistryError(
                f"注册表坏：{path} 第 {index} 条 [[model]] 必须是表，实际是 {type(entry).__name__}")
        for key in ("alias", "pool", "id"):
            if key not in entry:
                raise ModelRegistryError(
                    f"注册表坏：{path} 第 {index} 条 [[model]] 缺「{key}」键")
        alias = entry["alias"]
        pool = entry["pool"]
        ident = entry["id"]
        for label, value in (("alias", alias), ("pool", pool), ("id", ident)):
            if not isinstance(value, str) or not value.strip() or re.search(r"\s", value):
                raise ModelRegistryError(
                    f"注册表坏：{path} 第 {index} 条 [[model]] 的「{label}」必须是非空、"
                    f"不含空白的字符串，实际是 {type(value).__name__}（{value!r}）")
        if pool not in KNOWN_POOLS:
            raise ModelRegistryError(
                f"注册表坏：{path} 第 {index} 条 [[model]] 的「pool」必须是 "
                f"{KNOWN_POOLS} 之一，实际是 {pool!r}")
        out.append(ModelEntry(
            alias=alias, pool=pool, id=ident,
            default=bool(entry.get("default", False)),
            note=str(entry.get("note", "")),
        ))
    return out


def _parse_codearts_reference(
        path: Path, data: dict[str, Any],
) -> tuple[str, str | None, list[ModelEntry]]:
    """解析 ``[pool.codearts]`` 引用段 → ``(source_name, declared_default, entries)``。

    ★ 宽容：引用的源文件找不到/坏掉 ⇒ 返回空条目（**不阻止 codebuddy 派活**，判据 ⑥）。
      ``resolve_model(alias, "codearts")`` / ``default_model_for("codearts")`` 在空时再报错。
    """
    ref = data.get("pool", {}).get("codearts") if isinstance(data.get("pool"), dict) else None
    if ref is None:
        return "", None, []
    if not isinstance(ref, dict):
        raise ModelRegistryError(
            f"注册表坏：{path} 的 ``[pool.codearts]`` 必须是表，实际是 {type(ref).__name__}")
    source_name = str(ref.get("source", ""))
    declared_default = ref.get("default")
    if declared_default is not None and not isinstance(declared_default, str):
        raise ModelRegistryError(
            f"注册表坏：{path} 的 ``[pool.codearts].default`` 必须是字符串，"
            f"实际是 {type(declared_default).__name__}")
    if not source_name:
        return "", declared_default, []
    src_path = _codearts_source_path()
    if src_path is None:
        pool_dir = find_pool_dir(ROOT)
        if pool_dir is None:
            return source_name, declared_default, []
        src_path = pool_dir / source_name
    if not src_path.exists():
        return source_name, declared_default, []
    try:
        text = src_path.read_text(encoding="utf-8")
        src_data = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError):
        return source_name, declared_default, []
    approved = src_data.get("approved")
    if not isinstance(approved, list):
        return source_name, declared_default, []
    entries: list[ModelEntry] = []
    for entry in approved:
        if not isinstance(entry, dict) or "model" not in entry:
            continue
        model = entry["model"]
        if not isinstance(model, str) or not model.strip():
            continue
        entries.append(ModelEntry(
            alias=model, pool="codearts", id=model,
            default=(model == declared_default),
            note=str(entry.get("note", "")),
        ))
    return source_name, declared_default, entries


def load_registry() -> list[ModelEntry]:
    """读注册表 → 所有条目（**只读**、不写）。

    - 注册表找不到/坏掉 ⇒ ``ModelRegistryError``（拒绝派活；**不退回内置名单**）；
    - 码道引用源找不到/坏掉 ⇒ 码道条目为空（**不阻止 codebuddy 派活**，判据 ⑥）；
    - 每池至多一条 ``default = true``（多了 ⇒ ``ModelRegistryError``）。
    """
    path = registry_path()
    if not path.exists():
        raise ModelRegistryError(
            f"模型注册表不存在：{path} —— 真源只有这一份（只有用户能改），找不到就拒绝"
            f"派活，不退回内置名单；测试/离线可用 {REGISTRY_ENV} 指到一份 toml。")
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        line = getattr(exc, "lineno", None)
        where = f"{path}（第 {line} 行）" if line else str(path)
        raise ModelRegistryError(f"模型注册表解析失败：{where} —— {exc}") from exc
    entries = _parse_model_entries(path, data)
    _source_name, _decl_default, codearts_entries = _parse_codearts_reference(path, data)
    entries.extend(codearts_entries)
    if not entries:
        raise ModelRegistryError(
            f"注册表坏：{path} 没有任何 [[model]] 条目，也没有可用的 [pool.*] 引用"
            "（空名单不许静默当空 —— 那是又一种「看着绿其实没查」）")
    _check_one_default_per_pool(path, entries)
    return entries


def _check_one_default_per_pool(path: Path, entries: list[ModelEntry]) -> None:
    """每池至多一条 ``default = true``（多了 ⇒ 报错 —— 默认必须确定）。"""
    by_pool: dict[str, list[str]] = {}
    for entry in entries:
        if entry.default:
            by_pool.setdefault(entry.pool, []).append(entry.alias)
    for pool, defaults in by_pool.items():
        if len(defaults) > 1:
            raise ModelRegistryError(
                f"注册表坏：{path} 的「{pool}」池有多条 default = true："
                f"{', '.join(defaults)}（每池至多一条默认）")


# ---------------------------------------------------------------- 按池查询
def entries_for(pool: str, entries: list[ModelEntry] | None = None) -> list[ModelEntry]:
    """该池的条目（按注册表顺序 = 轮换序）。"""
    if entries is None:
        entries = load_registry()
    return [e for e in entries if e.pool == pool]


def resolve_model(
        alias: str, pool: str, entries: list[ModelEntry] | None = None,
) -> ModelEntry | None:
    """查 ``(alias, pool)`` → ``ModelEntry``；不在注册表 → ``None``（可能被开关/ONE_OFF 放行）。

    - alias 不在注册表 ⇒ ``None``（不抛错 —— 可能被外部开关/一次性授权放行；
      是否真的允许由 ``model_rejected`` 判）；
    - alias 存在但属于别的池 ⇒ ``PoolMismatchError``（跨池串用，判据 ③）；
    - alias 存在且属于该池 ⇒ 返回条目。
    """
    if entries is None:
        entries = load_registry()
    matches = [e for e in entries if e.alias == alias]
    if not matches:
        return None
    in_pool = [e for e in matches if e.pool == pool]
    if not in_pool:
        belongs_to = matches[0].pool
        raise PoolMismatchError(alias, pool, belongs_to)
    return in_pool[0]


def default_model_for(pool: str, entries: list[ModelEntry] | None = None) -> ModelEntry:
    """该池的默认项（``default = true`` 的那条）。

    ★ **绝对不许"取注册表首项"** —— 那正是卡 146 踩的雷（跨池串了默认值，判据 ②）。
    - 没有默认 ⇒ ``ModelRegistryError``（该池条目空 / 没人标 default）。
    """
    if entries is None:
        entries = load_registry()
    pool_entries = entries_for(pool, entries)
    if not pool_entries:
        raise ModelRegistryError(
            f"「{pool}」池在注册表里没有条目（引用的源可能找不到/坏掉）。"
            "CodeBuddy 池不受影响；码道池真要接请检查 infra/pool/models.whitelist.toml。")
    defaults = [e for e in pool_entries if e.default]
    if not defaults:
        raise ModelRegistryError(
            f"「{pool}」池没有声明 default = true 的条目（默认必须确定，不许取首项冒充）。"
            f"该池条目：{', '.join(e.alias for e in pool_entries)}")
    return defaults[0]


def rotation_chain_for(pool: str, entries: list[ModelEntry] | None = None) -> tuple[str, ...]:
    """该池的轮换链（按注册表顺序的 alias）。

    ★ 只对 codebuddy 池有意义（码道池不参与 429 轮换）。
    """
    if entries is None:
        entries = load_registry()
    return tuple(e.alias for e in entries_for(pool, entries))


def effective_allowed_for(pool: str, entries: list[ModelEntry] | None = None) -> tuple[str, ...]:
    """该池的允许集 = 注册表条目 ∪ 开关文件里该池打开的。

    ★ 开关文件按池读（``[switch.<pool>]`` 段；向后兼容 ``[switch]`` 段当成 codebuddy）。
    ★ 开关只做**加法**（注册表是下限）、**不进 429 轮换链**。
    """
    if entries is None:
        entries = load_registry()
    out = [e.alias for e in entries_for(pool, entries)]
    switches = load_switches(pool=pool)
    for name, on in switches.items():
        if on and name not in out:
            out.append(name)
    return tuple(out)


# ---------------------------------------------------------------- 适配器（按池分流）
@dataclass(frozen=True)
class PoolAdapter:
    """派活适配器（按池分流，卡 166 追加要求 1）。

    ★ 判据：**换池不许改变工人看到的东西**（除了 provider/model 名字）。
    """
    pool: str
    wired: bool
    note: str

    def assert_wired(self) -> None:
        """未接 ⇒ ``PoolNotWiredError``（响亮拒绝，不静默回落到别的池）。"""
        if not self.wired:
            raise PoolNotWiredError(self.note)


_ADAPTERS: dict[str, PoolAdapter] = {
    "codebuddy": PoolAdapter("codebuddy", True, "CodeBuddy CLI（今天在用的）"),
    "codearts": PoolAdapter("codearts", False,
                            "codearts 池的调用还没接（卡 166：只留接口 + 拒绝路径）"),
}


def get_adapter(pool: str) -> PoolAdapter:
    """取该池的适配器；未知池 ⇒ ``UnknownPoolError``（判据 ④）。"""
    if pool not in _ADAPTERS:
        raise UnknownPoolError(pool)
    return _ADAPTERS[pool]


# ---------------------------------------------------------------- 最小规矩集（追加要求 2）
#: 最小规矩集的键（顺序固定，机器判据按这个查）。
MINIMUM_RULESET_KEYS: tuple[str, ...] = (
    "no_window", "no_commit", "no_full_gates", "forbidden", "pit_page",
)

_MINIMUM_RULESET: dict[str, str] = {
    "no_window":
        "NO_WINDOW 铁律：起子进程（subprocess.Popen/run/call）必须带 "
        "NO_WINDOW/creationflags/windowsHide，否则 tests/test_no_window.py 判红（卡 148）。",
    "no_commit":
        "不许 commit（除非卡规格明确要求；commit 信息末尾四行 trailer 一行不许少）。",
    "no_full_gates":
        "不许跑全量门禁（除非卡规格明确要求；跑子集即可）。",
    "forbidden":
        "禁区：真实数据库、备份目录、别人的未跟踪文件一个字都不许碰。",
    "pit_page":
        "固定坑页入口：复盘/口径坑.md（主控与工人都先读这一页；每条都是真踩过的）。",
}


def minimum_ruleset() -> dict[str, str]:
    """最小规矩集（卡 166 追加要求 2）—— 派活时**必须**喂给工人的规矩。

    ★ 码道那侧也要喂（正是卡 182 咬的那条：码道派活器只喂卡规格原文 ⇒ 工人不知道 NO_WINDOW）。
    ★ 形态：文本（拼进提示）；机器判据 ``test_minimum_ruleset_text_contains_all_keys``。
    """
    return dict(_MINIMUM_RULESET)


def minimum_ruleset_text() -> str:
    """拼成一段文本（拼进工人提示）。"""
    items = minimum_ruleset()
    lines = ["★ 最小规矩集（卡 166；换池不许改变工人看到的东西）："]
    for key in MINIMUM_RULESET_KEYS:
        lines.append(f"  · {items[key]}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 统一日志读数（追加要求 3）
def dispatch_log_dirs(root: Path) -> dict[str, Path]:
    """两边日志目录（卡 166 追加要求 3：同一套读数看见两边）。

    - codebuddy 池日志落 ``<root>/gates/diag/``（``wb-<卡>.jsonl``）；
    - codearts 池日志落 ``<号池目录>/logs/``（``card-<卡>.jsonl``，仓外）。
    """
    pool_dir = find_pool_dir(root)
    fallback = root / "infra" / "pool" / "logs"
    codearts_logs = (pool_dir / "logs") if pool_dir is not None else fallback
    return {"codebuddy": root / "gates" / "diag", "codearts": codearts_logs}


def list_dispatch_logs(root: Path, card: str | None = None) -> list[Path]:
    """扫两边日志目录 → 所有派活日志（同一套读数看见两边）。

    ★ 不论池子，都能被这一套读数看见（否则「跑没跑完」又变成靠人看文件）。
    """
    out: list[Path] = []
    for pool_name, dir_path in dispatch_log_dirs(root).items():
        if not dir_path.exists():
            continue
        if pool_name == "codebuddy":
            pattern = (f"wb-{card}.jsonl" if card else "wb-*.jsonl")
        else:
            pattern = (f"card-{card}.jsonl" if card else "card-*.jsonl")
        out.extend(sorted(dir_path.glob(pattern)))
    return out


__all__ = [
    "ModelEntry", "ModelRegistryError", "PoolMismatchError", "UnknownPoolError",
    "PoolNotWiredError", "PoolAdapter",
    "ROOT", "REGISTRY_FILE", "REGISTRY_ENV", "KNOWN_POOLS", "DEFAULT_POOL",
    "MINIMUM_RULESET_KEYS",
    "registry_path", "load_registry", "entries_for", "resolve_model",
    "default_model_for", "rotation_chain_for", "effective_allowed_for",
    "get_adapter", "minimum_ruleset", "minimum_ruleset_text",
    "dispatch_log_dirs", "list_dispatch_logs",
]
