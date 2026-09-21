"""例 2（中）· 加一个**配置项**：以「番茄钟时长」为例，展示配置的四处落点。

什么时候用这个示例：你要让**用户可以调**某个行为（时长、阈值、开关、制式……），
而不是把它写死在代码里。

配置的四处落点（缺一处就是"半成品"）：
    ① `src/timeflow/config.py`   —— 加字段（pydantic 会顺手做类型校验）
    ② `config.example.toml`      —— 加**带中文注释**的示例（用户抄的就是这份）
    ③ 用到它的模块              —— 读 `load_settings()`（**不要在函数里写死常量**）
    ④ `docs/`（如 implementation/modules.md）+ `changelog.md` —— 文档同步

环境变量覆盖的写法：`TIMEFLOW_<段名>__<键名>`（双下划线表示下一层，大小写不敏感）。
**敏感信息（API Key / Cookie）永远只放本机 `config.toml`**，不入 Git / PR / 日志 / 截图。

跑法（在项目根目录）：
    python -X utf8 examples/02_add_a_config_option.py
"""

from __future__ import annotations

import os

from timeflow.config import load_settings

ENV_KEY = "TIMEFLOW_FOCUS__POMODORO_MINUTES"


def main() -> int:
    before = load_settings()
    print(f"[例2] 改之前：focus.pomodoro_minutes = {before.focus.pomodoro_minutes}")
    print("[例2] （值可能来自 config.toml，也可能来自内置默认 —— 两者都合法）")

    os.environ[ENV_KEY] = "50"
    after = load_settings()

    assert after.focus.pomodoro_minutes == 50, after.focus.pomodoro_minutes
    assert after.database.path == before.database.path, "没碰过的字段不该被 env 影响"

    print(f"[例2] 设 {ENV_KEY}=50 之后 = {after.focus.pomodoro_minutes}")
    print("[例2] 没碰过的字段保持原值 → env 覆盖是「按字段」而不是「整份替换」")
    print("OK 例2：env 覆盖生效（TIMEFLOW_<段>__<键>；config.toml → env → 代码默认，后者胜）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
