"""产品门：timeflow 这一款产品自己的门。换产品 ⇒ 整份替换。

★ 门数是会变的：真源只有这里；`tools/wb_verify.py` 与 `tools/wb_review.py` 都从门表现读，
  任何地方都不许写死 17 / 18 / 19。
"""

import sys

PY = sys.executable

GATES: list[tuple[str, list[str]]] = [
    # 五层文档对齐（意图 / 规格 / 契约 / 实现 / 品味）。
    ("check_layers", [PY, "-X", "utf8", "scripts/check_layers.py"]),
    # 对比度审美门（T-G27 建 → T-G42 收紧）：令牌层 WCAG，`--strict` 是硬门，不达 AA 当场红。
    ("contrast", [PY, "-X", "utf8", "tools/contrast_audit.py", "--strict"]),
    # 风格一致性：同形状重复 / 一次性裸值 / 缺 :hover·:focus-visible / 动效越界。
    ("style", [PY, "-X", "utf8", "tools/style_audit.py", "--check"]),
    # 界面文案上限门（T-G57）：≥30 汉字一条都不许、≥20 只许减不许增（棘轮）。
    ("ui_text", [PY, "-X", "utf8", "tools/ui_text_audit.py", "--check"]),
    # 命令表（T-G31）：界面 / ⌘K / CLI / AI·MCP 四个面共用的那一个源，必须与三个真源对得上。
    ("commands", [PY, "-X", "utf8", "scripts/check_commands.py", "--check"]),
    # DOM 探针是占位：按 node 是否可用来填（见 `scripts/run_gates.py`）。
    ("ui_dom_probe", []),
    # 代理指标过期对账（卡 208）：判据在 `tools/proxy_audit.py`，这里不重写阈值。
    ("proxy", [PY, "-X", "utf8", "tools/proxy_audit.py", "--check"]),
]

# 真机层：起不了服务就记 `not_run`，NOT RUN 不是 PASS。
REAL: list[tuple[str, list[str]]] = [
    ("lf1_live", [PY, "-X", "utf8", "tools/lf1_live_check.py"]),
    ("web_live", [PY, "-X", "utf8", "tools/web_live_check.py"]),
]

# 渲染 / 行为流：真浏览器；每次采两遍做确定性自检，不一致退 4（工具自己不可信）。
BROWSER: tuple[str, ...] = ("render", "ui_flow")
