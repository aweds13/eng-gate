# 骨架清单与幂等口径（细则）

> `pipe-init/SKILL.md` 的按需参考。**清单会随模板变** —— 真源是 `framework/templates/minimal/`，
> 别拿这份当判据；要当下的清单就跑一次 `--json`。

## 1. 当下的铺出清单（`minimal` 模板）

实测（2026-10-19，`python -X utf8 framework/cli/main.py --json init --dir <临时目录>`）：

| # | 文件 | 作用 |
|---|---|---|
| 1 | `.gitignore` | 骨架自带的忽略（门产物 / 临时件） |
| 2 | `README.md` | 项目壳说明 |
| 3 | `backlog.toml` | 队列壳 |
| 4 | `card-template.md` | 卡模板 |
| 5 | `docs/README.md` | 文档层壳 |
| 6 | `gates.d/tests.toml` | 门分片示例 |
| 7 | `invariants.toml` | 不变量壳 |
| 8 | `ledger.toml` | 台账壳 |
| 9 | `pipeline.toml` | 顶层配置 |
| 10 | `<新仓>/src/notes/__init__.py` | 示例包 |
| 11 | `<新仓>/src/notes/evidence.py` | 示例模块 |
| 12 | `tests/conftest.py` | 测试夹具 |
| 13 | `<新仓>/tests/test_evidence.py` | 示例判据 |
| 14 | `<新仓>/tests/test_nail_sample.py` | 钉子样例（证明门真的会咬） |

`count = 14`。换模板（`--template <名>`）时清单不同 —— 以该模板的 `--json` 读数为准。

## 2. 幂等口径（怎么读，不是判据）

- 第二次对**同一个非空目录**再铺：不给 `--force` ⇒ 退 `5`（拒绝，不是静默半铺）。
- 给 `--force` 且目标在仓内 ⇒ 覆盖；**仓外** ⇒ 退 `4`。
- 「逐字节相同算不算幂等」的判定在 `framework/src/framework/scaffold.py`；这里不抄。

## 3. 退出码（框架 CLI 唯一一张表）

| 码 | 含义 |
|---|---|
| 0 | 通过 |
| 1 | 判据不通过 |
| 2 | 用法 / 参数错 |
| 3 | 资源闸拒跑 |
| 4 | 被策略拒绝（越界 / 未授权） |
| 5 | 前置条件缺失（文件 / 段 / 键不存在；含「薄壳未实现」） |
| 6 | 被外部打断（可续跑） |
| 7 | 资源全挂 |
| 124 | 单道门硬超时 |

## 4. 铺完之后的第一步

```bash
cd <目标目录>
python -X utf8 <本仓>/framework/cli/main.py gate --config pipeline.toml
```

`pipe gate` 需要 `pipeline.toml`；本仓根目录**没有**它，所以在新铺的目录里跑才有效。
