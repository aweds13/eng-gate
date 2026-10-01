r"""白名单越界 —— **唯一实现**（卡 106 · T-G202）。

**防什么**：一份提交里**顺手改了白名单外的东西**还一起提交进去（越界 = 这一轮作废）。
判据是纯机械的：一组仓库相对路径里，哪些**不在**允许 glob 里。

★ 为什么放这里（本仓最忌的"两份真源"）：同一件事原先有**三份实现** ——
`wb_review.check_files()`、`wb_dispatch._outside_allow()`、`tf_stage_guard.outside_allow()`。
这里收敛成**一处** `outside_allow()`：路径与 glob 都先把反斜杠规范成 `/` 再比（与
`tf_stage_guard` 完全一致；git 在 `core.quotepath=false` 下本来就吐 `/`，对真实输入是**恒等**的）。
`wb_review.py` 改成调这里；另两处若**不在本卡白名单 / 是禁区**，暂时保留（见卡回报第 8 条），
但由测试证明三者对同一输入给出**同一越界清单**。

★ 中文路径：路径一律**原样**比、不清洗引号 —— 本仓踩过：git 默认把非 ASCII 做八进制转义，
拿它跟白名单里的中文路径比会**永远不匹配**。`core.quotepath=false` 在取路径那一步钉死。
"""

from __future__ import annotations

import fnmatch


def outside_allow(paths: list[str], allow: list[str]) -> list[str]:
    """`paths` 里**不在**允许列表（fnmatch）里的那些 —— 越界项，顺序保持原样。

    路径与 glob 都先把 `\\` 规范成 `/` 再比（Windows 下 git 偶尔给反斜杠时也不误判）；
    空 `allow` = 全越界（调用方负责先判"没给白名单"）。
    """
    normalized_allow = [a.replace("\\", "/") for a in allow]
    out: list[str] = []
    for path in paths:
        rel = path.replace("\\", "/")
        if not any(fnmatch.fnmatch(rel, pat) for pat in normalized_allow):
            out.append(path)
    return out
