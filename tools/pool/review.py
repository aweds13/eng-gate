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

import tomllib


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


# ================================================ 实际改动 vs 权威域（卡 131 · T-G228）
#
# 治外部审查（GLM-5.3）「三.1」：域检查原先吃的是**交申请一方自己填的清单** —— 卡树里真的改了
# 什么从不参与判断，于是**真实越界只要不自报就全绿**。下面三个零件给复核侧一条机器判据：
# 读卡树的**实际改动**、读**权威域**、比出越界。纯函数、无 IO（读文件 / 跑 git 留给调用方）。


def changed_paths(status_text: str) -> list[str]:
    """从 `git status --porcelain -uall --no-renames` 的原文取出改动路径集合（**含未跟踪** `??`）。

    ★ 每行形状 `XY <path>`：状态恰好 2 列 + 1 个空格 ⇒ 取 `line[3:]`。
    ★ `--no-renames` 让改名拆成"删 + 增"两行、**不出现** `old -> new`；这里仍按箭头右侧兜一下。
    ★ **不做**引号反转义：本仓取路径一律带 `core.quotepath=false`（中文不做八进制转义）；
      会触发 git 引号的是控制字符 / 引号本身那类罕见路径 —— 那种路径会原样（带引号）出现，
      属**已知边界**（本卡不要求）。
    """
    out: list[str] = []
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            out.append(path)
    return out


def domain_of_manifest_text(text: str, member_id: str) -> list[str] | None:
    """任务预声明 TOML 原文里某成员的 `paths`（＝这张卡的域）；**没有这个成员 → `None`**。

    ★ 直接读预声明原文，**不 import `pool.task`**：栅栏本体的 `batch_dir()` 锚在**主树**
      （`git rev-parse --git-common-dir`）且会顺手校验 `why` / `layer` 等字段 —— 复核器只要
      **这一张成员的域**，读原始 TOML 耦合更少（卡 131 只治复核侧，不动栅栏本体）。
    ★ 返回 `None` 而不是 `[]`：区分"查不到这个成员"与"成员域就是空的" —— **空域会骗过一切守卫**
      （`guards.py` 模块头专门写了这条），调用方据此**拒单**，绝不当成"没有约束"。
    """
    data = tomllib.loads(text)
    for member in data.get("member") or []:
        if str(member.get("id", "")) == member_id:
            return [str(p) for p in (member.get("paths") or [])]
    return None


def outside_domain(paths: list[str], domain: list[str]) -> list[str]:
    """`paths` 里**不在权威域**里的那些 —— 就是 `outside_allow()`，只换了个语义标签。

    ★ 为什么复用 `outside_allow` 而**不**新写第三套匹配（卡 131 明令"别造第三套语义"）：
      栅栏那侧（`pool.task.check_domain`）对成员 `paths` 用的就是 `fnmatch`，这里的"域"是
      **同一份声明** ⇒ 用同一套语义才叫"和权威域比对"。队列那侧的 `files` 是**精确路径且禁通配**
      （`pool.plan.validate` ⑧），对无通配的模式 `fnmatch` 退化成精确匹配 ⇒ 两种来源都不走样。
      （`files_intersect` 是**相交**判据，用途不同，不拿它判"在不在域内"。）
    """
    return outside_allow(paths, domain)
