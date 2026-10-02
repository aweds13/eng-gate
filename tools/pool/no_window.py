r"""子进程「不弹窗」flag 的**唯一真源**（卡 148 · T-G248）。

## 为什么有它（用户现场反馈）

用户 2026-10-02：*「为什么我一直在蹦命令行窗口？」* —— Windows 11 会把**没有控制台的父进程**
起的控制台子进程（`git` / `python` / `node` / `taskkill` …）转交给**默认终端宿主**，
于是每起一个子进程就闪一个命令行窗口。带上 `CREATE_NO_WINDOW` 就压住它。

## 用法（唯一写法）

    from pool.no_window import NO_WINDOW
    subprocess.run(argv, capture_output=True, text=True, **NO_WINDOW)

★ **别**在每个调用点各写一遍 `creationflags=…` 的字面量 —— 集中在这里，改口径只改一处。
非 Windows 平台没有这个概念，值是空 dict（语法上仍算「带上了」）。
"""

from __future__ import annotations

import os

#: Windows ⇒ `CREATE_NO_WINDOW`；其它平台 ⇒ `{}`（别的平台没有这个 flag）。
#: ★ 写数值 `0x08000000` 而不写 `subprocess.CREATE_NO_WINDOW`：typeshed 只在 `win32`
#:   分支声明那个属性，写属性会在非 Windows 上报 `attr-defined`（得配 `# type: ignore`）；
#:   数值两边都干净。二者等价由 `tests/test_no_window.py` 的
#:   `test_shared_flag_is_platform_correct` 钉住。
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if os.name == "nt" else {}

__all__ = ["NO_WINDOW"]
