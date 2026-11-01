#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""pika 新旧版迁移器（默认 dry-run）。

用法
----
    python -X utf8 tools/pika_migrate.py                      # 默认 dry-run，只打印
    python -X utf8 tools/pika_migrate.py --only skills        # 只看 skills 一类
    python -X utf8 tools/pika_migrate.py --explain-arbitration  # 列出待人裁决项
    python -X utf8 tools/pika_migrate.py --execute --i-understand-delete --only skills

为什么这个脚本长这样
--------------------
卡 B3 的硬判据（原文）：

    迁移脚本必须默认 dry-run，**真跑需要人再确认一次**；脚本要能对**每一个删除动作**
    打印将要删的绝对路径与原因，且**删除前必须已验证新版存在且内容正确**（顺序不能反）。

所以本文件被切成四段，段与段之间只有「清单」这一种接口：

    ① verify   —— 只读。逐条打开「新版」取字节、算 sha256；再算「旧版」的 sha256。
                  两边都对得上才允许这一条进入**删除清单**。验证失败的一条都不进。
    ② 备份      —— 把①清单里每个旧文件复制到 _backup_<时间戳>/ 并逐一比对
                  （文件数 + 字节数 + 每个文件的 sha256）。任何一项对不上就**中止整批**。
    ③ delete   —— 只消费①产出的清单，不再自己推导该删谁。删每个文件之前再算一次
                  旧版 sha256 兜底（防中途有人动过）；对不上就中止整批，不做「跳过继续」。
    ④ place    —— 把新版内容写到目标位（这一阶段不删任何东西）。

顺序为什么不能反：如果先删再验，一旦新版缺一条，旧的那条已经没了 —— 数据不可恢复。
所以 ① 必须先把**全部**条目的新版侧读通、算完 sha，才轮到 ②③。①失败 ⇒ 整批不进入 ②。

风险边界（本脚本刻意不做的事）
------------------------------
* 只读打开 `D:/downloads\pika文件_Pro.zip`（`zipfile.ZipFile(..., 'r')`），全程不写不改。
* 不删除「磁盘上有、新版里没有」的文件（那 48+1+1 条是用户自己的东西 / 旧包本体），
  它们只进 `--explain-arbitration` 的裁决清单，要删得人另跑一次并明确点名。
* 不重建索引、不改 Obsidian 配置、不改注册表与环境变量 —— 那些是回填方案里
  「需要人确认」的项，得人点头后单独做。

分类（`--only` 用这套名字）
--------------------------
    library  `Library/开源资源` + `Library/pika的presentations`
    tool     `Tool/代码与数据`
    aitools  `知识库/pika文件_Pro/AI工具`
    vault    `知识库/pika文件_Pro/笔记共享vault`
    skills   `C:/Users/example\.dsh\skills\<skill>`（7 个 payload）
    gridlab  `Tool/代码与数据/grid-covering-lab-source`

依赖的只读清单（`_tools/pika-迁移/inventory/`，上一轮勘察产出）
--------------------------------------------------------------
    b3_fullhash.json     3771 条：新版侧 sha256(new_sha) + 旧版侧 sha256(old_sha) + verdict
    old_candidates.json  4074 条：match(是否配对) + old_path + origin + zip_path
    root_map.json        5 对根的映射（zip 子树根 ↔ D 盘旧根）

本脚本**不信任**这两个 json 里的 sha 值，它会自己重算 —— json 只用来「知道有哪些条目」。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# 一、常量：本机的真实位置（全部来自 2026-10-31 的实测，不是猜的）
# --------------------------------------------------------------------------

ROOT = Path(r"D:/repo")                      # 知识根（mpk config 的 knowledge_root）
MIG_DIR = ROOT / "_tools" / "pika-迁移"                 # 迁移工作目录
INVENTORY = MIG_DIR / "inventory"                       # 上一轮勘察产出的只读清单
EXTRACTED = MIG_DIR / "_extracted"                      # 已解出的新版（仅 toolkit/gridlab 可信）
OUTER_ZIP = Path(r"D:/downloads/pika文件_Pro.zip")           # 外层包（1.4 GB，只读）
VAULT_ZIP = EXTRACTED / "笔记共享vault" / "__source.zip"  # 与外包内 member 逐字节相同（已实测）

SKILLS_ROOT = Path.home() / ".dsh" / "skills"           # pika 6 个 skill 的实装位置
VAULT_TARGET = ROOT / "知识库" / "pika文件_Pro" / "笔记共享vault"
GRIDLAB_TARGET = ROOT / "Tool" / "代码与数据" / "grid-covering-lab-source"

# 外层 zip 里的嵌套包（名字已实测）
MEMBER_VAULT = "pika文件_Pro/笔记共享vault.zip"
MEMBER_TOOLKIT = "pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip"
MEMBER_GRIDLAB = "pika文件_Pro/pika资料共享/代码与数据/grid-covering-lab-source.zip"

VAULT_INNER_PREFIX = "笔记共享vault/笔记共享vault/"      # vault 包里的双层套娃前缀

CATEGORIES = ("library", "tool", "aitools", "vault", "skills", "gridlab")

# 六个 --only 分类 ↔ (origin, zip_path 前缀) 的对应。写死成表是为了让 `--only library`
# 这种模糊名字有唯一解释，而不是让脚本去猜。
CATEGORY_RULES = {
    "library": ("outer", ("pika资料共享/开源资源/", "pika资料共享/pika的presentations/")),
    "tool": ("outer", ("pika资料共享/代码与数据/",)),
    "aitools": ("outer", ("pika资料共享/AI工具/",)),
    "vault": ("vault", ("__vault__/",)),
    "skills": ("toolkit", ("__toolkit__/",)),
    "gridlab": ("gridlab", ("__gridlab__/",)),
}

# 哪些目录名在 Windows 上是设备名（`C:/Users/example\.dsh\skills\nul` 这个 0 字节垃圾文件踩过）
DEVICE_NAMES = {"nul", "con", "prn", "aux"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


# --------------------------------------------------------------------------
# 二、小工具
# --------------------------------------------------------------------------

def utf8_stdout() -> None:
    """Windows 控制台默认 GBK，中文路径和 ✅/❌ 会炸；这里强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(name: str):
    with open(INVENTORY / name, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# 三、读「新版」内容的四个来源
#
# 新版内容不在一个地方：外层包 + 两个嵌套包。这里把它们统一成
#   read_new(origin, zip_path) -> (bytes, locator)
# locator 是给人看的「新版路径」，会原样打进删除理由里。
# --------------------------------------------------------------------------

class NewSource:
    """新版内容的只读句柄集合。全部 `'r'` 打开，任何路径都不写。"""

    def __init__(self) -> None:
        self._outer = zipfile.ZipFile(OUTER_ZIP, "r")
        self._vault = zipfile.ZipFile(VAULT_ZIP, "r") if VAULT_ZIP.is_file() else None
        self._nested: dict[str, zipfile.ZipFile] = {}

    # -- 内部：把外层的嵌套包读进内存再当 zip 用（toolkit 2 MB / gridlab 62 KB，很轻）
    def _nested_zip(self, member: str) -> zipfile.ZipFile:
        if member not in self._nested:
            self._nested[member] = zipfile.ZipFile(io.BytesIO(self._outer.read(member)), "r")
        return self._nested[member]

    def close(self) -> None:
        for zf in self._nested.values():
            zf.close()
        if self._vault is not None:
            self._vault.close()
        self._outer.close()

    # -- 对外唯一的读入口
    def read_new(self, origin: str, zip_path: str) -> tuple[bytes, str]:
        if origin == "outer":
            member = "pika文件_Pro/" + zip_path
            return self._outer.read(member), f"{OUTER_ZIP.as_posix()}!{member}"

        if origin == "vault":
            rel = zip_path[len("__vault__/"):]
            member = VAULT_INNER_PREFIX + rel
            if self._vault is not None:
                return self._vault.read(member), f"{VAULT_ZIP.as_posix()}!{member}"
            # 兜底：__source.zip 不在就直接从外层包里的 member 读（223 MB 会吃内存，仅兜底）
            return (
                self._nested_zip(MEMBER_VAULT).read(member),
                f"{OUTER_ZIP.as_posix()}!{MEMBER_VAULT}!{member}",
            )

        if origin == "toolkit":
            member = zip_path[len("__toolkit__/"):]
            zf = self._nested_zip(MEMBER_TOOLKIT)
            return zf.read(member), f"{OUTER_ZIP.as_posix()}!{MEMBER_TOOLKIT}!{member}"

        if origin == "gridlab":
            member = zip_path[len("__gridlab__/"):]
            zf = self._nested_zip(MEMBER_GRIDLAB)
            return zf.read(member), f"{OUTER_ZIP.as_posix()}!{MEMBER_GRIDLAB}!{member}"

        raise KeyError(f"未知 origin: {origin}")

    def is_file(self, origin: str, zip_path: str) -> bool:
        """只判存在、不取字节 —— 用于 place 阶段前的一次廉价确认。"""
        try:
            self.read_new(origin, zip_path)
            return True
        except (KeyError, zipfile.BadZipFile, FileNotFoundError):
            return False


# --------------------------------------------------------------------------
# 四、路径映射：zip 里的条目 → 磁盘上的绝对路径
#
# 五对根来自 root_map.json（上一轮实测），两条特殊映射写死：
#   __gridlab__ → Tool/代码与数据/grid-covering-lab-source
#   __toolkit__/payload/<skill> → C:/Users/example\.dsh\skills\<skill>
# --------------------------------------------------------------------------

def build_root_map() -> list[tuple[str, str]]:
    """返回 [(zip_root, old_root)]，按 root_map.json 的顺序。"""
    rows = load_json("root_map.json")
    return [(r["zip_root"], r["old_root"]) for r in rows if r["zip_root"].startswith("pika资料共享/")]


ROOT_MAP = build_root_map()


def target_path(origin: str, zip_path: str) -> Path:
    """新版内容该落到哪里（make_dirs 在这里不做，place 阶段才做）。"""
    if origin == "outer":
        for zip_root, old_root in ROOT_MAP:
            if zip_path.startswith(zip_root + "/"):
                return ROOT / old_root / zip_path[len(zip_root) + 1:]
        raise KeyError(f"外层条目没有映射根: {zip_path}")

    if origin == "vault":
        return VAULT_TARGET / zip_path[len("__vault__/"):]

    if origin == "toolkit":
        rel = zip_path[len("__toolkit__/payload/"):]
        return SKILLS_ROOT / rel

    if origin == "gridlab":
        return GRIDLAB_TARGET / zip_path[len("__gridlab__/"):]

    raise KeyError(f"未知 origin: {origin}")


def old_path_of(row: dict) -> Path | None:
    """旧版绝对路径。old_candidates 里 origin=toolkit 的已经是绝对路径，其余是 D 盘相对路径。"""
    raw = row.get("old_path")
    if not raw:
        return None
    if raw[:3].upper() == "C:/":
        return Path(raw)
    return ROOT / raw


def category_of(row: dict) -> str | None:
    origin = row["origin"]
    for name, (want_origin, prefixes) in CATEGORY_RULES.items():
        if origin != want_origin:
            continue
        if any(row["zip_path"].startswith(p) for p in prefixes):
            return name
    return None


# --------------------------------------------------------------------------
# 五、① verify 阶段：产出删除清单
#
# 清单元素 = DeleteItem，字段就是卡 B3 要的那三元组加上打印所需的元数据：
#     (旧路径, 新版定位符, sha256)
# 规矩：**验证不通过的条目不进清单**，而且要单独计数、单独打印原因。
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DeleteItem:
    old_abs: Path        # 要删的旧文件绝对路径
    new_locator: str     # 新版内容在哪（zip 路径!member，给人看也给人核）
    new_sha: str         # 上面那份新版内容的 sha256
    old_sha: str         # 旧文件删之前的 sha256（备份阶段要复核这个）
    size: int            # 旧文件字节数（打印用）
    category: str
    zip_path: str
    origin: str

    # execute 阶段只认这三样 —— 卡 B3 的清单形状
    def triple(self) -> tuple[str, str, str]:
        return (str(self.old_abs), self.new_locator, self.new_sha)


@dataclass
class VerifyReport:
    manifest: list[DeleteItem] = None
    failed: list[tuple[dict, str]] = None          # (条目, 失败原因)
    skipped_same: int = 0                          # 新旧 sha 相同 ⇒ 不需要删除/重写
    skipped_excluded: int = 0                      # 被 --only 排除
    skipped_no_old: int = 0                        # 新版有、旧版没有（只需 place，不需 delete）
    skipped_no_root: int = 0                       # 没有任何映射根的条目（安装器顶层文件等）
    arbitration: list[dict] = None                 # 需要人裁决的「磁盘独有」项

    def __post_init__(self) -> None:
        self.manifest = self.manifest or []
        self.failed = self.failed or []
        self.arbitration = self.arbitration or []


def build_rows() -> list[dict]:
    """把两份清单按 (origin, zip_path) 合成一张表。

    old_candidates.json 只有「配对关系」（match / old_path / old_size），没有 sha；
    b3_fullhash.json 才有 new_sha / old_sha / verdict。两个文件各 4074 / 3771 条，
    用 (origin, zip_path) 做键正好一一对上（实测 matched 3771 条全部命中）。
    合成后每条都带上 sha，后面 verify 就不必回查第二个文件。
    """
    b3 = {(r["origin"], r["zip_path"]): r for r in load_json("b3_fullhash.json")}
    rows = []
    for row in load_json("old_candidates.json")["rows"]:
        key = (row["origin"], row["zip_path"])
        hashed = b3.get(key)
        merged = dict(row)
        if hashed is not None:
            merged["new_sha"] = hashed["new_sha"]
            merged["old_sha"] = hashed["old_sha"]
            merged["verdict"] = hashed["verdict"]
        rows.append(merged)
    return rows


def verify(only: set[str] | None, mode: str) -> VerifyReport:
    """只读。打开新版算 sha、算旧版 sha，两边都对上才进删除清单。"""
    report = VerifyReport()
    src = NewSource()
    try:
        rows = build_rows()
        for row in rows:
            match = row.get("match")
            cat = category_of(row)

            # 1) 只处理「新版旧版能按相对路径配对」的条目。
            #    old_missing = 新版有旧版没有 ⇒ 不需要删除，place 阶段处理。
            #    no_old_root = 连映射根都没有（安装器顶层 21 个文件 + vault 包本体）⇒ 本次不管。
            if match == "old_missing":
                report.skipped_no_old += 1
                continue
            if match == "no_old_root":
                report.skipped_no_root += 1
                continue
            if match != "matched_relpath":
                report.failed.append((row, f"未知 match 值: {match}"))
                continue

            if only is not None and cat not in only:
                report.skipped_excluded += 1
                continue

            old_abs = old_path_of(row)
            if old_abs is None:
                report.failed.append((row, "配对条目缺少 old_path"))
                continue
            if "new_sha" not in row:
                # 配对上了但 b3_fullhash 里没有它的 sha 记录 ⇒ 没有可信基线，不进清单
                report.failed.append((row, "b3_fullhash.json 里没有这一条的 sha256 记录"))
                continue

            # 2) 先验新版 —— 这一步必须在「考虑删旧」之前完成，顺序不可反。
            try:
                new_bytes, locator = src.read_new(row["origin"], row["zip_path"])
            except KeyError as exc:
                report.failed.append((row, f"新版不存在（{exc}）"))
                continue
            except (zipfile.BadZipFile, OSError) as exc:
                report.failed.append((row, f"新版读取失败：{type(exc).__name__}: {exc}"))
                continue

            new_sha = sha256_bytes(new_bytes)
            if new_sha != row["new_sha"]:
                # 清单里记的和现场算的不一致 ⇒ 说明来源被动过，整条不可信。
                report.failed.append(
                    (row, f"新版内容与勘察记录不符（现场 {new_sha[:12]}… ≠ 记录 {row['new_sha'][:12]}…）")
                )
                continue

            # 3) 再验旧版现场（文件还在不在、内容有没有被改过）
            if not old_abs.is_file():
                report.failed.append((row, f"旧文件不存在: {old_abs}"))
                continue
            try:
                old_sha = sha256_file(old_abs)
            except OSError as exc:
                report.failed.append((row, f"旧文件读取失败：{type(exc).__name__}: {exc}"))
                continue
            if old_sha != row["old_sha"]:
                report.failed.append(
                    (row, f"旧文件已被改动（现场 {old_sha[:12]}… ≠ 记录 {row['old_sha'][:12]}…），拒绝纳入清单")
                )
                continue
            size = old_abs.stat().st_size
            if size != row["old_size"]:
                report.failed.append((row, f"旧文件大小变了（{size} ≠ 记录 {row['old_size']}）"))
                continue

            # 4) 内容本来就一样 ⇒ 不必删也不必重写（除非 --mode mirror 强制重建一遍）
            if new_sha == old_sha and mode != "mirror":
                report.skipped_same += 1
                continue

            report.manifest.append(
                DeleteItem(
                    old_abs=old_abs,
                    new_locator=locator,
                    new_sha=new_sha,
                    old_sha=old_sha,
                    size=size,
                    category=cat or "?",
                    zip_path=row["zip_path"],
                    origin=row["origin"],
                )
            )

        report.arbitration = collect_arbitration(only, src)
    finally:
        src.close()
    return report


# --------------------------------------------------------------------------
# 六、需要人裁决的「磁盘独有」项 —— 只列，绝不删
#
# 这些是「磁盘上有、新版 zip 里没有」的东西。它们不是迁移对象，是用户的资料：
#   * vault 里 1 篇笔记（可能是用户自己写的，也可能是被改名了）
#   * AI工具 里的 2.1.4 旧包本体
#   * 三个 Codex Skills 空壳 / _observer-tools / 知识库/.obsidian 等
# 脚本对它们的唯一动作是**打印**。
# --------------------------------------------------------------------------

ARBITRATION_DIRS = [
    (ROOT / "知识库" / "pika文件_Pro" / "_observer-tools", "vault",
     "只在 D 盘有、新版没有：用户自建的观察器工具（4 文件 27 KB）"),
    (ROOT / "知识库" / "Codex Skills", "vault",
     "3 个 0 字节 SKILL.md 空壳之一：旧安装器留下的定位标记，删了 mpk 的 infer_vault_root 会变"),
    (ROOT / "知识库" / ".obsidian", "vault",
     "用户当前实际在用的 Obsidian 配置（字体 + CSS snippet + 10-30 的 workspace），新版 zip 里那份是旧快照"),
    (ROOT / "知识库" / "pika文件_Pro" / "笔记共享vault" / "笔记共享vault", "vault",
     "空目录残留（双层套娃留下的一层）"),
]

# skills 目录下只该看这 7 个（payload 全量）。`~/.dsh/skills` 里还躺着
# 30 多个**别的**技能（pipe-*、office-*、ppt-generator 等），那是用户的其它资产，
# 不是本次迁移对象 —— 不加这个白名单，裁决清单会被别人的技能淹掉（实测 319 条噪音）。
PIKA_SKILLS = (
    "compute-fleet-manager",
    "manage-personal-knowledge",
    "math-coach",
    "math-research-solve",
    "math-science-computation",
    "obsidian-vault-notes",
    "pdf-problem-search",
)


def collect_arbitration(only: set[str] | None, src: NewSource) -> list[dict]:
    """返回 [{path, category, why, size}]，纯列举。"""
    items: list[dict] = []

    # (a) 各映射根下「磁盘有、新版包里没有」的具体文件（用 old_candidates 的匹配结果反推）
    #
    # 判据是「这个路径是不是本包**任何一个**条目的落点」，所以两类都要收进来：
    #   matched_relpath → 落点是旧路径（old_path_of）
    #   old_missing     → 落点要按 root_map 算（target_path），它旧版没有、新版有
    # 只收 matched_relpath 会把 281 条 old_missing 的落点错判成「磁盘独有」，
    # 一旦 place 写过它们，裁决清单就会凭空多出 281 条噪音。
    rows = load_json("old_candidates.json")["rows"]
    known_targets = set()
    for row in rows:
        try:
            p = old_path_of(row)
            if p is None:
                p = target_path(row.get("origin", ""), row.get("zip_path", ""))
        except KeyError:
            # `outer:zipfile` 这类「包本体」条目没有落点，跳过即可
            continue
        if p is not None:
            known_targets.add(str(p).casefold())

    scan_roots: list[tuple[Path, str]] = [
        (ROOT / "Library" / "开源资源", "library"),
        (ROOT / "Library" / "pika的presentations", "library"),
        (VAULT_TARGET, "vault"),
    ]
    # skills 只扫这 7 个 payload 目录本身 —— 不扫 `~/.dsh/skills` 整个目录，
    # 那里还有用户别的技能（pipe-* / office-* / ppt-generator …），不是迁移对象。
    scan_roots += [(SKILLS_ROOT / name, "skills") for name in PIKA_SKILLS]

    for scan_root, cat in scan_roots:
        if only is not None and cat not in only:
            continue
        if not scan_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(scan_root):
            # 设备名目录（nul 等）必须剪掉，否则 Windows 上 relpath 直接抛 ValueError
            dirnames[:] = [d for d in dirnames if d.split(".")[0].casefold() not in DEVICE_NAMES]
            if Path(dirpath).name == "__pycache__":
                dirnames[:] = []
                continue
            for name in filenames:
                if name.split(".")[0].casefold() in DEVICE_NAMES:
                    continue
                p = Path(dirpath) / name
                if str(p).casefold() in known_targets:
                    continue
                if p.suffix in {".pyc", ".pyo"}:
                    continue        # 生成物，不算资料
                items.append({
                    "path": str(p),
                    "category": cat,
                    "why": "磁盘上有、新版包里没有（旧版残留或用户自己放的）",
                    "size": p.stat().st_size,
                })

    # (b) 结构性裁决项（目录级）
    for path, cat, why in ARBITRATION_DIRS:
        if only is not None and cat not in only:
            continue
        if path.exists():
            items.append({"path": str(path), "category": cat, "why": why, "size": -1})

    return items


# --------------------------------------------------------------------------
# 七、② 备份阶段
#
# 照 `_tools/pika-迁移/backup_pika.py` 的形状：copytree 到 `_backup_<stamp>/`，
# 复制完比对「文件数 + 字节数」。区别有两点，都是这次刻意加严的：
#   1) 落点在 `_tools/pika-迁移/_backup_<时间戳>/`（backup_pika.py 落在知识根下）
#   2) **任何一个文件备份失败或对不上 ⇒ 直接中止整批**（backup_pika.py 是「源不存在就跳过」，
#      迁移场景下「跳过」等于「没备份就准备删」，绝对不能放过）
# --------------------------------------------------------------------------

@dataclass
class BackupReport:
    root: Path | None = None
    copied: int = 0
    bytes_copied: int = 0
    failures: list[str] = None

    def __post_init__(self) -> None:
        self.failures = self.failures or []


def backup(manifest: list[DeleteItem]) -> BackupReport:
    """把清单里每个旧文件复制到备份根，逐条核对 sha256。失败即中止（返回 failures）。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst_root = MIG_DIR / f"_backup_{stamp}"
    dst_root.mkdir(parents=True, exist_ok=False)     # 已存在就报错，不覆盖上一次备份
    rep = BackupReport(root=dst_root)

    for item in manifest:
        # 备份内保持「相对知识根」的路径结构，方便原样拷回
        try:
            rel = item.old_abs.relative_to(ROOT)
        except ValueError:
            rel = Path("_external") / item.category / item.old_abs.name
        dst = dst_root / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.old_abs, dst)
            if sha256_file(dst) != item.old_sha:
                rep.failures.append(f"备份内容与源不一致: {item.old_abs}")
                continue
            if dst.stat().st_size != item.size:
                rep.failures.append(f"备份大小与源不一致: {item.old_abs}")
                continue
            rep.copied += 1
            rep.bytes_copied += item.size
        except OSError as exc:
            rep.failures.append(f"备份失败 {item.old_abs}: {type(exc).__name__}: {exc}")

    # 总数核对：清单里每一条都必须有一份备份
    if rep.copied != len(manifest):
        rep.failures.append(f"备份条数不足：清单 {len(manifest)} 条，成功 {rep.copied} 条")
    return rep


# --------------------------------------------------------------------------
# 八、③ delete 阶段 —— 只消费清单
# --------------------------------------------------------------------------

@dataclass
class DeleteReport:
    deleted: int = 0
    bytes_freed: int = 0
    failures: list[str] = None

    def __post_init__(self) -> None:
        self.failures = self.failures or []


def delete(manifest: list[DeleteItem], dry_run: bool) -> DeleteReport:
    """逐条打印「绝对路径 + 原因 + 大小」，dry_run 时不真删。"""
    rep = DeleteReport()
    for item in manifest:
        sha, locator, _ = item.triple()
        # 打印格式固定：先路径，再原因，再大小。人是照着这玩意儿核的。
        print(f"  [删] {human(item.size):>9}  {sha}")
        print(f"        原因：新版 {locator} 存在且 sha256 相同（{item.new_sha[:16]}…）")
        if dry_run:
            continue
        # 真删之前的最后一道保险：文件还是不是刚才验过的那一份？
        if not Path(sha).is_file():
            rep.failures.append(f"待删文件在备份后消失了: {sha}")
            break
        try:
            now = sha256_file(Path(sha))
        except OSError as exc:
            rep.failures.append(f"删除前复读失败 {sha}: {type(exc).__name__}: {exc}")
            break
        if now != item.old_sha:
            rep.failures.append(f"待删文件在备份后被改动，已停止整批: {sha}")
            break
        try:
            os.remove(Path(sha))
        except OSError as exc:
            rep.failures.append(f"删除失败 {sha}: {type(exc).__name__}: {exc}")
            break
        rep.deleted += 1
        rep.bytes_freed += item.size
    return rep


# --------------------------------------------------------------------------
# 九、④ place 阶段（不删东西）
#
# 目标位 = 磁盘上最终该有的样子。只写两类：
#   * delete 清单里那些（旧内容已被上一步删掉，写新版）
#   * 新版有、旧版没有的（old_missing）
# 已存在且内容已经等于新版的，一律跳过（幂等，重复跑不会反复写盘）。
# --------------------------------------------------------------------------

@dataclass
class PlaceReport:
    written: int = 0
    bytes_written: int = 0
    skipped_same: int = 0
    failures: list[str] = None

    def __post_init__(self) -> None:
        self.failures = self.failures or []


def place(delete_items: list[DeleteItem], only: set[str] | None, dry_run: bool) -> PlaceReport:
    rep = PlaceReport()
    src = NewSource()
    planned: list[tuple[Path, str, bytes, str]] = []

    try:
        # (a) 清单里的：删完就写新版
        for item in delete_items:
            data, locator = src.read_new(item.origin, item.zip_path)
            planned.append((target_path(item.origin, item.zip_path), locator, data, item.category))

        # (b) 新版有、旧版没有的
        for row in build_rows():
            if row.get("match") != "old_missing":
                continue
            cat = category_of(row)
            if only is not None and cat not in only:
                continue
            try:
                data, locator = src.read_new(row["origin"], row["zip_path"])
            except (KeyError, zipfile.BadZipFile, OSError) as exc:
                rep.failures.append(f"新版读取失败 {row['zip_path']}: {exc}")
                continue
            # 「新版独有」的条目在 b3_fullhash 里没有 sha 记录（那份清单只覆盖配上的 3771 条），
            # 所以这里改校验**字节数**==勘察记录的 zip_size —— 仍是「内容对得上」的实证，
            # 不是凭 zip 能打开就算数。
            expected_size = row.get("zip_size")
            if expected_size is not None and len(data) != expected_size:
                rep.failures.append(
                    f"新版字节数与勘察记录不符: {row['zip_path']} "
                    f"（实测 {len(data)}，记录 {expected_size}）"
                )
                continue
            planned.append((target_path(row["origin"], row["zip_path"]), locator, data, cat or "?"))
    finally:
        src.close()

    for dst, locator, data, cat in planned:
        new_sha = sha256_bytes(data)
        if dst.is_file():
            try:
                if sha256_file(dst) == new_sha:
                    rep.skipped_same += 1
                    continue
            except OSError as exc:
                rep.failures.append(f"目标不可读 {dst}: {exc}")
                continue
        print(f"  [写] {human(len(data)):>9}  {dst}")
        print(f"        来源：{locator}")
        # 统计口径：dry-run 也算「要写」，否则人看到的 0 条 0 B 没法判断工作量
        rep.written += 1
        rep.bytes_written += len(data)
        if dry_run:
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            scratch = dst.with_name(dst.name + ".pika-tmp")
            scratch.write_bytes(data)
            os.replace(scratch, dst)          # 原子替换，半截文件不会留在盘上
        except OSError as exc:
            rep.failures.append(f"写入失败 {dst}: {type(exc).__name__}: {exc}")
            continue
        rep.written += 1
        rep.bytes_written += len(data)

    return rep


# --------------------------------------------------------------------------
# 九之前：清单的落盘与读回
#
# 卡 B3 要求「verify 产出一张 [(旧路径, 新版路径, sha256)] 清单，execute 只消费这张清单」。
# 同一进程内传 list 就已经满足；但为了让人**能先看**再决定跑不跑，这里再把它落成 JSON：
#   dry-run  → 写出 <MIG_DIR>/_plans/plan_<时间戳>.json，并打印路径
#   --execute → 带 --plan <那个文件> 就直接消费它（不重新推导该删谁）
# 落盘是写文件，但不碰任何被迁移的数据，也不算「执行」。
# --------------------------------------------------------------------------

PLAN_DIR = MIG_DIR / "_plans"


def save_plan(manifest: list[DeleteItem], only: set[str] | None, mode: str) -> Path:
    """把删除清单写成 JSON。文件名带时间戳，不覆盖旧的（每次审核都有据可查）。"""
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    path = PLAN_DIR / f"plan_{time.strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "schema": "pika-migrate-plan/1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "knowledge_root": str(ROOT),
        "only": sorted(only) if only else list(CATEGORIES),
        "mode": mode,
        "count": len(manifest),
        "bytes": sum(i.size for i in manifest),
        # 每条就三样核心：旧绝对路径、新版定位符、新版 sha256
        "items": [
            {
                "old_abs": item.triple()[0],
                "new_locator": item.triple()[1],
                "new_sha": item.triple()[2],
                "old_sha": item.old_sha,
                "size": item.size,
                "category": item.category,
                "zip_path": item.zip_path,
                "origin": item.origin,
            }
            for item in manifest
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return path


def load_plan(path: Path) -> list[DeleteItem]:
    """读回清单。**只接受本脚本写出的 schema**，别的一律 refuse。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "pika-migrate-plan/1":
        raise SystemExit(f"拒绝执行：{path} 不是本脚本写出的清单（schema={data.get('schema')!r}）")
    return [
        DeleteItem(
            old_abs=Path(it["old_abs"]),
            new_locator=it["new_locator"],
            new_sha=it["new_sha"],
            old_sha=it["old_sha"],
            size=it["size"],
            category=it["category"],
            zip_path=it["zip_path"],
            origin=it["origin"],
        )
        for it in data["items"]
    ]


# --------------------------------------------------------------------------
# 十、命令行
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="pika 新旧版迁移器（默认 dry-run；真跑要 --execute 再加 --i-understand-delete）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dry-run", action="store_true",
                   help="只打印不执行（默认就是这个；显式写出来只是为了看得清）")
    p.add_argument("--execute", action="store_true",
                   help="真的执行（还需同时给 --i-understand-delete）")
    p.add_argument("--i-understand-delete", action="store_true",
                   help="二次确认旗：我明白这一步会删除 D 盘上的旧文件")
    p.add_argument("--only", default="",
                   help="只跑某几类，逗号分隔：" + ",".join(CATEGORIES))
    p.add_argument("--mode", choices=("replace-changed", "mirror"), default="replace-changed",
                   help="replace-changed（默认）：只处理内容不同的条；mirror：连内容相同的也重建一遍")
    p.add_argument("--place", action="store_true",
                   help="顺带执行 ④ place 阶段（写新版内容；这一阶段不删东西）")
    p.add_argument("--skip-backup", action="store_true",
                   help="跳过备份（仅用于演练；真跑请不要用）")
    p.add_argument("--explain-arbitration", action="store_true",
                   help="只列出「需要人裁决」的项，不做任何其他事")
    p.add_argument("--plan", default="",
                   help="执行时消费指定的清单文件（由 dry-run 写出），而不是现场重新推导")
    return p.parse_args(argv)


def parse_only(raw: str) -> set[str] | None:
    if not raw.strip():
        return None
    want = {x.strip() for x in raw.split(",") if x.strip()}
    bad = want - set(CATEGORIES)
    if bad:
        raise SystemExit(f"--only 里有无法识别的分类: {', '.join(sorted(bad))}\n可选: {', '.join(CATEGORIES)}")
    return want


def print_banner(args, only) -> None:
    print("=" * 78)
    print("pika 迁移器")
    print(f"  知识根      : {ROOT}")
    print(f"  外层包(只读): {OUTER_ZIP}")
    print(f"  分类        : {', '.join(sorted(only)) if only else '全部（' + ', '.join(CATEGORIES) + '）'}")
    print(f"  模式        : {args.mode}")
    print(f"  运行方式    : {'真跑（--execute）' if args.execute else 'dry-run（默认，不删不写）'}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    args = parse_args(argv)

    # ---- 二次确认：缺 --execute 或 缺 --i-understand-delete，任一缺失都拒绝执行 ----
    # 这一段放在最前面，是因为它必须在**读任何东西、删任何东西之前**就把人拦住。
    if args.execute and not args.i_understand_delete:
        print("拒绝执行：缺少二次确认旗。")
        print()
        print("  你给了      : --execute")
        print("  还缺        : --i-understand-delete")
        print()
        print("  这一步会**删除**下列目录里的旧文件（删除前会先备份、先验 sha256）：")
        print(f"      {ROOT / 'Library' / '开源资源'}")
        print(f"      {ROOT / 'Library' / 'pika的presentations'}")
        print(f"      {ROOT / 'Tool' / '代码与数据'}")
        print(f"      {ROOT / '知识库' / 'pika文件_Pro' / 'AI工具'}")
        print(f"      {VAULT_TARGET}")
        print(f"      {GRIDLAB_TARGET}")
        print(f"      {SKILLS_ROOT}")
        print()
        print("  确认无误就把两个旗都给上：")
        print("      python -X utf8 tools/pika_migrate.py --execute --i-understand-delete")
        print()
        print("  或者先看一遍会删什么（dry-run，什么都不会发生）：")
        print("      python -X utf8 tools/pika_migrate.py")
        return 2

    if args.i_understand_delete and not args.execute:
        print("提示：--i-understand-delete 已给，但缺 --execute，因此仍按 dry-run 处理。")
        print("      真跑请补上 --execute。")
        print()

    if args.skip_backup and args.execute:
        print("拒绝执行：--skip-backup 与 --execute 不能同时给。")
        print("  备份是删除的前置条件；要演练请只跑 dry-run。")
        return 2

    only = parse_only(args.only)
    print_banner(args, only)

    # ---- 只列裁决项 ----
    if args.explain_arbitration:
        src = NewSource()
        try:
            items = collect_arbitration(only, src)
        finally:
            src.close()
        print()
        print(f"需要人裁决的项：{len(items)} 条（本脚本不会删它们）")
        for it in sorted(items, key=lambda x: (x["category"], x["path"])):
            size = "目录" if it["size"] < 0 else human(it["size"])
            print(f"  [{it['category']:<7}] {size:>9}  {it['path']}")
            print(f"            {it['why']}")
        return 0

    # ---- ① verify ----
    print()
    if args.execute:
        if args.plan:
            # 只消费清单：这一支**不重新推导**该删谁，人不点头的条目根本进不来
            plan_path = Path(args.plan)
            if not plan_path.is_file():
                print(f"拒绝执行：清单文件不存在: {plan_path}")
                return 2
            rep = VerifyReport()
            rep.manifest = load_plan(plan_path)
            print(f"[① verify] 已从清单读入 {len(rep.manifest)} 条，跳过现场验证")
            print(f"    清单: {plan_path}")
            print(f"    合计: {human(sum(i.size for i in rep.manifest))}")
        else:
            print("[① verify] 逐条验证「新版存在且内容正确」+「旧版现场未变」……")
            t0 = time.time()
            rep = verify(only, args.mode)
            print(f"  验证完成，用时 {time.time() - t0:.1f}s")
    else:
        print("[① verify] 逐条验证「新版存在且内容正确」+「旧版现场未变」……")
        t0 = time.time()
        rep = verify(only, args.mode)
        print(f"  验证完成，用时 {time.time() - t0:.1f}s")

    if not (args.execute and args.plan):
        print(f"    进删除清单 : {len(rep.manifest)} 条 / {human(sum(i.size for i in rep.manifest))}")
        print(f"    内容已相同 : {rep.skipped_same} 条（无需删除、无需重写）")
        print(f"    新版独有   : {rep.skipped_no_old} 条（只需写新版，不涉及删除）")
        print(f"    无映射根   : {rep.skipped_no_root} 条（安装器顶层文件 / 包本体，本次不动）")
        if only is not None:
            print(f"    被 --only 排除: {rep.skipped_excluded} 条")
        print(f"    验证失败   : {len(rep.failed)} 条")

    if rep.failed:
        print()
        print("  ⚠️ 以下条目验证没通过，**没有**进入删除清单：")
        for row, why in rep.failed[:40]:
            print(f"      {row['zip_path']}")
            print(f"        {why}")
        if len(rep.failed) > 40:
            print(f"      …… 另 {len(rep.failed) - 40} 条")

    # ---- 清单落盘（dry-run 时写，方便人先审再审） ----
    if not args.execute and rep.manifest:
        plan_path = save_plan(rep.manifest, only, args.mode)
        print()
        print(f"  清单已写出：{plan_path}")
        print("  审完确认无误，可让 --execute 直接消费它：")
        print(f"      python -X utf8 tools/pika_migrate.py --execute --i-understand-delete --plan {plan_path}")

    # ======================================================================
    # 到这里为止，**一个文件都还没动**。下面才是会改磁盘的三个阶段，顺序固定：
    #     ② backup → ③ delete → ④ place
    # 为什么是这个顺序：
    #   * backup 必须在 delete 之前 —— 没备份就删等于把旧版直接抹掉，回不来；
    #   * delete 必须在 place 之前 —— 用户要的是「先清旧版、再由新版填空」，
    #     反过来先写新版再删旧版，中间会有一段时间新旧混在一处，且删的时候
    #     可能已经分不清哪个是新写进去的；
    #   * 备份失败 ⇒ 后面两步都不跑（直接 return 3）。
    # ======================================================================

    # ---- ② backup（只在真跑时做；dry-run 连备份都不写盘） ----
    brep = None
    if args.execute and rep.manifest:
        print()
        print("[② backup] 备份将删的旧文件……")
        brep = backup(rep.manifest)
        print(f"  备份到 {brep.root}")
        print(f"  {brep.copied} 个文件 / {human(brep.bytes_copied)}")
        if brep.failures or brep.copied != len(rep.manifest):
            print("  ❌ 备份核对不通过，**已中止，一个文件都没删**：")
            for f in brep.failures[:20]:
                print("     ", f)
            if brep.copied != len(rep.manifest):
                print(f"     备份数 {brep.copied} ≠ 清单数 {len(rep.manifest)}")
            return 3
        print("  ✅ 备份核对通过（文件数与 sha256 全部对上），可以进入删除阶段")

    # ---- ③ delete（dry-run 时只是打印） ----
    print()
    print(f"[③ delete] 清单 {len(rep.manifest)} 条" + ("—— dry-run，以下只是打印" if not args.execute else ""))
    drep = delete(rep.manifest, dry_run=not args.execute)

    # 删除阶段一旦中止，**不再继续写新版** —— 半删半写的状态最难收拾
    if drep.failures:
        print()
        print("[统计]")
        print(f"  会删         : {drep.deleted} 条（已中止，未完成）")
        print(f"  验证失败     : {len(rep.failed)} 条")
        print("  ❌ 删除阶段中止，place 阶段未执行：")
        for f in drep.failures:
            print("     ", f)
        return 4

    # ---- ④ place ----
    prep = None
    if args.place:
        print()
        print("[④ place] 写新版内容" + ("—— dry-run，以下只是打印" if not args.execute else ""))
        prep = place(rep.manifest, only, dry_run=not args.execute)

    # ---- 统计 ----
    print()
    print("[统计]")
    print(f"  会删         : {len(rep.manifest) if not args.execute else drep.deleted} 条"
          f" / {human(sum(i.size for i in rep.manifest))}")
    print(f"  验证失败     : {len(rep.failed)} 条")
    print(f"  跳过(已相同) : {rep.skipped_same} 条")
    print(f"  跳过(无映射根): {rep.skipped_no_root} 条")
    print(f"  待裁决       : {len(rep.arbitration)} 条（本脚本不删，用 --explain-arbitration 看）")
    if prep is not None:
        print(f"  写新版       : {prep.written if args.execute else len(rep.manifest) + rep.skipped_no_old} 条"
              f" / {human(prep.bytes_written)}")
    if drep.failures:
        print("  ❌ 删除阶段中止：")
        for f in drep.failures:
            print("     ", f)
        return 4
    if prep is not None and prep.failures:
        print("  ❌ 写入阶段有失败：")
        for f in prep.failures:
            print("     ", f)
        return 5

    print()
    if not args.execute:
        print("dry-run 结束：**没有删除、没有写入任何东西**。")
        print("真跑需要两个旗一起给：--execute --i-understand-delete")
    else:
        print("执行结束。回滚方式：把备份目录里的文件按原相对路径拷回知识根。")
        if brep and brep.root:
            print(f"  备份: {brep.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
