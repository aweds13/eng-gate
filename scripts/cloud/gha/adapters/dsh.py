"""dsh-superagent-prototype 仓的门禁适配器（GHA 那条腿，卡 E156）。

文件名钉死在 tests/test_windows_autostart_e2e.py：镜像仓 dsh-gate 的 workflow 是冻结的模板，
本 token 没有 workflow scope，最后一步写死 python -m pytest -q tests/test_windows_autostart_e2e.py。

★ 计数只认 vitest 的 JSON reporter，不再从日志尾巴猜。上一版靠 "Tests " / "Test Files "
两行解析，实测在 runner 上恒为 0（卡 E156 的两条实测）：
  1. 那段日志只打了 merged[-25:]，而 vitest 失败时末尾是一长行 ::error file=... 的 GitHub
     annotation，把汇总行挤出 25 行窗口 ⇒ 日志里根本没有可解析的行；
  2. runner 上 vitest 输出带 ANSI（行首是 ESC[2m），"行首就是 Tests " 永远不成立。
JSON reporter 两个问题一起绕开：计数在文件里，位置固定、无颜色。
"""

import json
import os
import re
import shutil
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READING = os.path.join(ROOT, ".pipe", "gha_reading.json")
VITEST_JSON = os.path.join(ROOT, ".pipe", "vitest.json")
BEGIN = "=== GHA-GATE-READING-BEGIN ==="
END = "=== GHA-GATE-READING-END ==="
GUARD = "GHA_GATE_ADAPTER"

ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: 卡 148：Windows 上不弹窗。POSIX 上这一项是 0，subprocess 照常接受。
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(argv, label, timeout):
    """跑一条命令，返回 (rc, 合并输出)。"""
    print("--- " + label + ": " + " ".join(argv), flush=True)
    t0 = time.time()
    env = dict(os.environ, CI="true", COREPACK_ENABLE_DOWNLOAD_PROMPT="0",
               PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=timeout, env=env,
                                creationflags=NO_WINDOW)
        rc = proc.returncode
        out = (proc.stdout or b"") + (proc.stderr or b"")
    except subprocess.TimeoutExpired:
        rc, out = 124, b"[timeout]"
    except OSError as exc:
        rc, out = 127, ("[cannot start: " + str(exc) + "]").encode("utf-8", "replace")
    text = out.decode("utf-8", "replace")
    cleaned = ANSI.sub("", text)
    print(chr(10).join(cleaned.strip().splitlines()[-25:]), flush=True)
    print("--- " + label + ": rc=" + str(rc) + " elapsed=" + ("%.1f" % (time.time() - t0)) + "s",
          flush=True)
    return rc, text


def _counts(path):
    """从 vitest 的 JSON 报告取计数。取不到就返回空 dict（⇒ 读数是「判不出」而不是 0）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    keys = ("numTotalTests", "numPassedTests", "numFailedTests", "numPendingTests",
            "numTodoTests", "numTotalTestSuites", "numPassedTestSuites",
            "numFailedTestSuites", "numPendingTestSuites", "success")
    return {k: data[k] for k in keys if k in data}


def _steps_record(rc, out):
    return {"rc": rc, "tail": ANSI.sub("", out).strip().splitlines()[-8:]}


def test_dsh_suite_on_github_actions():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    if os.environ.get(GUARD):
        return
    os.environ[GUARD] = "1"
    corepack = shutil.which("corepack") or "corepack"
    steps = []
    notes = []

    rc_node, out_node = _run(["node", "--version"], "node", 120)
    steps.append({"step": "node", **_steps_record(rc_node, out_node)})
    rc_pnpm, out_pnpm = _run([corepack, "pnpm", "--version"], "pnpm-version", 600)
    steps.append({"step": "pnpm-version", **_steps_record(rc_pnpm, out_pnpm)})
    rc_install, out_install = _run([corepack, "pnpm", "install", "--frozen-lockfile"],
                                   "pnpm-install", 1500)
    steps.append({"step": "pnpm-install", **_steps_record(rc_install, out_install)})

    os.makedirs(os.path.dirname(VITEST_JSON), exist_ok=True)
    if os.path.exists(VITEST_JSON):
        os.remove(VITEST_JSON)

    test_rc = None
    test_out = ""
    if rc_install != 0:
        notes.append("pnpm install 没成功，没往下跑 vitest（装不上就没有可信读数）")
    else:
        test_rc, test_out = _run(
            [corepack, "pnpm", "exec", "vitest", "run",
             "--reporter=default", "--reporter=json", "--outputFile=" + VITEST_JSON],
            "vitest", 2400)
        steps.append({"step": "vitest", **_steps_record(test_rc, test_out)})

    counts = _counts(VITEST_JSON)
    if test_rc is not None and not counts:
        notes.append("vitest 没留下可解析的 JSON 报告（--outputFile 没写成）⇒ 计数判不出")
    reading = {
        "ok": rc_install == 0 and test_rc == 0 and not notes,
        "returncode": test_rc if test_rc is not None else rc_install,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "suite": "vitest",
        "steps": steps,
        "counts": counts,
    }
    if counts:
        # 名字对齐 python 腿那几份（passed / failed / skipped），读日志的人不用记两套词
        reading["passed"] = counts.get("numPassedTests", 0)
        reading["failed"] = counts.get("numFailedTests", 0)
        reading["skipped"] = counts.get("numPendingTests", 0) + counts.get("numTodoTests", 0)
        reading["files_failed"] = counts.get("numFailedTestSuites", 0)
        reading["files_passed"] = counts.get("numPassedTestSuites", 0)
        if counts.get("success") is False:
            reading["ok"] = False
    if notes:
        reading["notes"] = notes

    os.makedirs(os.path.dirname(READING), exist_ok=True)
    with open(READING, "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(json.dumps(reading, ensure_ascii=False, indent=2) + chr(10))
    print("[reading-hook] wrote " + READING, flush=True)
    blob = json.dumps(reading, ensure_ascii=False, sort_keys=True)
    print(BEGIN, flush=True)
    print(blob, flush=True)
    print(END, flush=True)
    assert reading["ok"], reading
