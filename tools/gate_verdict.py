r"""三把尺子共用的一条判据（卡 E63 / T-AG521）：**「通过」不许在空集上成立**。

## 病

本仓对同一份门禁产物（`gates/last.json`）有三种判法：

- 本地 `scripts/run_gates.py:gates_ok()` —— `all(阻断门 exit_code == 0)`；
- 云机 `tools/gate_pool.py:validate_cloud_return()` —— 门名对账 + `not_run` 判红；
- 落地链 `tools/pool/landing.py` ④/⑤ —— 只看子进程 rc。

`all()` 在空表上返 `True` 是**数学性质，不是判据** —— 于是「一道门都没跑」时
`gates_ok([]) == True`：整趟退 0、`ok=True`，而同一份 payload 的 `not_run` 还写着
「未验证」—— 产物自己跟自己矛盾。卡 E62 就是这么落的卡：`gates/last.json` 里
`render` 是 `exit=3 / status=NOT RUN`、`not_run=['render']`，而 `ok=True`。

## 治

判据只留一份，就在这里；三处都调 `judge()`，谁也不许自己下定义：

1. **零门**（一条 gate 记录都没有）⇒ 红；
2. **零阻断门**（有记录，但全是 NOT RUN / 信息性门）⇒ 未验证 ⇒ 红；
3. `not_run` 里有门（`OPTIONAL_DOORS` 里显式标了可缺省的除外）⇒ 未验证 ⇒ 红；
4. `reused: true` 的条目追溯不到来源宿主，或来源宿主不等于这份产物的宿主 ⇒ 红；
5. 这份产物没有 `host`（判不出来是哪台机器跑的）⇒ 红。要看「必须是某台」传
   `expect_host`，要看「不许是某台」传 `not_host`。
6. **未声明的排除**（`status=EXCLUDED` 但不在 `GOLDEN_PINNED` 里 / 理由空 /
   同时标了 blocking）⇒ 红：排除是豁免，不是「跑过了」。

## 不做（写清楚，免得下次又长出第二把尺子）

- **不看 `payload["ok"]`** —— 它就是本条判据的**结果**；拿结果当输入等于自己证明自己；
- **不数阻断门的退出码** —— 那是「这道门红了没」的问题，归本地尺子 `gates_ok()`
  与云机尺子的 pytest 判据；本模块只管「这份产物能不能算**跑过了**」；
- **不判 `not_run` 里那些门的具体退出码** —— 那不是「有没有跑」的问题。

## 反向验证（卡 E63 判据 5 要求）

`tests/test_no_vacuous_pass.py` 逐条把这五条钉住，并且每条都有「把产品改回老写法 ⇒
钉子必红」的实测记录（见卡规格 §反向验证）。
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 只为类型标注
    from collections.abc import Iterable

#: 本判据的出生卡（写进产物，便于反查口径从哪来）
CARD = "E63 / T-AG521"

#: 门名 -> 「为什么可以缺省」。**空 = 一道都不许缺**：要写进来必须给理由。
OPTIONAL_DOORS: dict[str, str] = {}

#: 金样本主机专用门：门名 -> 采集记录的相对路径。
#:
#: ★ 为什么表要在这里：`EXCLUDED` 是一条**豁免**，谁拿表谁就掌握了「哪些门可以不算红」。
#:   三把尺子（本地 / 号池 / 落地链）必须拿**同一张表**，否则又会长出第二把尺子。
#:   要加门必须同时改卡规格、本表与 `tests/test_gates_ok_vacuous.py` —— 让它是一次显式决定。
GOLDEN_PINNED: dict[str, str] = {"render": "gates/render/CAPTURED_ON.json"}

GREEN = "green"
UNVERIFIED = "unverified"
RED = "red"

_PROV = "来源不明"


def local_host() -> str:
    """本机的宿主名（`socket.gethostname()`，比对时统一小写去空白）。"""
    try:
        return socket.gethostname()
    except OSError:  # 罕见：容器里 gethostname 会抛
        return ""


def _norm_host(raw: Any) -> str:
    return str(raw or "").strip().lower()


def payload_host(payload: Any) -> str:
    """产物自己声明的宿主。缺失/空 ⇒ `""`（判不出来源）。"""
    return _norm_host(payload.get("host")) if isinstance(payload, dict) else ""


def gate_rows(payload: Any) -> list[dict[str, Any]]:
    """`payload["gates"]` 里合法的行（非 dict 的条目丢掉，不当证据）。"""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("gates")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def blocking_rows(payload: Any) -> list[dict[str, Any]]:
    """阻断门行（`blocking` 缺省按 `True` 算 —— 老产物没有这个字段）。"""
    return [r for r in gate_rows(payload) if r.get("blocking", True)]


def row_names(rows: Iterable[dict[str, Any]]) -> list[str]:
    return [str(r.get("name") or "?") for r in rows]


def not_run_list(payload: Any) -> list[str]:
    """`not_run` 规范化成字符串列表（非 list 的真值 ⇒ 当成「有门没跑」，不静默吞掉）。"""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("not_run")
    if raw is None or raw is False:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [str(raw)]


def unverified_doors(payload: Any) -> list[str]:
    """`not_run` 里**没有**被门表显式标成可缺省的那些门 —— 它们让整趟不算通过。"""
    return [n for n in not_run_list(payload) if n not in OPTIONAL_DOORS]


def optional_missing(payload: Any) -> list[str]:
    """`not_run` 里被显式标了可缺省的门（产物里要留痕，但不判红）。"""
    return [n for n in not_run_list(payload) if n in OPTIONAL_DOORS]


# --------------------------------------------------------------------- 五条判据
def zero_door_problem(payload: Any) -> str | None:
    """① 零门：一条 gate 记录都没有 ⇒ 红（`all([]) == True` 就是这一条的病灶）。"""
    rows = gate_rows(payload)
    if rows:
        return None
    return "零门：一份 gate 记录都没有（一道门都没跑 ⇒ 什么都没证明，不许当通过）"


def no_blocking_problem(payload: Any) -> str | None:
    """② 零阻断门：有记录，但全是 NOT RUN / 信息性门 ⇒ 未验证。"""
    rows = gate_rows(payload)
    if not rows:
        return None  # 零门由 ① 报，别报两遍
    if blocking_rows(payload):
        return None
    return (
        f"零阻断门：{len(rows)} 条记录里没有一条阻断门（全是 NOT RUN / 信息性门 ⇒ 未验证 ≠ 通过）"
    )


def not_run_problem(payload: Any) -> str | None:
    """③ `not_run` 非空 ⇒ 整趟不许 ok=True（除非门表显式标了可缺省）。"""
    bad = unverified_doors(payload)
    if not bad:
        return None
    return f"有门 not_run（未验证 ≠ 通过）：{bad}"


def red_door_problems(payload: Any) -> list[str]:
    """阻断门里**真红**的那些（有 `exit_code` 键且非 0）。

    ★ 缺 `exit_code` 键的行**不在这里判红**，但也不放行 —— 交给
      `missing_exit_code_problems()` 判成「未验证」。分界是：**说了数字就按数字判
      （非零即红），没说就记未验证**；「没写」既不等于绿、也不必冒充红。
    """
    out: list[str] = []
    for row in blocking_rows(payload):
        if "exit_code" not in row:
            continue
        code = row.get("exit_code")
        try:
            bad = int(str(code)) != 0
        except (TypeError, ValueError):
            bad = True  # 读不懂的退出码 ⇒ 当红（fail closed）
        if bad:
            out.append(f"{row.get('name')}(exit={code})")
    return out


def missing_exit_code_problems(payload: Any) -> list[str]:
    """阻断门**没写** `exit_code`：未声明 ≠ 跑过 ⇒ 未验证。

    ★ 这条是 2026-10-28 对抗复核查出来的洞（卡 E63 复核）：`red_door_problems()` 遇到
      缺 `exit_code` 的行是 `continue`，于是「只写了门名、没写退出码」的产物一路判绿。
      原来的理由（老夹具只写门名）不成立 —— 那种产物**本来就拿不出跑过的证据**，
      正确结论是「未验证」，不是「通过」，也不是「红」。红留给「写了数字且非零」。
    """
    out: list[str] = []
    for row in blocking_rows(payload):
        if "exit_code" not in row:
            out.append(f"{row.get('name')}(没写 exit_code)")
    return out


def not_run_row_problems(payload: Any) -> list[str]:
    """④′ 门行自己写着「没验证」：`status == "NOT RUN"` 或 `exit_code == 3`。

    ★ 这条是**现网真数据**里挖出来的（卡 E63 判据 4 前半）：`gates/last.json` 里
      `web_live` 是 `exit_code=3 / blocking=False / status='NOT RUN'`、自己的 note 写着
      「这一层没有验证，不算通过」，而 `not_run` 是 `['render']` —— **它不在里面**。
      「有没有验证」被 `not_run` 与 `gates[].status` 两个字段各记一半，于是三个复核口
      全放行了它。所以这里直接看门行，不再只信 `not_run`。
    """
    out: list[str] = []
    for row in gate_rows(payload):
        status = str(row.get("status") or "").strip().upper()
        code = row.get("exit_code")
        try:
            is_three = int(str(code)) == 3
        except (TypeError, ValueError):
            is_three = False
        if status == "NOT RUN" or is_three:
            out.append(f"{row.get('name')}(status={status or '-'}, exit={code})")
    return out


def reused_problems(payload: Any) -> list[str]:
    """④ 跨机复用不许冒充本机真跑：`reused: true` 必须能追到来源宿主，且等于本产物宿主。"""
    out: list[str] = []
    host = payload_host(payload)
    for row in gate_rows(payload):
        if not row.get("reused"):
            continue
        name = str(row.get("name") or "?")
        src = _norm_host(row.get("host"))
        if not src:
            out.append(
                f"复用来源不明：门 {name} 标了 reused=true 但条目里没有 host"
                "（判不出这条判定是哪台机器做的 ⇒ 不许算通过）"
            )
            continue
        if not host:
            out.append(
                f"复用来源不明：门 {name} 的来源宿主是 {src}，但产物自己没有 host"
                "（判不出这份产物是哪台机器跑的 ⇒ 不许算通过）"
            )
            continue
        if src != host:
            out.append(
                f"跨机冒充：门 {name} 的判定来自 {src}，这份产物来自 {host}"
                "（别的宿主上的结论不算本机真跑）"
            )
    return out


def host_problems(
    payload: Any, *, expect_host: str | None = None, not_host: str | None = None
) -> list[str]:
    """⑤ 这份产物是哪台机器跑的：判不出来就红（fail closed）。"""
    out: list[str] = []
    host = payload_host(payload)
    declared = payload.get("host") if isinstance(payload, dict) else None
    if not host:
        out.append(f"{_PROV}：产物没有 host 字段（证明不了是哪台机器跑的 ⇒ 不许算通过）")
        return out
    if expect_host is not None and host != _norm_host(expect_host):
        out.append(f"{_PROV}：产物 host={declared!r}，要求是 {expect_host!r}")
    if not_host is not None and host == _norm_host(not_host):
        out.append(
            f"{_PROV}：产物 host={declared!r} 就是本机（{not_host!r}）"
            "⇒ 这不是别处跑的读数，不许冒充"
        )
    return out


def excluded_row_problems(payload: Any) -> list[str]:
    """⑥ 排除是**豁免**，不是「跑过了」：只许声明过的门、且必须能念给人听。

    ★ 这条是卡 E63 判据 6。没有它，任何门都能自报 `status="EXCLUDED"` 把红洗成绿 ——
      而 `blocking=False` + `exit_code=0` 的形状恰好能骗过「按退出码判红」的所有老尺子。
    ★ 排除还必须**不伪装成通过**：`exit_code` 非 0 或 `blocking=True` 的 EXCLUDED 行是
      「既想豁免又想算阻断」的矛盾行 ⇒ 红。
    """
    out: list[str] = []
    for row in gate_rows(payload):
        if str(row.get("status") or "").strip().upper() != "EXCLUDED":
            continue
        name = str(row.get("name") or "?")
        if name not in GOLDEN_PINNED:
            out.append(
                f"门 {name} 自报按设计排除，但它不在金样本主机专用门清单里 —— 不许自报豁免"
            )
            continue
        if not str(row.get("excluded_reason") or "").strip():
            out.append(f"门 {name} 被排除但没写理由 —— 排除必须能念给人听")
        if row.get("blocking", True):
            out.append(f"门 {name} 既标了 EXCLUDED 又标 blocking=true —— 一条行不许两副面孔")
        try:
            if int(str(row.get("exit_code"))) != 0:
                out.append(f"门 {name} 标了 EXCLUDED 却带着非零退出码 {row.get('exit_code')}")
        except (TypeError, ValueError):
            continue
    return out


def judge(
    payload: Any,
    *,
    expect_host: str | None = None,
    not_host: str | None = None,
    check_host: bool = True,
) -> Verdict:
    """一条判据，三种尺子共用。`ok=False` 时 `problems` 至少一条（不许空口判红）。

    `check_host=False` 只给「自己已经另有一套更严的来源检查」的调用方用 —— 眼下是云机尺子
    （`tools/gate_pool.py:validate_cloud_return` 的 ③：要求 `host` 非空且等于指定云机）。
    **别拿它当放宽**：`reused` 条目的来源（判据 4）无论它开不开都照判。
    """
    unverified: list[str] = []
    red: list[str] = []
    bad_doors = red_door_problems(payload)
    if bad_doors:
        red.append(f"阻断门没绿：{bad_doors}")
    for one in (zero_door_problem(payload), no_blocking_problem(payload), not_run_problem(payload)):
        if one:
            unverified.append(one)
    rows_not_run = not_run_row_problems(payload)
    if rows_not_run:
        unverified.append(f"门行自己写着未验证（status=NOT RUN / exit=3）：{rows_not_run}")
    rows_no_code = missing_exit_code_problems(payload)
    if rows_no_code:
        unverified.append(f"阻断门没写 exit_code（未声明 ≠ 跑过）：{rows_no_code}")
    red += reused_problems(payload)
    red += excluded_row_problems(payload)
    if check_host:
        red += host_problems(payload, expect_host=expect_host, not_host=not_host)
    problems = red + unverified
    if not problems:
        return Verdict(ok=True, state=GREEN, problems=())
    return Verdict(ok=False, state=(RED if red else UNVERIFIED), problems=tuple(problems))


@dataclass(frozen=True)
class Verdict:
    """一条判定：`ok` + 状态 + 逐条问题（问题必须点名成因，不许只说「红」）。"""

    ok: bool
    state: str
    problems: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        """落进 `gates/last.json` 的形状（键名固定，便于跨机对账）。"""
        return {
            "ok": self.ok,
            "state": self.state,
            "problems": list(self.problems),
            "card": CARD,
        }

    def line(self) -> str:
        """一句话给人看（终端/日志用）。"""
        if self.ok:
            return f"[绿] 通过（{CARD}）"
        return f"[{'红' if self.state == RED else '未验证'}] " + "；".join(self.problems)


def judge_text(text: str, **kw: Any) -> Verdict:
    """从 JSON 文本判（产物读不懂 ⇒ 红，别猜）。"""
    import json as _json

    try:
        payload = _json.loads(text)
    except (TypeError, ValueError) as exc:
        return Verdict(ok=False, state=RED, problems=(f"产物读不懂：{exc}",))
    if not isinstance(payload, dict):
        return Verdict(ok=False, state=RED, problems=(f"产物不是对象：{type(payload).__name__}",))
    return judge(payload, **kw)
