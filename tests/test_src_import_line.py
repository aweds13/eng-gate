"""钉子（T-G134）：worktree 里跑 pytest，`import timeflow` 必须拿到**本树**的 src。

背景：miniconda 的 editable 安装（`__editable__.timeflow-0.1.0.pth`）硬指主树的
`engineering\\src` —— 在 `git worktree` 里跑测试会静默导入主树旧代码，既能造假红
（新用例用到本树新接口就崩）也能造假绿（新测试跑在旧实现上照样通过）。

判据全部**相对**本树根（由本文件的 `__file__` 往上推），不出现任何字面绝对路径。
"""

from __future__ import annotations

import os
import pathlib
import sys

import timeflow

_TREE_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TREE_SRC = _TREE_ROOT / "src"


def _resolved(entry: str) -> pathlib.Path:
    # sys.path 里可能有空串（= cwd）与未归一化的写法，统一按绝对路径比较；
    # Windows 下大小写不敏感，再用 normcase 兜一层。
    p = pathlib.Path(entry).resolve() if entry else pathlib.Path.cwd().resolve()
    return pathlib.Path(os.path.normcase(str(p)))


def test_import_timeflow_resolves_to_this_tree() -> None:
    imported = pathlib.Path(timeflow.__file__).resolve()
    assert _TREE_ROOT in imported.parents, (
        f"import timeflow 拿到的不是本树的代码：{imported}（本树根：{_TREE_ROOT}）"
    )


def test_this_tree_src_precedes_all_external_sys_path_entries() -> None:
    tree = os.path.normcase(str(_TREE_ROOT))
    src = os.path.normcase(str(_TREE_SRC))
    src_idx = next(
        (i for i, e in enumerate(sys.path) if _resolved(e) == pathlib.Path(src)),
        None,
    )
    assert src_idx is not None, f"本树 src 不在 sys.path 里：{_TREE_SRC}"
    for i, e in enumerate(sys.path):
        r = _resolved(e)
        # 只把「本树之内」的条目算自己人（带分隔符，防 “engineering” 撞 “engineering2”）
        inside = str(r) == tree or str(r).startswith(tree + os.sep)
        if not inside:
            assert src_idx < i, (
                f"本树 src（sys.path[{src_idx}]）没有前置："
                f"外部路径 {e!r} 排在它前面（sys.path[{i}]）"
            )
