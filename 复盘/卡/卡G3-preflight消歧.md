# 卡 G3 —— `--preflight` 同名不同义：旧的「跳过预检」与新的「只读体检」

> 台账号 T-AG458 · 分区 G（软工技能）· 依赖：E1

## 现在疼在哪（实测）

- **旧义（已落主树）**：`skills/pipe-land/references/land-steps.md:23`
  「`--no-preflight` —— 跳过 ③″ 快门禁预检（已知道要跑全量时）」。`wb_land.py` 里这个旗标
  一直是「**少跑一次快门禁预检**」。
- **新义（卡 E1）**：`wb_land.py --preflight` = **只读体检 13 条**（不给 `--card` 就体检完早退，
  20 秒左右，零副作用、不拿锁）。

⇒ 落完 E1 后，`--preflight` 与 `--no-preflight` 同时在，词根相同、层次完全不同：
一个是「先体检」，一个是「别预检」。照着旧文档敲的人会以为自己关掉了体检，实际什么都没关。

## 目标

同一页纸上不再有两个 `preflight` 指两件事。

## 判据

1. **选出一种消歧法并写清理由**（二选一，不要两个都留）：
   - 改名：E1 那条改成 `--check`（或 `--inspect`），旧 `--no-preflight` 保持原义；
   - 或分层命名：`--preflight`（体检）/ `--skip-preflight`（跳过快门禁预检），旧写法给别名。
2. **`--help` 里两处措辞不再混**：各自的 `help=` 要写出「它对哪一层、花多少时间、有没有副作用」。
3. **技能同步**：`skills/pipe-land/SKILL.md`、`references/land-steps.md` 里出现 preflight 的地方逐条对过，
   一个不留旧义；G1 的尺子绿。
4. **钉子**：`tests/test_wb_land.py` 至少一条「两个旗标不同层」的断言
   （例如给 `--skip-preflight` 时体检照跑、给 `--preflight` 时只体检不落地）。
5. **向后兼容说明**：如果改掉了已发布的写法，在 `docs/changelog.d/` 里写一行「旧写法仍在/已移除」。

## 不许做

- 不许靠「反正两个都能跑」放着不管（这正是本卡要消的那条歧义）。
