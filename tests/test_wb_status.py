"""WorkBuddy 状态器（`tools/wb_status.py`，T-G81）的测试 —— 给"看工人的窗"上护栏。

为什么要有测试：这个工具的**输入是别的进程吐出来的 JSONL**，而那个进程会升级、会换事件形状。
它最容易得的病有两种，两种都已经被钉住：
  · **认不出来就静默丢掉** → 状态器说"什么也没干"，而工人其实干了一堆（比没有窗更坏）；
  · **长输出原样刷屏**（工具回话里可能是几万字的文件内容）→ 真正的动作被淹掉。

零件层喂合成事件；CLI 层验 `--tail` / `--json` / 文件不存在这三条路。
★ 形状目前按 CodeBuddy/Claude-Code 那一族写 —— **第一次真派活之后要用真 log 复钉**（本文件头一句
就是记这件事，别让它漂）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_status as ws  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _event(**kwargs: object) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _assistant(*items: dict) -> str:
    return _event(type="assistant", message={"content": list(items)})


def _lines() -> list[str]:
    return [
        _event(type="system", subtype="init", model="deepseek-v3-2-volc",
               tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"]),
        _assistant({"type": "text", "text": "我先读一遍交接文档，再决定动哪里。"}),
        _assistant({"type": "tool_use", "name": "Bash",
                    "input": {"command": "git status --short"}}),
        _event(type="user", message={"content": [
            {"type": "tool_result", "content": "M src/timeflow/api/app.py"}]}),
        _assistant({"type": "tool_use", "name": "Edit",
                    "input": {"file_path": "src/timeflow/core/tasks/manager.py",
                              "old_string": "a"}}),
        _event(type="user", message={"content": [
            {"type": "tool_result", "content": "编辑失败：找不到那段", "is_error": True}]}),
        _event(type="result", subtype="success", result="改完了，门禁全绿"),
    ]


# ------------------------------------------------------------------ 零件层


def test_timeline_shows_model_tools_and_what_it_touched() -> None:
    """一行事件 → 一行人话：模型、工具清单、每个动作动了哪个文件/跑了什么命令。"""
    timeline, summary = ws.parse_events(_lines())
    body = "\n".join(timeline)

    assert "deepseek-v3-2-volc" in body          # 用的是哪个模型
    assert "Grep" in body                        # ★ 它到底有没有 grep，看这一行
    assert "Bash(command=git status --short)" in body
    assert "src/timeflow/core/tasks/manager.py" in body
    assert summary["tool_calls"] == 2
    assert summary["tools"] == {"Bash": 1, "Edit": 1}
    assert summary["texts"] == 1
    assert summary["files"] == ["src/timeflow/core/tasks/manager.py"]
    assert summary["tool_errors"] == 1
    assert summary["final"] == "改完了，门禁全绿"


def test_unknown_event_shapes_are_shown_not_swallowed() -> None:
    """对方升级换了形状 → **原样留一行**，不许静默什么都不说（比没有窗更坏）。"""
    timeline, summary = ws.parse_events([_event(type="brand_new_thing", foo=1)])
    assert "brand_new_thing" in timeline[0]
    assert summary["unknown_events"] == 1


def test_broken_json_line_does_not_crash() -> None:
    """半行 / 非 JSON（进程被 kill 时很常见）→ 记一句，继续读完整个文件。"""
    ok = _event(type="result", subtype="success", result="ok")
    timeline, summary = ws.parse_events(["这不是 JSON", ok])
    assert "非 JSON 行" in timeline[0]
    assert summary["unknown_events"] == 1
    assert summary["final"] == "ok"


def test_long_output_is_clipped() -> None:
    """工具回话里可能塞着整个文件 —— 状态器一行最多 240 字，不许刷屏。"""
    big = "x" * 5000
    timeline, _ = ws.parse_events([
        _event(type="user", message={"content": [{"type": "tool_result", "content": big}]}),
    ])
    assert len(timeline[0]) < 400
    assert big not in timeline[0]


def test_non_dict_event_does_not_crash() -> None:
    """一行合法 JSON 但不是对象（比如一个数组）也不许崩。"""
    timeline, summary = ws.parse_events(["[1,2,3]"])
    assert "非对象事件" in timeline[0]
    assert summary["unknown_events"] == 1


# ------- 畸形 `message`（T-G96 边界① / T-G125）：不是 dict 时不许抛、口径确定 -------

_OK_ASSISTANT = _assistant({"type": "tool_use", "name": "Read",
                            "input": {"file_path": "src/a.py"}})


def test_message_is_a_string_does_not_crash() -> None:
    """① `message` 是字符串（畸形 log）→ 记一行认不出，不抛；后面好事件照数。"""
    timeline, summary = ws.parse_events([
        _event(type="assistant", message="字符串"),
        _OK_ASSISTANT,
    ])
    assert "message 不是对象" in "\n".join(timeline)
    assert summary["unknown_events"] == 1
    assert summary["tool_calls"] == 1          # 该数的照数


def test_message_is_a_list_does_not_crash() -> None:
    """② `message` 是列表（畸形 log）→ 同样记一行认不出，不抛。"""
    timeline, summary = ws.parse_events([
        _event(type="user", message=["不是 dict"]),
    ])
    assert "message 不是对象" in "\n".join(timeline)
    assert summary["unknown_events"] == 1


def test_message_none_behaves_like_before() -> None:
    """③ `message` 是 None → 老口径（当空 message 跳过），不许抛、也不算未知。"""
    timeline, summary = ws.parse_events([_event(type="assistant", message=None)])
    assert summary["unknown_events"] == 0
    assert summary["tool_calls"] == 0
    assert summary["texts"] == 0


def test_message_missing_behaves_like_before() -> None:
    """④ 缺 `message` 字段 → 与 None 同口径（跳过），不许抛。"""
    timeline, summary = ws.parse_events([_event(type="assistant")])
    assert summary["unknown_events"] == 0
    assert summary["tool_calls"] == 0
    assert summary["texts"] == 0


# ------------------------------------------------------------------ CLI 层


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "wb.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_tail_shows_only_the_last_events(tmp_path: Path, monkeypatch, capsys) -> None:
    """跑长任务时看进度：`--tail` 只印最后几条（第一条发言不该出现）。"""
    path = _write(tmp_path, _lines())
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(path), "--tail", "2"])
    assert ws.main() == 0
    out = capsys.readouterr().out
    assert "改完了，门禁全绿" in out
    assert "我先读一遍交接文档" not in out


def test_json_summary_is_machine_readable(tmp_path: Path, monkeypatch, capsys) -> None:
    """主控要拿它做判断 → `--json` 必须是能解析的摘要。"""
    path = _write(tmp_path, _lines())
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(path), "--json"])
    assert ws.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool_calls"] == 2
    assert data["final"] == "改完了，门禁全绿"


def test_missing_log_is_a_clean_error(tmp_path: Path, monkeypatch, capsys) -> None:
    """文件不存在 → 退出码 2 + 一句人话，不许抛栈（它常被主控在循环里调）。"""
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(tmp_path / "没有这个.jsonl")])
    assert ws.main() == 2
    assert "找不到 log" in capsys.readouterr().err


# ================================================================== 卡 A318
#
# 模式②：派生卡状态（不给 log 参数）+ 两条事故钉子（台账缺条目 ⇒ 拒落 / 对账红）。
# 口径：状态从 git 派生（Task trailer / 批次围栏），台账只存计划。

import subprocess  # noqa: E402

import wb_land  # noqa: E402
import wb_reconcile  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def _derive_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    return root


def _ledger(root: Path, *cards: tuple[str, str]) -> None:
    """写一份最小台账（只有计划字段：id / task —— 没有 status，那字段退役了）。"""
    (root / "docs").mkdir(exist_ok=True)
    body = "".join(f'[[cards]]\nid = "{cid}"\ntask = "{task}"\n' for cid, task in cards)
    (root / "docs" / "workbacklog.toml").write_text(body, encoding="utf-8")


def _commit(root: Path, subject: str, task: str | None = None) -> None:
    args = ["commit", "-q", "--allow-empty", "-m", subject]
    if task:
        args += ["-m", f"Task: {task}"]
    _git(root, *args)


def _batch(root: Path, name: str, state: str, declared: list[str]) -> None:
    d = root / "gates" / "diag" / "batch"
    d.mkdir(parents=True, exist_ok=True)
    body = {"id": name, "state": state, "declared": declared,
            "landed": {"commit": ""}}
    (d / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


def _row(rows: list[dict], cid: str) -> dict:
    return next(r for r in rows if r["id"] == cid)


def test_derive_done_from_task_trailer(tmp_path: Path) -> None:
    """有 `Task: <task>` trailer 的提交 ⇒ done（卡规格判据第一条）。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"), ("A2", "T-Z2"))
    _commit(root, "feat: 落了", task="T-Z1")
    rows, _ = ws.derive_status(root)
    assert _row(rows, "A1")["status"] == "done"
    assert "commit" in _row(rows, "A1")["via"]
    assert _row(rows, "A2")["status"] == "pending"


def test_derive_from_batch_fence(tmp_path: Path) -> None:
    """批次围栏：landed ⇒ done；awaiting-commit ⇒ awaiting-commit；collecting 不算。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"), ("A2", "T-Z2"), ("A3", "T-Z3"))
    _batch(root, "B-L", "landed", ["A1"])
    _batch(root, "B-A", "awaiting-commit", ["A2"])
    _batch(root, "B-C", "collecting", ["A3"])
    rows, _ = ws.derive_status(root)
    assert _row(rows, "A1")["status"] == "done"
    assert _row(rows, "A2")["status"] == "awaiting-commit"
    assert _row(rows, "A3")["status"] == "pending"


def test_derive_body_mention_is_not_done(tmp_path: Path) -> None:
    """正文里**提到**任务号（不是 trailer 整行）⇒ 不算落地（卡 146 假阳的封口）。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"))
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: x",
         "-m", "复盘里提到 T-Z1 这张卡")
    rows, _ = ws.derive_status(root)
    assert _row(rows, "A1")["status"] == "pending"


def test_derived_json_cli_summary(tmp_path: Path, capsys) -> None:
    """`wb_status.py --json`（无 log 参数）⇒ 机器可读摘要，含 done 数与 git 号数。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"), ("A2", "T-Z2"))
    _commit(root, "feat: 落了", task="T-Z1")
    assert ws.main(["--root", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["done"] == 1
    assert data["summary"]["pending"] == 1
    assert data["summary"]["tasks_in_git"] == 1
    assert _row(data["cards"], "A1")["status"] == "done"


def test_land_refuses_card_missing_from_ledger(tmp_path: Path, capsys) -> None:
    """钉子①：台账缺 A999 条目 ⇒ `wb_land --card A999` 拒落退非零（一步不跑）。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"))
    rc = wb_land.guard_card_in_ledger(["--card", "A999", "--tree", "."], cwd=root)
    assert rc != 0
    assert "A999" in capsys.readouterr().err


def test_land_guard_passes_registered_card_and_sandbox(tmp_path: Path) -> None:
    """守卫的放行面：① 卡已登记 ⇒ 过；② 树里没台账（假仓/沙箱）⇒ 打印跳过、过。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"))
    assert wb_land.guard_card_in_ledger(["--card", "A1", "--tree", "."], cwd=root) == 0
    empty = tmp_path / "empty"
    empty.mkdir()
    assert wb_land.guard_card_in_ledger(["--card", "A999"], cwd=empty) == 0


def test_reconcile_red_on_orphan_task_commit(tmp_path: Path, capsys) -> None:
    """钉子②：提交挂了 `Task: T-A999` 而台账没有该任务 ⇒ wb_reconcile 红（退 1）。"""
    root = _derive_repo(tmp_path)
    _ledger(root, ("A1", "T-Z1"))
    _commit(root, "feat: 落了但没登记", task="T-A999")
    assert wb_reconcile.main(["--root", str(root)]) == 1
    assert "T-A999" in capsys.readouterr().out
    # 补登记之后 ⇒ 同一笔提交不再是孤儿，转绿。
    _ledger(root, ("A1", "T-Z1"), ("A999", "T-A999"))
    assert wb_reconcile.main(["--root", str(root)]) == 0


def test_reconcile_is_fine_when_no_task_mark_yet(tmp_path: Path) -> None:
    """A318：**没 git** 才退 2；有 git 但一笔 `Task:` 都没有是新仓初始态 ⇒ 退 0。"""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "docs").mkdir()
    text = "[[cards]]" + chr(10) + "id = " + chr(39) + "A1" + chr(39)
    text += chr(10) + "task = " + chr(39) + "T-X1" + chr(39) + chr(10)
    (tmp_path / "docs" / "workbacklog.toml").write_text(text, encoding="utf-8")
    assert wb_reconcile.main(["--root", str(tmp_path)]) == 0

