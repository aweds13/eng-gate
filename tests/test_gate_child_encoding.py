"""卡 A337（T-AG539）：钉住「门禁子进程必须按 UTF-8 写，否则症状被编码洗掉」。

## 为什么有这张测试

云机（Windows Server，`locale=cp936`）上 `sys.stdout.encoding` 是 **`gbk`**，而
`scripts/run_gates.py:start_gate()` 按 `encoding="utf-8", errors="replace"` 解码子进程输出
⇒ 子进程写出的 GBK 字节被当成 UTF-8 解 ⇒ 中文全成乱码 ⇒ `SUSPECT_SHAPES`
（`没等到` / `超时` / `timeout` / `timed out` / `等了约`）一条也匹配不上
⇒ `mark_suspect_rows()` 标不上 `SUSPECT`。

实测原文（云门禁 `gates/last.json` 的 `detail` 首行）：
`'[FAIL] û�ȵ���Ӧ������Լ 12 ��'` —— 那是「没等到响应，等了约 12 秒」被 GBK 洗过一遍。

⇒ 判据本身没错，错在**读的一方钉死 utf-8、写的一方却没钉死**。

## 怎么验

- 正向：`env()` 必须同时给出 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8`，
  且**覆盖**外部注入的 `PYTHONIOENCODING=gbk`（`setdefault` 会让外部赢 ⇒ 换台机器修不好）。
- 真路径：注入 `PYTHONIOENCODING=gbk` 后走 `start_gate()` → `finish_gate()` →
  `mark_suspect_rows()`，断 `detail` 里中文完好、`status == "SUSPECT"`。
- 反向自证：把 `env()` 换回旧实现（只走 `tree_pythonpath`），同一条链**必须**乱码 ——
  不然证明不了这层修复有用。

## 边界（如实写，未覆盖）

- 不在真云机上跑（要 SSH + 一门全量）；本机用 `PYTHONIOENCODING=gbk` 复现同一机制。
- 只钉 `env()` 这一处出口；`subprocess` 的 `encoding=` 参数本身不改（写的一方钉死了，
  读的一方按 utf-8 解就是对的）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

#: 现场形状：pytest 把 `FAILED …` 打在最后一行，症状留在更前面那行。
_FAKE_RED = (
    "import sys\n"
    "print('[FAIL] 没等到响应，等了约 12 秒')\n"
    "print('FAILED tests/test_live.py::test_x')\n"
    "sys.exit(1)\n"
)


def _legacy_env() -> dict[str, str]:
    """修前的 `env()`（只走 `tree_pythonpath`）—— 反向自证用它。"""
    import os

    return rg.tree_pythonpath(dict(os.environ))


def _run(envf) -> str:  # type: ignore[no-untyped-def]
    """按 `start_gate()` 的同一套参数起子进程，返回解出来的文本。"""
    import subprocess

    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _FAKE_RED], cwd=rg.ROOT, env=envf(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    out, _ = proc.communicate()
    return out


@pytest.fixture(autouse=True)
def _logs_into_tmp(monkeypatch, tmp_path):
    """假的日志别落进仓库（同 `tests/test_run_gates_timeout.py` 的口径）。"""
    monkeypatch.setattr(rg, "LOG_DIR", tmp_path / "logs")


# ---------------------------------------------------------------- 判据 1：两个变量都给


def test_env_pins_both_utf8_variables(monkeypatch) -> None:
    """★ `env()` 必须同时给 `PYTHONUTF8` 与 `PYTHONIOENCODING`。

    只给 `PYTHONUTF8` 不够：`PYTHONIOENCODING` 的优先级**高于** UTF-8 模式，
    外部环境里已有的 `PYTHONIOENCODING=gbk` 仍会赢。
    """
    # ★ 必须先把宿主环境里的这两个变量摘掉：本机恰好带着 PYTHONIOENCODING=utf-8，
    #   不清掉的话「env() 少写一行」也能靠继承通过 —— 那就成了假钉子（反向验证 ② 咬不住）。
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    e = rg.env()
    assert e.get("PYTHONUTF8") == "1", f"没钉 PYTHONUTF8：{e.get('PYTHONUTF8')!r}"
    assert e.get("PYTHONIOENCODING") == "utf-8", (
        f"没钉 PYTHONIOENCODING：{e.get('PYTHONIOENCODING')!r}"
    )


def test_env_overrides_a_hostile_pythonioencoding(monkeypatch) -> None:
    """★ 外部把 `PYTHONIOENCODING` 设成 `gbk` 时，`env()` 必须**覆盖**它。

    写成 `setdefault` 的话这里会拿到 `gbk` ⇒ 换台机器上复现不了同一份读数。
    """
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    e = rg.env()
    assert e["PYTHONIOENCODING"] == "utf-8", (
        f"外部注入的 gbk 赢了（说明用了 setdefault）：{e['PYTHONIOENCODING']!r}"
    )
    assert e["PYTHONUTF8"] == "1"


def test_env_still_puts_tree_src_first() -> None:
    """加编码不許动 `PYTHONPATH` 那条既有约束（INV-25：本树 src 必须首位）。"""
    import os

    e = rg.env()
    first = e["PYTHONPATH"].split(os.pathsep)[0]
    assert first == str(rg.ROOT / "src"), f"PYTHONPATH 首位不是本树 src，是 {first!r}"


# ---------------------------------------------------------------- 判据 2：真路径上中文完好


def test_child_process_writes_utf8_through_the_real_door(monkeypatch) -> None:
    """★ 注入 `PYTHONIOENCODING=gbk` 后，走真 `start_gate()`/`finish_gate()`，中文必须完好。"""
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    proc, t0, err = rg.start_gate("web_live", [sys.executable, "-c", _FAKE_RED])
    assert proc is not None, f"假门没起起来：{err}"
    row = rg.finish_gate("web_live", proc, t0)
    blob = f"{row.get('summary') or ''}\n{row.get('detail') or ''}"
    assert "没等到响应，等了约 12 秒" in blob, (
        f"中文被编码洗掉了（云机那条红的复现）：{blob[:200]!r}"
    )


def test_suspect_shape_survives_a_gbk_host(monkeypatch) -> None:
    """★ 云机那条红的**正题**：相同现场下 `mark_suspect_rows()` 必须标得出 `SUSPECT`。"""
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    proc, t0, err = rg.start_gate("web_live", [sys.executable, "-c", _FAKE_RED])
    assert proc is not None, f"假门没起起来：{err}"
    row = rg.finish_gate("web_live", proc, t0)
    rows = [row]
    rg.mark_suspect_rows(rows, {"co": "占 cpu 的同行"})
    assert rows[0].get("status") == "SUSPECT", (
        f"没标上 SUSPECT（症状被编码洗掉就是这个样子）：{rows[0]!r}"
    )
    reason = str(rows[0].get("suspect_reason") or "")
    assert "没等到" in reason, f"理由里没写命中的形状：{reason!r}"


# ---------------------------------------------------------------- 判据 3：反向自证


def test_reverse_legacy_env_garbles_the_shape(monkeypatch) -> None:
    """★ 反向钉子：没有这层修复（`env()` 退回旧实现）时，同一现场**必须**乱码。

    先自证前提成立（乱码确实发生），才谈得上「修好了」。这条不依赖平台：
    注入 `PYTHONIOENCODING=gbk` 后，任何平台上的子进程都会按 GBK 写。
    """
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    out = _run(_legacy_env)
    assert "没等到响应" not in out, (
        f"前提不成立：旧 env() 居然没乱码，这条反向钉子证明不了什么：{out[:200]!r}"
    )
    # 乱码了，于是形状匹配不上 —— 这正是云机那条红的机制
    assert not any(s in out for s in rg.SUSPECT_SHAPES), (
        f"旧实现里居然还能命中形状：{out[:200]!r}"
    )
