"""PC 入口线与可选依赖（卡 098 / 轨外 089 · A 档）。

口径（用户拍板 A 档）：

- `pywebview` 从**硬依赖**挪进 `optional-dependencies[pc]` —— 只想在浏览器 / 手机上用的人
  不该被迫先装一个桌面壳；
- 新增**无窗口**入口 `timeflow-web`（`timeflow.app.serve:main`）：行为与 `timeflow.app.main`
  **一致**（起服务前先备份 → 认 `[net] allow_lan` → 打印人话地址），但**不开窗口**：
  不引入 `webview`、不建窗口、也不去打开系统浏览器。

★ 本文件**不装 pywebview 也要能跑**：断言要么直接读 `pyproject.toml` / 源码文本，
  要么用**桩**把"真起服务""真开窗口"两条路换掉（不起服务、不开窗口、不联网）。
  "import 不依赖 pywebview"这件事用**干净子进程**现证（不靠"本机恰好没装"）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomllib

from timeflow.app import serve

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ 一、pyproject 三处
def test_pyproject_moves_pywebview_into_the_pc_extra() -> None:
    """`pywebview` 只在 `optional-dependencies.pc` 里，不在硬依赖里；两个入口都在。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert not any("pywebview" in dep for dep in project["dependencies"]), (
        f"pywebview 又回到硬依赖里了：{project['dependencies']}"
    )
    assert any("pywebview" in dep for dep in project["optional-dependencies"]["pc"])

    scripts = project["scripts"]
    assert scripts["timeflow-web"] == "timeflow.app.serve:main"
    assert scripts["timeflow"] == "timeflow.app.main:main", "窗口那条入口一字没动"


def test_desktop_main_keeps_port_and_explains_the_optional_extra() -> None:
    """删硬依赖后 `main.py` 只改了回退文案：端口 / 备份 / 窗口逻辑原样。"""
    src = (ROOT / "src" / "timeflow" / "app" / "main.py").read_text(encoding="utf-8")
    assert "port = 8520" in src, "桌面入口的默认端口不许被本卡改动"
    assert "make_backup" in src, "备份口径不许动"
    assert "webview.create_window" in src, "窗口那条路要留着"
    assert 'pip install -e ".[pc]"' in src, "回退文案要说清可选依赖怎么装"


# ------------------------------------------------------------------ 二、无窗口入口
def test_serve_imports_and_never_pulls_in_webview() -> None:
    """`serve` 能被 import，且**不把 webview 拉进 sys.modules**（没装/装了都一样）。"""
    src = (ROOT / "src" / "timeflow" / "app" / "serve.py").read_text(encoding="utf-8")
    assert "import webview" not in src
    assert "create_window" not in src and "webbrowser" not in src, "无窗口入口不该碰窗口/浏览器"

    # 干净子进程现证：先**假装没装 pywebview**（任何 import webview 都炸），
    # 再 import serve —— 仍要成功，且 webview 不在 sys.modules 里（也不真起服务）。
    code = """
import sys

class _NoWebview:
    def find_spec(self, name, path=None, target=None):
        if name == "webview" or name.startswith("webview."):
            raise ImportError("no module named 'webview'（本用例模拟：没装 pc 额外项）")
        return None

sys.meta_path.insert(0, _NoWebview())
import timeflow.app.serve as s
assert callable(s.main), "serve.main 不是可调用入口"
assert "webview" not in sys.modules, "serve 把 webview 拉进来了"
print("OK-NO-WEBVIEW")
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK-NO-WEBVIEW" in proc.stdout


def _install_stubs(monkeypatch, events: list, db_path: Path, *, allow_lan: bool) -> dict:
    """把"真起服务 / 真开窗口 / 真连库"换成桩；返回可读的座位（host/port）。"""
    seats: dict[str, object] = {}

    monkeypatch.setattr(
        serve,
        "load_settings",
        lambda *a, **k: SimpleNamespace(
            database=SimpleNamespace(path=str(db_path)),
            net=SimpleNamespace(allow_lan=allow_lan),
        ),
    )

    def fake_backup(path: Path) -> Path:
        events.append("backup")
        return Path(str(path) + ".bak-20260101-000000")

    monkeypatch.setattr(serve.backup_mod, "make_backup", fake_backup)
    monkeypatch.setattr(serve, "create_app", lambda *a, **k: object())

    class FakeConfig:
        def __init__(self, app: object, host: str, port: int, log_level: str) -> None:
            seats["host"] = host
            seats["port"] = port

    class FakeServer:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config

        def run(self) -> None:  # 别真起服务
            events.append(("serve", seats["host"], seats["port"]))

    monkeypatch.setattr(serve.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(serve.uvicorn, "Server", FakeServer)
    return seats


def test_serve_backs_up_before_it_serves_and_reports_the_address(
    tmp_path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    """默认（不开局域网）：**先备份再起服务**；打印人话地址；只绑回环；不打局域网横幅。"""
    events: list = []
    seats = _install_stubs(monkeypatch, events, tmp_path / "timeflow.db", allow_lan=False)
    # 关着的时候**绝不该**去连库取配对码 —— 连了就是不必要地碰真库
    monkeypatch.setattr(
        serve.db_mod, "connect", lambda *a, **k: pytest.fail("默认关时不该连库取配对码")
    )
    monkeypatch.setattr(
        serve.lan_mod, "banner", lambda *a, **k: pytest.fail("默认关时不该打局域网横幅")
    )

    assert serve.main([]) == 0
    out = capsys.readouterr().out

    assert events[0] == "backup" and events[1][0] == "serve", f"顺序不对：{events}"
    assert seats["host"] == "127.0.0.1"
    assert "[已备份]" in out, "起服务前要先备份（口径同 main.py）"
    assert "http://127.0.0.1:8520" in out, "要打印人话的访问地址"
    assert "[局域网]" not in out and "[配对码]" not in out


def test_serve_lan_on_binds_everything_and_prints_the_banner(
    tmp_path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    """开了 `[net] allow_lan`：绑 `0.0.0.0` + 打印地址/配对码横幅；备份仍在最前。"""
    events: list = []
    seats = _install_stubs(monkeypatch, events, tmp_path / "timeflow.db", allow_lan=True)
    monkeypatch.setattr(serve.db_mod, "connect",
                        lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(serve.lan_mod, "code", lambda conn: "123456")

    def fake_banner(port: int, code: str) -> list[str]:
        events.append(("banner", port, code))
        return ["[局域网] STUB 已开启", "[配对码] 123456"]

    monkeypatch.setattr(serve.lan_mod, "banner", fake_banner)

    assert serve.main([]) == 0
    out = capsys.readouterr().out

    assert seats["host"] == "0.0.0.0", "开了局域网要绑所有网卡（手机才连得上）"
    assert ("banner", 8520, "123456") in events, "开了局域网要打地址与配对码"
    assert events.index("backup") < events.index(("banner", 8520, "123456")) < len(events)
    assert "[局域网] STUB 已开启" in out and "[配对码] 123456" in out


def test_serve_accepts_an_optional_port(tmp_path, monkeypatch, capsys) -> None:
    """端口口径与 `main.py` 一致（默认 8520）；被占时可 `--port` 换一个。"""
    events: list = []
    seats = _install_stubs(monkeypatch, events, tmp_path / "timeflow.db", allow_lan=False)
    monkeypatch.setattr(serve.db_mod, "connect", lambda *a, **k: pytest.fail("默认关时不该连库"))

    assert serve.main(["--port", "8599"]) == 0
    assert seats["port"] == 8599
    assert "http://127.0.0.1:8599" in capsys.readouterr().out
