# ruff: noqa: E501
# ★ 卡 119（T-G217）：本文件是从 scratch 原型（gates/diag/tf_batch.py）**整份搬**进来的，
#   33 条钉子逐条验过"行为一字未变"。里面有多处**中文长行** —— E501 按**显示宽度**算（CJK 一字 = 2 列），
#   而这些行多是中文整句，拆行必然要动**字符串字面量**，风险不该在"搬家"这张卡里担。
#   ⇒ 本次**整份豁免 E501**，拆行的纯美化**另开一张卡**（记在卡 119 的正文与 _todo_pending 里）。
r"""任务栅栏：**注册一个跨层的任务 → 每张卡交成送申请 → 集齐才收口**（用户 2026-10-02 定的形状）。

**防什么**：一笔提交 = 一张卡 + 一棵树 + 一趟 17 道门（约 5 分钟）+ 三段文书，**与改动大小无关**
（卡 113 改 16 行、卡 114 改 9 行照走全流程）。用户要的是**版本管理式的攒批**，并把它说准了两次：

> 第一次：『要引入**版本管理**的理念：小规模的改动应该**堆在一起**，同一个板块堆在一起写文书会好一点。』
> 第二次（**纠正我理解错的地方**）：『收批应该是我根据**任务的种类**，就是属于不同的板块，比如属于
> **审美层**的、属于**后端**的、属于**前端**的。然后我在外包程序的某个地方**注册一个任务**，
> 然后任务需要这些板块下面的**多张卡都完成了**，并且**发送了那个成功申请**，然后**集齐所有的成送申请**
> 再写 —— **而不是单纯的数量**。』

★ 所以本模块的形状是**任务**（不是"同目录族攒够 N 条"）：

    [[member]]              一个任务 = 若干张卡；每张卡带**自己的层**、**自己的域**
    id = "卡115"            卡的域就是这张卡能碰的路径（＝卡规格里的禁区/冲突域）
    layer = "后端"          层只用来**归类与写文书**（审美层 / 后端 / 前端 … 各项目自己定）
    paths = ["scripts/run_gates.py", "tests/test_seal_untracked.py"]

- **注册任务**（人，开工前）：声明它需要哪些卡、每张卡属于哪层 ⇒ 成员名单**预先定死**。
- **成送申请**（各卡自己）：干完了就往收件箱投一份**带证据**的成功申请；投"不通过"就**挡住收口**。
- **集齐才收口**：★ **判据是"名单上的每一张卡都交了成功申请"**（或缺席者被**显式豁免**），
  **不是**"攒够了 N 条"。少一张卡就等着 —— 永远不会因为"数量够了"提前放行。
- **最后一名投递者当场关门**：不轮询、不起守候进程（守候进程要判死，今晚已经为"判死"付过代价）。
- 集齐后**自动**：跑任务里声明的门禁命令 → 读数进状态 → 按**层**生成三段文书骨架。
- ★ **停在 `awaiting-commit`，绝不自动提交**：① 门禁红时提交是红线；② 『一笔提交恰好一个台账号』
  是审计的机器判据，要人过一眼。（想全自动：`on_complete` 加 `commit`，**本版故意不实现**。）

**四条安全阀**（缺一条就会卡死或提前放行）：
- ★★ **逐卡的域检查**：一张卡投上来的文件必须落在**它自己声明的域**里 —— 否则任务会变成
  **绕过冲突域的后门**（这是本模块最重要的一条守卫）。
- **名单外不算数**（防夹带）；重复投递**幂等**（只算一次，内容可更新）。
- **`waive` 显式豁免**：谁没到要**留痕**；豁免后计数照算，账上写着谁没到。
- **过期只判死**：到期 ⇒ `timeout` 并列出缺席者，**绝不自作主张放行**（要人显式豁免或续期）。

**边界（如实写）**：
- ★ 用**主工作树**（`git rev-parse --git-common-dir` 的父目录）。**不许**用 `--show-toplevel`：
  卡树里回的是卡树，写进去等于没写（同一个坑在 `tools/pool/registry.py` 里踩过）。
- ★ 并发写用 `O_CREAT|O_EXCL` 自旋锁 + 同目录 `os.replace` 原子写；判据是"丢一次投递只会让任务多等"
  （安全方向），锁只是省掉白等。**只治单机**，跨机不做也不假装能做。
- ★ **已进 git（卡 119 / `T-G217`）—— 权威副本就是本文件**（`tools/pool/task.py`，模块 `pool.task`）。
  命令行壳是 `tools/wb_task.py`；旧的 `gates/diag/tf_batch.py` 保留成临时转发壳（免得旧调用点当夜断掉）。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fnmatch
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import tomllib

#: 任务相关文件都放这儿（相对主工作树根）。
BATCH_REL = ("gates", "diag", "batch")

#: 集齐后允许声明的自动化动作（**故意不含 commit**，见模块头）。
ALLOWED_ACTIONS = ("gate", "draft")

#: 状态机的合法态。
STATES = (
    "collecting",      # 还缺卡（或某张卡投了"不通过"）
    "ready",           # 齐了（机器刚数完）
    "gating",          # 正在跑门禁
    "awaiting-commit",  # ★ 停这儿：文书骨架已生成，等人补『为什么』并提交
    "landed",          # 提交了（要人显式标）
    "timeout",         # 过期，缺席者列出来了（要人 waive 或 extend）
)


class BatchError(Exception):
    """环境 / 文件 / 用法层面的错（与"守卫拒收"分开）。"""


class RefuseError(Exception):
    """守卫拒收（域越界 / 不在名单 / 状态不对）—— `reasons` 里逐条点名。"""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("；".join(self.reasons))


# ================================================================ 主树定位 / 路径


def main_tree_root() -> Path:
    """主工作树根 = `git rev-parse --git-common-dir` 的**父目录**。

    ★ `cwd` 必须显式给（从本文件推）：服务可能被别的程序（如 DSH 起 MCP 子进程）从仓外拉起。
    """
    tree_root = Path(__file__).resolve().parents[2]
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(tree_root) if tree_root.is_dir() else None,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise BatchError(f"算不出主工作树（跑不了 git：{exc}）") from exc
    raw = (done.stdout or "").strip()
    if done.returncode or not raw:
        raise BatchError("算不出主工作树：`git rev-parse --git-common-dir` 没回路径")
    common = Path(raw)
    if not common.is_absolute():
        common = Path.cwd() / common
    return common.resolve().parent


def batch_dir() -> Path:
    """任务目录：`TF_BATCH_DIR` 覆盖（自证要用），否则主树下 `gates/diag/batch/`。"""
    override = os.environ.get("TF_BATCH_DIR", "").strip()
    if override:
        return Path(override)
    return main_tree_root() / Path(*BATCH_REL)


def manifest_path(task_id: str) -> Path:
    return batch_dir() / f"{task_id}.toml"


def state_path(task_id: str) -> Path:
    return batch_dir() / f"{task_id}.json"


def inbox_dir(task_id: str) -> Path:
    return batch_dir() / f"{task_id}.d"


def pool_path() -> Path:
    """"还没定卡的活"的登记表（可选；任务也可以直接注册成员）。"""
    return batch_dir() / "pool.json"


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def whoami() -> str:
    window = os.environ.get("TF_WINDOW_ID", "").strip()
    return window or f"{socket.gethostname()}:{os.getpid()}"


# ================================================================ 原子写 / 自旋锁


def write_json_atomic(target: Path, payload: object) -> None:
    """同目录 `tmp` + `os.replace`（同文件系统 ⇒ 原子）：读者只会看到旧整份或新整份。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


@contextlib.contextmanager
def spin_lock(target: Path, timeout: float = 10.0):
    """`O_CREAT|O_EXCL` 自旋锁。判据：拿不到只影响"白等"，不影响正确性。

    ★ `yield` **必须在取到锁之后、循环之外** —— 放在 `while` 里，上下文正常退出后生成器会绕回
    循环再 yield 一次，`contextlib` 直接报 `RuntimeError: generator didn't stop`（自证时咬过）。
    ★ 锁所在目录可能还不存在（**新机器第一次用**就是这样）；先建目录，否则 `os.open` 报
    FileNotFoundError（也是自证时咬过的）。
    """
    lock = target.with_suffix(target.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() > deadline:
                raise BatchError(f"拿不到任务锁（{lock}）—— 有别的进程在写，稍后重试") from None
            time.sleep(0.05)
            continue
        os.write(fd, f"{whoami()} {now_iso()}\n".encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _toml_str(value: str) -> str:
    """把一段文本写成 **TOML 基本字符串字面量**（含引号 / 反斜杠也写不坏文件）。

    ★ 转义规则与 JSON 基本字符串同规，所以直接借 `json.dumps`：`"` → `\\"`、`\\` → `\\\\`、
    控制字符 → `\\uXXXX`，产出的都是合法 TOML。`ensure_ascii=False` 让中文原样落盘（更好读）。
    """
    return json.dumps(value, ensure_ascii=False)


def read_json(target: Path) -> dict:
    if not target.exists():
        raise BatchError(f"没有这个文件：{target}")
    text = target.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BatchError(f"文件坏了，**不动它**：{target}（{exc}）") from exc
    if not isinstance(data, dict):
        raise BatchError(f"结构不对（顶层应是对象）：{target}")
    return data


# ================================================================ 注册任务（预声明）


def _validate_manifest(man: dict, task_id: str) -> None:
    """预声明的全套校验 —— **落盘之前**就要跑（否则不合法任务会留在目录里）。"""
    if man.get("id") != task_id:
        raise BatchError(f"预声明里的 id（{man.get('id')!r}）与文件名（{task_id!r}）不一致")
    if not man.get("why"):
        raise BatchError("预声明缺 `why`（这个任务要干成什么）")
    members = man.get("member") or []
    if not isinstance(members, list) or not members:
        raise BatchError("预声明里一张卡都没有（`[[member]]`）")
    ids = [m.get("id", "") for m in members]
    if "" in ids:
        raise BatchError("有成员没写 `id`（卡号）")
    if len(set(ids)) != len(ids):
        raise BatchError(f"成员（卡号）有重复：{ids}")
    for m in members:
        if not m.get("layer"):
            raise BatchError(f"卡 {m.get('id')} 没写 `layer`（属于哪一层：审美层 / 后端 / 前端 …）")
        if not m.get("paths"):
            raise BatchError(f"卡 {m.get('id')} 没写 `paths`（这张卡的域＝它能碰的路径）")
    for action in man.get("on_complete", ["gate", "draft"]):
        if action not in ALLOWED_ACTIONS:
            raise BatchError(f"`on_complete` 里有不认识的动作 {action!r}（只认 {ALLOWED_ACTIONS}）")


def load_manifest(task_id: str) -> dict:
    path = manifest_path(task_id)
    if not path.exists():
        raise BatchError(f"没有这个任务的预声明：{path}（先 `register`）")
    with path.open("rb") as fh:
        man = tomllib.load(fh)
    _validate_manifest(man, task_id)
    return man


def member_of(man: dict, member_id: str) -> dict:
    for m in man.get("member") or []:
        if m.get("id") == member_id:
            return m
    raise BatchError(f"预声明里没有这张卡：{member_id}")


def layers_of(man: dict) -> list[str]:
    """按预声明顺序列出层（写文书时按层分组）。"""
    out: list[str] = []
    for m in man.get("member") or []:
        if m["layer"] not in out:
            out.append(m["layer"])
    return out


def cmd_register(args: argparse.Namespace) -> int:
    src = Path(args.manifest)
    if not src.is_absolute():
        src = Path.cwd() / src
    if not src.exists():
        raise BatchError(f"找不到预声明文件：{src}")
    with src.open("rb") as fh:
        man = tomllib.load(fh)
    task_id = str(man.get("id", "")).strip()
    if not task_id:
        raise BatchError("预声明里没写 `id`（任务号）")

    root = batch_dir()
    root.mkdir(parents=True, exist_ok=True)
    if state_path(task_id).exists() and not args.force:
        raise BatchError(f"任务已存在：{state_path(task_id)}（要覆盖加 `--force`）")
    # ★ 先在内存里验完再落盘 —— 免得留下"半截任务"（目录里有文件、没有状态）。
    _validate_manifest(man, task_id)
    dest = manifest_path(task_id)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    man = load_manifest(task_id)
    members = [m["id"] for m in man["member"]]

    state = {
        "id": task_id,
        "why": man["why"],
        "layers": layers_of(man),
        "declared": members,
        "need": len(members),          # ★ 判据是"名单上每张卡都交了成功申请"，不是数量阈值
        "claims": {},                  # 卡号 → 成送申请（success / failed）
        "waived": [],
        "state": "collecting",
        "auto": list(man.get("on_complete", ["gate", "draft"])),
        "gate_cmd": man.get("gate_cmd"),
        "deadline": man.get("deadline"),
        "gate": None,
        "draft": None,
        "landed": None,
        "history": [],
    }
    _log(state, "-", "collecting",
         f"注册任务：{len(members)} 张卡 · 层 {'、'.join(state['layers'])} · 集齐条件=**全部成送申请**")
    write_json_atomic(state_path(task_id), state)
    print(f"任务 {task_id} 注册好了：{len(members)} 张卡 / 层 {'、'.join(state['layers'])}")
    print("  ★ 放行判据：名单上每一张卡都交了**成功申请**（或缺席者被显式豁免）—— 不看数量")
    print(f"  预声明：{dest}")
    return 0


def _log(state: dict, frm: str, to: str, note: str) -> None:
    """状态变化一律**追加**进 history（用户说的「把状态变成写日志」）。"""
    state["history"].append({"at": now_iso(), "by": whoami(), "from": frm, "to": to, "note": note})


# ================================================================ 成送申请（收件箱）


def check_domain(man: dict, member_id: str, files: list[str]) -> None:
    """★★ 最重要的守卫：这张卡碰的文件必须落在**它自己声明的域**里（否则任务＝绕过冲突域的后门）。"""
    mem = member_of(man, member_id)
    patterns = list(mem["paths"])
    bad = [f for f in files if not any(fnmatch.fnmatch(f, p) for p in patterns)]
    if bad:
        raise RefuseError([
            f"卡 {member_id}（{mem['layer']}）碰了**自己域外**的文件：{'、'.join(bad)}",
            f"这张卡的域是：{'、'.join(patterns)}",
            "要动域外的文件 ⇒ 改预声明里的域（那是**改冲突域声明**，要显式做）或另开一张卡",
        ])


def cmd_claim(args: argparse.Namespace) -> int:
    """一张卡交**成送申请**。★ 成功申请必须带证据（没证据的不叫申请）。"""
    if args.claim == "success" and not (args.evidence or "").strip():
        raise RefuseError([
            "成功申请**必须带证据**（`--evidence`）—— 没证据的不叫申请",
            "证据可以是：测试读数 / 门禁结论 / 命令原样输出 / 文件 sha256",
        ])
    with spin_lock(state_path(args.task)):
        man = load_manifest(args.task)
        state = read_json(state_path(args.task))
        if state["state"] in ("landed", "timeout"):
            raise RefuseError([f"任务已处于 {state['state']}，不再收申请（要先 `extend` 或另开任务）"])

        member_id = args.member
        if member_id not in state["declared"]:
            raise RefuseError([
                f"{member_id} 不在这个任务的名单里（名单：{'、'.join(state['declared'])}）",
                "★ 不在名单里的申请不算数 —— 防夹带（要加卡先改预声明并重建任务）",
            ])
        if member_id in state["waived"]:
            raise RefuseError([f"{member_id} 已被豁免，不能再交申请（要交先撤豁免）"])

        files = [f.strip() for f in (args.files or "").split(",") if f.strip()]
        check_domain(man, member_id, files)

        mem = member_of(man, member_id)
        payload = {
            "member": member_id,
            "layer": mem["layer"],
            "claim": args.claim,
            "at": now_iso(),
            "by": whoami(),
            "why": args.why,
            "files": files,
            "evidence": args.evidence or "",
            "log": args.log or "",
        }
        write_json_atomic(inbox_dir(args.task) / f"{member_id}.json", payload)

        first = member_id not in state["claims"]
        state["claims"][member_id] = args.claim
        mark = "成功申请" if args.claim == "success" else "★ 不通过"
        _log(state, state["state"], state["state"],
             f"卡 {member_id}（{mem['layer']}）交了{mark}"
             f"（{'首次' if first else '更新'}）：{args.why or '（没写为什么）'}")
        print(f"卡 {member_id} 的{mark}收了（{len(_ok(state))}/{state['need']} 张已成功，名单共 "
              f"{len(state['declared'])}）")
        print(f"  还缺：{_missing(state) or '（齐了）'}")
        advanced = _maybe_advance(state, man)
        write_json_atomic(state_path(args.task), advanced)
    return _report(advanced)


def _ok(state: dict) -> set[str]:
    """已交**成功**申请的卡（投"不通过"的不算）。"""
    return {mid for mid, kind in (state.get("claims") or {}).items() if kind == "success"}


def _bad(state: dict) -> list[str]:
    """投了"不通过"、还没改成成功、也没被豁免的卡。"""
    return [mid for mid, kind in (state.get("claims") or {}).items()
            if kind == "failed" and mid not in state["waived"]]


def _missing(state: dict) -> str:
    got = _ok(state) | set(state["waived"])
    return "、".join(m for m in state["declared"] if m not in got)


def cmd_waive(args: argparse.Namespace) -> int:
    """显式豁免：谁没到要留痕。**这是"不齐也能放行"的唯一合法路径**。"""
    with spin_lock(state_path(args.task)):
        man = load_manifest(args.task)
        state = read_json(state_path(args.task))
        if args.member not in state["declared"]:
            raise RefuseError([f"{args.member} 不在名单里（{'、'.join(state['declared'])}）"])
        if args.member in state["waived"]:
            print(f"{args.member} 早就豁免过了（幂等）")
            return 0
        if state.get("claims", {}).get(args.member) == "success":
            raise RefuseError([f"{args.member} 已经交过成功申请了，不用豁免"])
        state["waived"].append(args.member)
        _log(state, state["state"], state["state"],
             f"★ 豁免 {args.member}（不齐放行，留痕）：{args.reason}")
        print(f"已豁免 {args.member}：{args.reason}")
        print(f"  还缺：{_missing(state) or '（齐了）'}")
        advanced = _maybe_advance(state, man)
        write_json_atomic(state_path(args.task), advanced)
    return _report(advanced)


def cmd_extend(args: argparse.Namespace) -> int:
    with spin_lock(state_path(args.task)):
        man = load_manifest(args.task)
        state = read_json(state_path(args.task))
        frm = state["state"]
        state["deadline"] = args.to
        if frm == "timeout":
            state["state"] = "collecting"
            _log(state, frm, "collecting", f"续期到 {args.to}")
            print(f"续期到 {args.to}，状态退回 collecting（还缺：{_missing(state) or '（齐了）'}）")
        else:
            _log(state, frm, frm, f"续期到 {args.to}")
            print(f"续期到 {args.to}")
        advanced = _maybe_advance(state, man)
        write_json_atomic(state_path(args.task), advanced)
    return _report(advanced)


def cmd_landed(args: argparse.Namespace) -> int:
    with spin_lock(state_path(args.task)):
        state = read_json(state_path(args.task))
        frm = state["state"]
        state["state"] = "landed"
        state["landed"] = {"commit": args.commit, "at": now_iso(), "by": whoami()}
        _log(state, frm, "landed", f"收口提交了：{args.commit}")
        write_json_atomic(state_path(args.task), state)
    print(f"任务 {args.task} 标成 landed（{args.commit}）")
    return 0


# ================================================================ 集齐 → 自动放行


def _maybe_advance(state: dict, man: dict) -> dict:
    """数**成送申请**；齐了才推过栅栏并跑任务里声明的自动动作。**幂等**：不齐就原样返回。"""
    if state["state"] in ("ready", "gating", "awaiting-commit", "landed"):
        return state
    got = _ok(state) | set(state["waived"])
    if len(got) < state["need"]:
        return state
    # ★ 有"不通过"的卡没处理 ⇒ 挡住（哪怕名单上别的卡都成功了）。
    bad = _bad(state)
    if bad:
        frm = state["state"]
        _log(state, frm, frm,
             f"★ 齐了但**有卡投了不通过**：{'、'.join(bad)} ⇒ 不放行（要么重投成功申请，要么显式豁免）")
        return state
    frm = state["state"]
    state["state"] = "ready"
    _log(state, frm, "ready",
         f"★ **集齐全部成送申请**（{len(got)}/{state['need']}）—— 最后一个投递者当场关门，"
         f"自动动作 {state['auto']}")
    if state["waived"]:
        _log(state, "ready", "ready", f"注意：放行时有豁免（{'、'.join(state['waived'])}）")
    return _run_auto(state, man)


def _run_auto(state: dict, man: dict) -> dict:
    """跑 `on_complete` 里声明的动作：`gate` → `draft`。★ **没有 commit**（见模块头）。"""
    if "gate" in state["auto"]:
        state["state"] = "gating"
        _log(state, "ready", "gating", f"跑门禁：{state['gate_cmd'] or '（任务里没声明 gate_cmd，跳过）'}")
        if state["gate_cmd"]:
            done = subprocess.run(state["gate_cmd"], shell=True, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
            state["gate"] = {
                "cmd": state["gate_cmd"],
                "exit_code": done.returncode,
                "verdict": "green" if done.returncode == 0 else "red",
                "at": now_iso(),
                "tail": "\n".join(((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-12:]),
            }
            _log(state, "gating", "gating",
                 f"门禁读数：exit={done.returncode} ⇒ **{state['gate']['verdict']}**")
            if done.returncode != 0:
                state["state"] = "ready"
                _log(state, "gating", "ready", "★ 门禁红了 ⇒ **不许提交**；修好再 `advance`")
                return state
        else:
            state["gate"] = {"cmd": None, "exit_code": None, "verdict": "skipped", "at": now_iso()}
    if "draft" in state["auto"]:
        text = render_draft(state, man)
        draft = batch_dir() / f"{state['id']}.draft.md"
        draft.write_text(text, encoding="utf-8", newline="\n")
        # ★ 人手补的"为什么"放**单独文件**（只建一次）—— 骨架可以随时重算而不冲掉人写的东西。
        why = batch_dir() / f"{state['id']}.why.md"
        if not why.exists():
            why.write_text(render_why_skeleton(state, man), encoding="utf-8", newline="\n")
        state["draft"] = {"path": str(draft), "at": now_iso(), "bytes": len(text.encode("utf-8")),
                          "why": str(why)}
        _log(state, state["state"], "awaiting-commit",
             f"文书骨架生成：{draft.name}（{state['draft']['bytes']} 字节，按层分组）"
             f"· 人手补『为什么』写 {why.name} ⇒ **停这儿等人补完并提交**")
    state["state"] = "awaiting-commit"
    return state


def render_draft(state: dict, man: dict) -> str:
    """把各卡的成送申请拼成文书骨架（**按层分组**）—— 这就是"省掉我写枚举"的那一半。"""
    blocks = []
    for layer in state["layers"]:
        rows = []
        for mem in man["member"]:
            if mem["layer"] != layer:
                continue
            mid = mem["id"]
            inbox = inbox_dir(state["id"]) / f"{mid}.json"
            if mid in state["waived"]:
                rows.append(f"| {mid} | {mem.get('what', '')} | —— | ★ **豁免**（没到） |")
                continue
            if not inbox.exists():
                rows.append(f"| {mid} | {mem.get('what', '')} | —— | ★ **缺席** |")
                continue
            got = read_json(inbox)
            kind = "" if got.get("claim") == "success" else "★**不通过** "
            files = "、".join(got.get("files") or []) or "——"
            rows.append(f"| {mid} | {kind}{got.get('why') or mem.get('what', '')} | {files} | "
                        f"{got.get('evidence') or '——'} |")
        blocks.append(f"### 层：{layer}\n\n| 卡 | 改了什么 | 碰过的文件 | 证据 |\n|---|---|---|---|\n"
                      + "\n".join(rows))
    body = "\n\n".join(blocks)
    gate = state.get("gate") or {}
    return f"""# 任务 {state['id']} 文书骨架（按**层**分组）

> 任务一句话：{state['why']}
> 层：{'、'.join(state['layers'])}
> 集齐：{len(_ok(state) | set(state['waived']))}/{state['need']} 张卡的**成送申请**（名单 {len(state['declared'])} 张）
> 门禁：{gate.get('verdict', '（没跑）')}（exit={gate.get('exit_code')}）
> ★ 枚举已由机器填好（**勿手改本文件：它随时会被重算**）；人要写的部分在 `{state['id']}.why.md`。

## 一、这个任务改了哪些（机器填）

{body}

## 二、台账行（骨架）

```
- id = "T-G???"
  title = "（这个任务作为一个整体干了什么，一句话）"
  type = "???"        # feat / fix / docs / refactor / test
  scope = "???"
  group = "???"
  refs = [{{}}]        # 各卡自己的 refs 拼起来
```

## 三、changelog 节（骨架）

```
### T-G??? （任务 {state['id']}：{state['why']}）
- 为什么：（★ 人写）
- 改了什么：见上表（机器按层填好）
- 证据：门禁 {gate.get('verdict', '?')}；各卡证据见上表
```

## 四、CHECKPOINT 段（骨架）

```
- 任务 {state['id']}（{len(state['declared'])} 张卡一次收口）：{state['why']}
  · 为什么攒成一批：（★ 人写一句）
  · 与单卡流程的差别：一次收口 / 一段文书 / 一趟门禁
```
"""


def render_why_skeleton(state: dict, man: dict) -> str:
    """人手补的部分（**只建一次、永不自动覆盖**）。"""
    return f"""# 任务 {state['id']} —— 人手补的部分（机器不会覆盖这个文件）

> 成员：{'、'.join(state['declared'])} · 层：{'、'.join(state['layers'])} ·
> 集齐 {len(_ok(state) | set(state['waived']))}/{state['need']}
> ★ 骨架（枚举表）在 `{state['id']}.draft.md`，**那个会被重算**；人写的东西写这里。

## 台账编号与归类（人定）

- id = "T-G???"
- title = "（这个任务作为一个整体干了什么，一句话）"
- type = "???"        # feat / fix / docs / refactor / test
- scope = "???"
- group = "???"
- refs = [???]

## 为什么这几张卡攒成一次收口（人写）

​
## 这个任务里哪张卡最值得记住（人写，可空）

​
## 与单卡流程的差别 / 代价（人写，可空）

​
"""


def cmd_advance(args: argparse.Namespace) -> int:
    """手动推一次（幂等）：门禁红了修好后重推、申请更新后**重算骨架**、或状态卡住时。"""
    with spin_lock(state_path(args.task)):
        man = load_manifest(args.task)
        state = read_json(state_path(args.task))
        if state["state"] == "awaiting-commit":
            # ★ 骨架随时可重算（人写的东西在 `<任务号>.why.md` 里，不在骨架里 ⇒ 冲不掉）。
            text = render_draft(state, man)
            draft = batch_dir() / f"{state['id']}.draft.md"
            before = draft.stat().st_size if draft.exists() else 0
            draft.write_text(text, encoding="utf-8", newline="\n")
            why = batch_dir() / f"{state['id']}.why.md"
            if not why.exists():
                why.write_text(render_why_skeleton(state, man), encoding="utf-8", newline="\n")
                print(f"（补建人手补写文件：{why.name}）")
            state["draft"] = {"path": str(draft), "at": now_iso(),
                              "bytes": len(text.encode("utf-8")), "why": str(why)}
            _log(state, state["state"], state["state"],
                 f"重算骨架：{before} → {state['draft']['bytes']} 字节（人手补的在 "
                 f"{state['id']}.why.md，不受影响）")
            write_json_atomic(state_path(args.task), state)
            print(f"骨架已重算（{state['draft']['bytes']} 字节）")
            return _report(state)
        state["state"] = "collecting"
        state = _maybe_advance(state, man)
        write_json_atomic(state_path(args.task), state)
    return _report(state)


def cmd_expire(args: argparse.Namespace) -> int:
    """过期判死：**只标 timeout + 列缺席者，绝不放行** —— 放行要人显式 waive。"""
    with spin_lock(state_path(args.task)):
        state = read_json(state_path(args.task))
        frm = state["state"]
        if state["state"] in ("landed", "awaiting-commit"):
            print(f"已经是 {state['state']}，不用判死")
            return 0
        state["state"] = "timeout"
        _log(state, frm, "timeout",
             f"到期（{state.get('deadline')}），缺席：{_missing(state)} ⇒ 等人工（waive 或 extend）")
        write_json_atomic(state_path(args.task), state)
    print(f"任务 {args.task} 标成 timeout，缺席：{_missing(state)}")
    return 0


def _report(state: dict) -> int:
    """把当前状态打一屏；门禁红了或不通过挡着 ⇒ **非零退出**（别让人以为"过了"）。"""
    gate = state.get("gate") or {}
    bad = _bad(state)
    print(f"状态：**{state['state']}** · 成功申请 {len(_ok(state))}/{state['need']} · "
          f"豁免 {len(state['waived'])} · 还缺 {_missing(state) or '（齐了）'}")
    if bad:
        print(f"★ 有卡投了**不通过**、还没处理：{'、'.join(bad)} —— 不放行（重投或豁免）")
        return 3
    if gate.get("verdict") == "red":
        print(f"★ 门禁红了（exit={gate.get('exit_code')}）—— 不提交。尾部读数：\n{gate.get('tail', '')}")
        return 3
    if state["state"] == "awaiting-commit":
        print(f"文书骨架：{state['draft']['path']}")
        print(f"人手补『为什么』：{state['draft'].get('why') or '（无）'}")
        print("★ 停在这儿：补完 → 走正常收口（`_integrate.py --batch`）→ 提交后 `landed`")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = read_json(state_path(args.task))
    man = load_manifest(args.task)
    print(f"任务 {state['id']}：{state['why']}")
    print(f"  层 {'、'.join(state['layers'])} · 集齐条件=**全部成送申请**（名单 {state['need']} 张卡）"
          f" · 自动 {state['auto']} · 期限 {state.get('deadline') or '（无）'}")
    for mem in man["member"]:
        mid = mem["id"]
        if mid in state["waived"]:
            tag = "★豁免"
        elif state.get("claims", {}).get(mid) == "success":
            tag = "✓成功申请"
        elif state.get("claims", {}).get(mid) == "failed":
            tag = "✗不通过"
        else:
            tag = "…还缺"
        print(f"  [{tag:<8}] {mid:<8} {mem['layer']:<8} {mem.get('what', '')}")
        print(f"             域：{'、'.join(mem['paths'])}")
    print("  --- history ---")
    for row in state["history"]:
        print(f"  {row['at']} {row['from']}→{row['to']} {row['note']}")
    return _report(state)


def cmd_list(args: argparse.Namespace) -> int:
    root = batch_dir()
    if not root.exists():
        print(f"（还没有任务：{root}）")
        return 0
    files = sorted(root.glob("*.json"))
    shown = False
    for path in files:
        if path.name == "pool.json":
            continue
        with contextlib.suppress(BatchError):
            st = read_json(path)
            if not isinstance(st.get("declared"), list):
                continue
            shown = True
            print(f"{st['id']:<22} {st['state']:<16} {len(_ok(st))}/{st['need']}  {st['why']}")
    if not shown:
        print(f"（还没有任务：{root}）")
    return 0


# ================================================================ 待定卡的活（可选登记）


def _load_pool() -> list[dict]:
    path = pool_path()
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BatchError(f"待办表坏了，**不动它**：{path}（{exc}）") from exc
    rows = data.get("pool") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise BatchError(f"待办表结构不对（`pool` 应是数组）：{path}")
    return [r for r in rows if isinstance(r, dict)]


def _save_pool(rows: list[dict]) -> None:
    write_json_atomic(pool_path(), {"pool": rows})


def cmd_pool(args: argparse.Namespace) -> int:
    """还没定卡的活先按**层**登记；注册任务时可以把它们收成成员（`register --from-pool <层>`）。

    ★ 这只是"提前明确哪些能一起干"的便利：**放行判据永远是"名单上每张卡都交了成功申请"**。
    """
    with spin_lock(pool_path()):
        rows = _load_pool()
        if args.action == "add":
            if not args.layer or not args.what:
                raise BatchError("`pool add` 要 `--layer` 与 `--what`")
            files = [f.strip() for f in (args.files or "").split(",") if f.strip()]
            mid = args.id or f"P-{len(rows) + 1}"
            if any(r.get("id") == mid for r in rows):
                raise BatchError(f"登记号重复：{mid}（换一个 `--id`）")
            rows.append({"id": mid, "layer": args.layer, "what": args.what,
                         "files": files, "at": now_iso(), "by": whoami()})
            _save_pool(rows)
            print(f"登记好了：{mid} · 层 {args.layer} · {args.what}")
            return 0
        if args.action == "list":
            picked = [r for r in rows if not args.layer or r.get("layer") == args.layer]
            if not picked:
                print("（待办表是空的）")
                return 0
            for r in picked:
                print(f"{r['id']:<8} {r['layer']:<8} {r['what']}")
            return 0
        if args.action == "drop":
            keep = [r for r in rows if r.get("id") != args.id]
            if len(keep) == len(rows):
                raise BatchError(f"待办表里没有 {args.id}")
            _save_pool(keep)
            print(f"{args.id} 划掉了")
            return 0
    raise BatchError(f"认不出 `pool {args.action}`")


def _register_from_pool(args: argparse.Namespace) -> int:
    """把某一层的待办登记收成任务的成员（每条的 `files` 就是这张卡的域）。"""
    rows = [r for r in _load_pool() if r.get("layer") == args.from_pool]
    if not rows:
        raise BatchError(f"层 {args.from_pool} 一条登记都没有（先 `pool add`）")
    if args.max:
        rows = rows[: args.max]
    task_id = args.id or f"T-{args.from_pool}"
    members = "".join(
        f'\n[[member]]\nid = {json.dumps(r["id"])}\nlayer = {_toml_str(r["layer"])}\n'
        f'what = {_toml_str(r["what"])}\n'
        f'paths = {json.dumps(r.get("files") or [], ensure_ascii=False)}\n'
        for r in rows)
    text = (f"id = {json.dumps(task_id)}\n"
            f"why = {_toml_str(args.why or f'{args.from_pool} 这一层的活一次收口')}\n"
            + (f"deadline = {json.dumps(args.deadline)}\n" if args.deadline else "")
            + (f"gate_cmd = {json.dumps(args.gate_cmd)}\n" if args.gate_cmd else "")
            + f"on_complete = {json.dumps(args.on_complete)}\n" + members)
    src = batch_dir() / f".{task_id}.from-pool.toml"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(text, encoding="utf-8", newline="\n")
    print(f"从待办登记成任务：{len(rows)} 张卡 → {task_id}")
    rc = cmd_register(argparse.Namespace(manifest=str(src), force=args.force))
    if rc == 0:
        with spin_lock(pool_path()):
            used = {r["id"] for r in rows}
            _save_pool([r for r in _load_pool() if r.get("id") not in used])
        print(f"  （这 {len(rows)} 条已从待办表划掉，避免重复成任务）")
    with contextlib.suppress(OSError):
        src.unlink()
    return rc


# ================================================================ 自证（反例钉子）


def selftest() -> int:
    """反例钉子：每条守卫都要有一个"它确实会咬"的例子，否则等于没有守卫。"""
    import io
    import tempfile

    checks: list[tuple[str, bool, str]] = []

    def nail(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    def run_cap(*argv: str) -> tuple[int, str]:
        """跑一条命令并**连人看到的报错一起收**（守卫咬人时 `main` 兜底成 rc=2 + stderr）。"""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main([*argv])
        return rc, err.getvalue()

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TF_BATCH_DIR"] = tmp
        root = Path(tmp)
        # ★ 源预声明放 `src/` 子目录，**不要**直接放批目录 —— 否则"有没有落半截任务"这条自证
        #   会被源文件自己撞成假阳性（自证时咬过一次）。
        (root / "src").mkdir()

        def write_man(name: str, body: str) -> Path:
            path = root / "src" / name
            path.write_text(body, encoding="utf-8", newline="\n")
            return path

        man = write_man("T-1.toml", (
            'id = "T-1"\n'
            'why = "自证用：审美层 + 后端一次收口"\n'
            'gate_cmd = "exit 0"\non_complete = ["gate", "draft"]\n'
            '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["tools/a/*"]\n'
            '\n[[member]]\nid = "卡B"\nlayer = "后端"\nwhat = "乙"\npaths = ["tools/b/*"]\n'
            '\n[[member]]\nid = "卡C"\nlayer = "审美层"\nwhat = "丙"\npaths = ["ui/*"]\n'))

        rc = run_cap("register", str(man))[0]
        nail("register 注册任务成功", rc == 0, f"rc={rc}")
        st = read_json(root / "T-1.json")
        nail("★ 放行判据记成『全部成送申请』而不是数量", st["need"] == 3 and "claims" in st,
             f"need={st['need']}")
        nail("层从成员里推出来", st["layers"] == ["后端", "审美层"], str(st["layers"]))

        rc, err = run_cap("claim", "T-1", "卡A", "--evidence", "pytest 3 passed", "--files",
                          "tools/a/x.py", "--why", "甲好了")
        st = read_json(root / "T-1.json")
        nail("第 1 张卡交申请 ⇒ 仍是 collecting（不提前放行）",
             rc == 0 and st["state"] == "collecting", f"state={st['state']}")
        nail("还缺 B、C", _missing(st) == "卡B、卡C", _missing(st))

        rc, err = run_cap("claim", "T-1", "卡A", "--evidence", "pytest 3 passed",
                          "--files", "tools/a/x.py", "--why", "甲又更新了")
        st = read_json(root / "T-1.json")
        nail("重复交申请幂等（计数不涨）", len(_ok(st)) == 1, str(_ok(st)))

        rc, err = run_cap("claim", "T-1", "卡A", "--evidence", "x", "--files", "docs/别的.md")
        nail("★ 逐卡域越界必须拒收（rc=2 + 点名到文件 + 指出这张卡的域）",
             rc == 2 and "自己域外" in err and "docs/别的.md" in err, f"rc={rc} err={err.strip()}")
        nail("★ 越界那次**没覆盖**已收到的申请",
             read_json(root / "T-1.d" / "卡A.json")["why"] == "甲又更新了")

        rc, err = run_cap("claim", "T-1", "卡Z", "--evidence", "夹带", "--files", "tools/a/x.py")
        nail("★ 名单外的申请不算数", rc == 2 and "不在这个任务的名单里" in err,
             f"rc={rc} err={err.strip()}")

        rc, err = run_cap("claim", "T-1", "卡B", "--files", "tools/b/x.py", "--why", "乙好了")
        nail("★ 成功申请**必须带证据**（没证据 rc=2）",
             rc == 2 and "必须带证据" in err, f"rc={rc} err={err.strip()}")

        # ---- "不通过"必须挡住收口 ----
        rc, err = run_cap("claim", "T-1", "卡B", "--claim", "failed", "--why", "乙那件事黄了")
        st = read_json(root / "T-1.json")
        nail("投『不通过』不进成功数", _ok(st) == {"卡A"}, str(_ok(st)))
        rc, err = run_cap("claim", "T-1", "卡C", "--evidence", "ui 三张图都过", "--files", "ui/c.png")
        st = read_json(root / "T-1.json")
        nail("★ 名单都投过了、但有一张『不通过』⇒ **仍然不放行**",
             rc == 3 and st["state"] == "collecting", f"rc={rc} state={st['state']}")
        nail("不通过挡住的理由写进 history",
             any("不通过" in row["note"] for row in st["history"]))

        rc, err = run_cap("claim", "T-1", "卡B", "--evidence", "重做后 pytest 5 passed",
                          "--files", "tools/b/x.py", "--why", "乙重做完了")
        st = read_json(root / "T-1.json")
        nail("★ 重投成功申请 ⇒ 集齐当场放行（awaiting-commit）",
             rc == 0 and st["state"] == "awaiting-commit", f"rc={rc} state={st['state']}")
        nail("门禁读数进状态（green）", (st.get("gate") or {}).get("verdict") == "green",
             str(st.get("gate")))
        draft = root / "T-1.draft.md"
        text = draft.read_text(encoding="utf-8") if draft.exists() else ""
        nail("文书骨架自动生成且**按层分组**", "### 层：后端" in text and "### 层：审美层" in text)
        nail("骨架里带上乙的证据", "乙重做完了" in text)
        nail("状态变化全进 history",
             any("集齐全部成送申请" in row["note"] for row in st["history"]))

        # ---- 骨架可重算 + 人写的东西不被冲掉 ----
        why = root / "T-1.why.md"
        nail("人手补的『为什么』文件被建出来（单独一份）", why.exists())
        why.write_text("我人写的：为什么这三张卡一起收", encoding="utf-8", newline="\n")
        rc = run_cap("claim", "T-1", "卡A", "--evidence", "pytest 4 passed", "--files",
                     "tools/a/x.py", "--why", "甲再改一句")[0]
        rc = run_cap("advance", "T-1")[0]
        text = draft.read_text(encoding="utf-8")
        nail("★ 申请更新后 advance 能重算骨架", rc == 0 and "甲再改一句" in text, f"rc={rc}")
        nail("★ 重算**不冲掉**人写的 why 文件",
             why.read_text(encoding="utf-8") == "我人写的：为什么这三张卡一起收")
        nail("重算记进 history（写日志）",
             any("重算骨架" in row["note"] for row in read_json(root / "T-1.json")["history"]))

        # ---- 豁免是"不齐也能放行"的唯一合法路径 ----
        man2 = write_man("T-2.toml", (
            'id = "T-2"\nwhy = "豁免自证"\ngate_cmd = "exit 0"\non_complete = ["gate", "draft"]\n'
            '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n'
            '\n[[member]]\nid = "卡B"\nlayer = "后端"\nwhat = "乙"\npaths = ["b/*"]\n'))
        run_cap("register", str(man2))
        run_cap("claim", "T-2", "卡A", "--evidence", "ok", "--files", "a/x.py")
        rc, err = run_cap("waive", "T-2", "卡B", "--reason", "乙那件事用户撤了")
        st2 = read_json(root / "T-2.json")
        nail("★ 豁免后不齐也能放行（留痕）", rc == 0 and st2["state"] == "awaiting-commit",
             f"rc={rc} state={st2['state']}")
        nail("豁免在骨架里写明", "豁免" in (root / "T-2.draft.md").read_text(encoding="utf-8"))

        # ---- 门禁红了 ⇒ 不许提交 ----
        man3 = write_man("T-3.toml", (
            'id = "T-3"\nwhy = "红门禁自证"\ngate_cmd = "exit 1"\non_complete = ["gate", "draft"]\n'
            '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n'))
        run_cap("register", str(man3))
        rc, err = run_cap("claim", "T-3", "卡A", "--evidence", "ok", "--files", "a/x.py")
        st3 = read_json(root / "T-3.json")
        nail("★ 门禁红 ⇒ 停在 ready 不提交且非零退出", rc == 3 and st3["state"] == "ready",
             f"rc={rc} state={st3['state']}")

        # ---- 过期判死绝不放行 ----
        man4 = write_man("T-4.toml", (
            'id = "T-4"\nwhy = "过期自证"\n'
            '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n'
            '\n[[member]]\nid = "卡B"\nlayer = "后端"\nwhat = "乙"\npaths = ["b/*"]\n'))
        run_cap("register", str(man4))
        run_cap("claim", "T-4", "卡A", "--evidence", "ok", "--files", "a/x.py")
        run_cap("expire", "T-4")
        st4 = read_json(root / "T-4.json")
        nail("★ 过期只判死不放行", st4["state"] == "timeout", st4["state"])

        # ---- 预声明不合法 ⇒ 不落盘 ----
        man5 = write_man("T-5.toml", 'id = "T-5"\nwhy = "缺 layer"\n'
                                     '\n[[member]]\nid = "卡A"\nwhat = "甲"\npaths = ["a/*"]\n')
        rc, err = run_cap("register", str(man5))
        nail("缺 layer 必须报错（rc=2）", rc == 2 and "layer" in err, f"rc={rc} err={err.strip()}")
        nail("★ 预声明没验过就**不落盘**（不留下半截任务）",
             not (root / "T-5.toml").exists() and not (root / "T-5.json").exists())
        man6 = write_man("T-6.toml", 'id = "T-6"\nwhy = "缺 paths"\n'
                                     '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\n')
        rc, err = run_cap("register", str(man6))
        nail("缺 paths（这张卡的域）必须报错", rc == 2 and "paths" in err,
             f"rc={rc} err={err.strip()}")

        # ---- 待办登记 → 成任务 ----
        run_cap("pool", "add", "--layer", "前端", "--what", "甲", "--files", "web/a.ts")
        run_cap("pool", "add", "--layer", "前端", "--what", "乙", "--files", "web/b.ts")
        run_cap("pool", "add", "--layer", "后端", "--what", "丙", "--files", "srv/c.py")
        rc, err = run_cap("register", "--from-pool", "前端", "--id", "T-P1")
        stp = read_json(root / "T-P1.json")
        nail("★ 按层把待办登记收成成员", rc == 0 and stp["declared"] == ["P-1", "P-2"],
             f"rc={rc} declared={stp['declared']}")
        nail("★ 成任务后从待办表划掉（不重复收）",
             [r["id"] for r in _load_pool()] == ["P-3"],
             str([r["id"] for r in _load_pool()]))
        rc, err = run_cap("register", "--from-pool", "空层", "--id", "T-P9")
        nail("空层成任务必须报错（rc=2）", rc == 2 and "一条登记都没有" in err,
             f"rc={rc} err={err.strip()}")

        # ---- 新机器第一次用：目录还不存在 ----
        fresh = root / "fresh" / "batch"
        old = os.environ["TF_BATCH_DIR"]
        os.environ["TF_BATCH_DIR"] = str(fresh)
        try:
            rc, err = run_cap("pool", "add", "--layer", "后端", "--what", "w", "--files", "x.py")
            nail("★ 目录**不存在**时也能登记（自己把目录建出来）",
                 rc == 0 and (fresh / "pool.json").exists(), f"rc={rc} err={err.strip()}")
        finally:
            os.environ["TF_BATCH_DIR"] = old

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  {'✓' if ok else '✗'} {name}" + (f"   [{detail}]" if detail and not ok else ""))
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 条钉子通过")
    return 1 if bad else 0


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # ★ `--selftest` 要在解析前截住：子命令是 required，直接交给 argparse 会先报"缺子命令"。
    if "--selftest" in argv:
        return selftest()
    parser = argparse.ArgumentParser(
        prog="tf_batch", description="任务栅栏：注册任务 → 各卡交成送申请 → 集齐才收口")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register", help="★ 注册任务（预声明它需要哪些卡 / 每张卡属于哪层 / 各自域）")
    p.add_argument("manifest", nargs="?", help="预声明 TOML 的路径（用 --from-pool 时不用给）")
    p.add_argument("--force", action="store_true", help="覆盖已存在的任务")
    p.add_argument("--from-pool", metavar="层", help="把该层的待办登记收成成员（预声明由机器生成）")
    p.add_argument("--max", type=int, help="从待办表最多收几条")
    p.add_argument("--id", help="任务号（默认 T-<层>）")
    p.add_argument("--why", default="", help="这个任务要干成什么")
    p.add_argument("--gate-cmd", help="集齐后自动跑的门禁命令（不给 = 跳过门禁）")
    p.add_argument("--deadline", help="期限（ISO）")
    p.add_argument("--on-complete", nargs="+", default=["gate", "draft"],
                   help="集齐后自动做什么（只认 `gate` / `draft`；**没有 commit**）")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("claim", help="★ 一张卡交成送申请（成功必须带证据）")
    p.add_argument("task")
    p.add_argument("member")
    p.add_argument("--claim", default="success", choices=["success", "failed"],
                   help="`success`（成送申请）/ `failed`（不通过 ⇒ 挡住收口）")
    p.add_argument("--evidence", default="", help="★ 成功申请必填：测试读数 / 门禁结论 / 原样输出")
    p.add_argument("--files", default="", help="碰过的文件，逗号分隔（**要过这张卡自己的域检查**）")
    p.add_argument("--why", default="", help="这张卡干了什么（会进文书骨架）")
    p.add_argument("--log", default="", help="日志路径")
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("deposit", help="（`claim` 的旧名，等价）")
    p.add_argument("task")
    p.add_argument("member")
    p.add_argument("--claim", default="success", choices=["success", "failed"])
    p.add_argument("--evidence", default="")
    p.add_argument("--files", default="")
    p.add_argument("--why", default="")
    p.add_argument("--log", default="")
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("waive", help="★ 显式豁免某张卡（不齐也能放行，但留痕）")
    p.add_argument("task")
    p.add_argument("member")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_waive)

    p = sub.add_parser("extend", help="续期")
    p.add_argument("task")
    p.add_argument("--to", required=True)
    p.set_defaults(func=cmd_extend)

    p = sub.add_parser("expire", help="★ 到期判死：只列缺席，绝不放行")
    p.add_argument("task")
    p.set_defaults(func=cmd_expire)

    p = sub.add_parser("advance", help="手动推一次（幂等；也用来重算骨架）")
    p.add_argument("task")
    p.set_defaults(func=cmd_advance)

    p = sub.add_parser("landed", help="标成已收口提交（要人显式标）")
    p.add_argument("task")
    p.add_argument("--commit", required=True)
    p.set_defaults(func=cmd_landed)

    p = sub.add_parser("status", help="一屏：哪张卡交了 / 还缺谁 / history")
    p.add_argument("task")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("list", help="所有任务")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("pool", help="还没定卡的活先按层登记（可选）")
    p.add_argument("action", choices=["add", "list", "drop"])
    p.add_argument("--id")
    p.add_argument("--layer")
    p.add_argument("--what")
    p.add_argument("--files", default="")
    p.set_defaults(func=cmd_pool)

    args = parser.parse_args(argv)
    try:
        if getattr(args, "from_pool", None) and args.cmd == "register":
            return _register_from_pool(args)
        return int(args.func(args))
    except (BatchError, RefuseError) as exc:
        print(f"✗ {type(exc).__name__}：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
