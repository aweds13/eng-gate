"""核「真机自检超时不许抛裸 traceback、也不许洗成通过」会不会咬（卡 E67 · T-AG528）。

## 为什么有这张测试

云机（2 物理核 / 4 逻辑核、内存紧）跑 `web_live` 那一趟红了，日志尾部是**裸 traceback**：

```
  File "tools/web_live_check.py", line 283, in main
    turned_on = _json_call(base, "/api/settings/ai", "PUT", {"enabled": True})[0]
  File "C:\\Python311\\Lib\\socket.py", line 706, in recv_into
    return self._sock.recv_into(b)
TimeoutError: timed out
```

病灶在 `tools/web_live_check.py:_json_call`：`urlopen(req, timeout=10)` 把 10 秒写死，
而 `except` 只接 `urllib.error.HTTPError`（4xx/5xx 拿状态码）—— `TimeoutError` /
`URLError` **一个都没接** ⇒ 抛穿到顶，整道门只剩一条说不清断在哪的 traceback。

## 怎么验

① 错误消息必须**点名**：endpoint、方法、等了多久、原始异常类型；
② 等待窗必须**可调**（env `TF_WEB_LIVE_TIMEOUT`），且默认值不变（本机不受影响）；
③ **不许洗成通过**：等不到要落成一条 `checks[...] = False`（点名），或者显式
   `[SKIP] not verified` —— 本仓禁止「未验证冒充通过」。

## 边界（如实写，未覆盖）

- 不真起 uvicorn（那要真机，且 `tests/test_gate_selfproof.py` 的 docstring 已如实登记
  「13 组 `live_*` 仍是盲区」）。这里把 `urllib.request.urlopen` 打成桩，验的是
  **`_json_call` 自己的收口行为**与 `main()` 那条链的**兜底**，不是真网络。
- 桩只替「网络怎么回」，**不替判据本体**：`_json_call` / `mark_live_error` 都真跑。
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def _load(name: str, path: Path):
    """按文件路径装模块（同名模块可能已被别的测试装过，这里换唯一名字）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # 先登记：否则模块里的 dataclass 会炸
    spec.loader.exec_module(mod)
    return mod


wlc = _load("web_live_check_for_e67", TOOLS / "web_live_check.py")


class _RefusedError(Exception):
    """假的底层异常（`URLError.reason` 的形状）。"""


def _boom(*_a, **_kw):
    """桩：`urlopen` 一定要「等不到」——超时。"""
    raise TimeoutError("timed out")


# ==================================================================== ① 点名


def test_timeout_error_names_the_endpoint_and_the_wait(monkeypatch):
    """★ 主钉子：超时抛的是**带点名**的 `LiveCallError`，不是裸 `TimeoutError`。"""
    monkeypatch.setattr(wlc.urllib.request, "urlopen", _boom)
    with pytest.raises(wlc.LiveCallError) as ei:
        wlc._json_call("http://127.0.0.1:9", "/api/settings/ai", "PUT", {"enabled": True})
    msg = str(ei.value)
    assert "/api/settings/ai" in msg, f"没点名 endpoint：{msg}"
    assert "PUT" in msg, f"没点名方法：{msg}"
    assert "TimeoutError" in msg, f"没点名原始异常类型：{msg}"
    assert "10" in msg, f"没写等了多久：{msg}"


def test_refused_connection_is_also_named(monkeypatch):
    """拒连（`URLError` / `OSError` 家族）也要点名，不许抛穿。"""

    def refuse(*_a, **_kw):
        raise urllib.error.URLError(_RefusedError("connection refused"))

    monkeypatch.setattr(wlc.urllib.request, "urlopen", refuse)
    with pytest.raises(wlc.LiveCallError) as ei:
        wlc._json_call("http://127.0.0.1:9", "/api/summary")
    msg = str(ei.value)
    assert "/api/summary" in msg and "URLError" in msg, f"拒连没点名：{msg}"


def test_http_error_still_returns_its_status_code(monkeypatch):
    """**反例**：4xx/5xx 的行为不许变 —— 仍返回 `(状态码, None)`。"""

    def not_found(*_a, **_kw):
        raise urllib.error.HTTPError("http://x/y", 404, "Not Found", {}, None)

    monkeypatch.setattr(wlc.urllib.request, "urlopen", not_found)
    assert wlc._json_call("http://x", "/y") == (404, None)


def test_happy_path_still_parses_the_body(monkeypatch):
    """**反例**：正常返回仍是 `(状态码, 解析结果)`，调用方的 `[1]["id"]` 取值链不受影响。"""

    class _Resp:
        status = 200

        def read(self):
            return b'{"id": "t-1"}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(wlc.urllib.request, "urlopen", lambda *_a, **_kw: _Resp())
    assert wlc._json_call("http://x", "/api/tasks", "POST", {"title": "t"})[1]["id"] == "t-1"


# ==================================================================== ② 可调等待窗


def test_wait_window_defaults_to_ten_and_is_env_tunable(monkeypatch):
    """★ 主钉子：默认 10 秒不变；env 一给就按 env 走（云机调这个，不放宽判据）。"""
    monkeypatch.delenv(wlc.CALL_TIMEOUT_ENV, raising=False)
    assert wlc.call_timeout() == 10.0, "默认值被改了 —— 本机不该受影响"
    monkeypatch.setenv(wlc.CALL_TIMEOUT_ENV, "30")
    assert wlc.call_timeout() == 30.0


def test_wait_window_rejects_junk_instead_of_going_infinite(monkeypatch):
    """**反例**：坏值 / 非正数退回默认 —— 静默变成「永不超时」等于放宽判据。"""
    for bad in ("abc", "0", "-5", ""):
        monkeypatch.setenv(wlc.CALL_TIMEOUT_ENV, bad)
        assert wlc.call_timeout() == 10.0, f"坏值 {bad!r} 没退回默认"


def test_wait_window_actually_reaches_urlopen(monkeypatch):
    """等待窗必须真的传进 `urlopen` —— 否则 env 是个摆设。"""
    seen: dict[str, object] = {}

    def grab(_req, timeout=None):
        seen["timeout"] = timeout
        raise TimeoutError("timed out")

    monkeypatch.setattr(wlc.urllib.request, "urlopen", grab)
    monkeypatch.setenv(wlc.CALL_TIMEOUT_ENV, "42")
    with pytest.raises(wlc.LiveCallError):
        wlc._json_call("http://x", "/y")
    assert seen["timeout"] == 42.0, f"等待窗没传下去：{seen['timeout']!r}"


# ==================================================================== ③ 不许洗成通过


def test_timeout_becomes_a_named_fail_not_a_pass():
    """★ 主钉子：等不到要落成 `checks[...] = False`，名字里带方法与 endpoint。"""
    checks: dict[str, bool] = {"页面能挂载": True}
    err = wlc.LiveCallError("PUT", "http://x/api/settings/ai", 10.0, TimeoutError("timed out"))
    wlc.mark_live_error(checks, err)
    assert any(v is False for v in checks.values()), "超时被洗成了通过"
    name = next(k for k, v in checks.items() if v is False)
    assert "PUT" in name and "/api/settings/ai" in name, f"没点名：{name}"


def test_a_failed_check_makes_the_whole_gate_red():
    """**反例（判据本体）**：只要有一条 False，`all(checks.values())` 就是 False ⇒ 退 1。"""
    checks = {"页面能挂载": True}
    err = wlc.LiveCallError("PUT", "http://x/api/settings/ai", 10.0, TimeoutError("timed out"))
    wlc.mark_live_error(checks, err)
    assert all(checks.values()) is False


def test_star_symptom_survives_the_final_rerun(capsys):
    """★ 卡 E152：收口重打那一轮，False 行必须继续带 ★ 与症状原文。

    现场：症状只打在 `mark_live_error()` 那一行（带 ★），主流程收口又把所有 check 名字重打一遍；
    旧写法只打名字 ⇒ `detail` 取的尾部只剩「配对失败」的名字，看不出是「等不到」，
    `mark_suspect_rows()` 于是永远标不上 `SUSPECT`（GHA 上三趟读数的 status 全是 None）。
    """
    checks: dict[str, bool] = {"页面能挂载": True}
    symptoms: dict[str, str] = {}
    err = wlc.LiveCallError("PUT", "http://x/api/settings/ai", 60.0, TimeoutError("timed out"))
    wlc.mark_live_error(checks, err, symptoms)
    capsys.readouterr()          # 第一轮（带 ★ 那行）不算，只看收口那一轮
    wlc.print_checks(checks, symptoms)

    out = capsys.readouterr().out
    fail_lines = [ln for ln in out.splitlines() if ln.startswith("[FAIL]")]
    assert len(fail_lines) == 1, f"收口该只打一行 FAIL：{fail_lines!r}"
    # 名字形状一个字不许改（既有 startswith 断言都认这个前缀）。
    head = fail_lines[0].split("  ")[0]
    assert head.startswith("[FAIL] 真机自检没跑完：PUT "), f"名字形状变了：{head!r}"
    assert "/api/settings/ai" in fail_lines[0]
    # 症状必须补回来：★ 与「没等到」两个都在。
    assert "★" in fail_lines[0], f"收口把 ★ 洗掉了：{fail_lines[0]!r}"
    assert "没等到" in fail_lines[0], f"症状原文没补回来：{fail_lines[0]!r}"
    assert "[OK ] 页面能挂载" in out, "绿行形状也被改坏了"


def test_fail_without_symptom_keeps_the_bare_name(capsys):
    """**反例**：没有症状的 False 行不许凭空长出 ★（那会让「断言不符」冒充「等不到」）。"""
    checks = {"页面能挂载": False}
    wlc.print_checks(checks)
    out = capsys.readouterr().out
    assert out == "[FAIL] 页面能挂载" + "\n", f"形状变了：{out!r}"
