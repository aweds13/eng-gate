# pipe-takeover —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、边界在哪。
> ★ 这里不写判据 —— 判据在 `tools/wb_takeover.py`。删掉整个 `skills/`，框架仍要可用。
>
> 三层：元数据 → 正文（顺序 + 前置检查，≤120 行）→ `references/`。
> 长表在 [定类](references/classify.md) · [映射](references/mapping.md) · [限制](references/limits.md) ·
> [接链六步](references/attach-to-chain.md)；本仓的路径与读数在 [本仓绑定](references/repo-bindings.md)。

## 这一层在防哪类错误

防「**没分类就动手**」「**把本仓特例当通用**」和「**骨架铺进对方主干**」。

接手一个旧项目时，最常见的失败不是改错代码，而是**先动再理解**：不知道对方有没有门禁、
测试算不算数、哪些文件不能碰，结果把脚手架提交进别人的仓库，或者把「能跑」当成
「接住了」。这张技能把顺序钉死：先只读勘察定类（A/B/C/D），再出映射表，最后套限制
清单；每一步有读数、能被人复核。

## 为什么顺序不能换

- **先定类**：A 类（已有完整管线）只需要对齐命令；C 类（裸仓）才需要铺骨架。
  类别不同，动作完全不同 —— 先动手等于赌。
- **先映射**：自然语言约定（「跑测试」）落到哪个命令，必须显式写下来；
  没写 = 没约定（`none` 是一等值）。
- **先限制**：禁止清单要在派活**之前**生效，事后补等于没禁。

## 与别的技能的关系

- 落骨架用 `pipe-init`（本技能只判断「该不该铺、铺哪一种」）。
- 开卡与派活用 `pipe-card` / `softeng-manage` 的派活节。
- 判「过不过门」用 `pipe-gate`；本技能不判断门本身。

## ★ 为什么分「SKILL.md / references/repo-bindings.md」两页（2026-11-08）

**问题**：这一页原来把本仓的勘察器路径、A 类读数（本仓有 `harness.toml` 与三件套）、
卡登记目录、骨架文件数、快照命名全写在 `SKILL.md` 正文里。换个仓整页作废 ——
用户原话：「现在它们只针对 engineer 这个仓库，是不够的」，「特定仓库表述下降到原来更下一层的 reference」。

**判据**（`docs/reference/agent-skills-spec.md` §5 三层渐进加载 / §6 引用只深一层 /
§8「稳定的写死、随环境变的留成参数」/ §9 第 ⑤ 条「长表下沉 references」）：

| 放哪 | 放什么 | 判据 |
|---|---|---|
| `SKILL.md` | 动作顺序、判据入口、读 JSON 的方法、常见误读 | 换一个仓，**一个字都不用改** |
| `references/repo-bindings.md` | 本仓形态（A 类 / 两套入口 / 工具根数据根）、勘察器路径、骨架 14 个文件、卡登记位置、快照形状 | 换仓**只改这一份** |

**搬走了什么**（行号是搬走前 `SKILL.md` 的行号）：`:30` 「本仓勘察结果应是 A」、`:39` 勘察器路径、
`:44` JSON 键的数目与名单、`:46`/`:78` 的 `skills/pipe-takeover/references/…` 全路径、
`:82` 的 `class`/`signals` 键名（错，已改正）、`:88` 的跨技能路径、`:50` 在本仓根没有 `pipeline.toml` 的前提。

## 失败过什么（带读数）

- **把「能跑测试」当成接住了**：某项目 `pytest` 绿，但 90% 用例是 skip，`-q` 的摘要
  只写 passed。判据：`pytest --collect-only -q` 与实际 passed 数对比，skip 率 >50% 记黄。
- **骨架提交进对方主干**：铺 `pipeline.toml` 时直接 commit 到 `main`，对方 CI 立刻红。
  现在限制清单第 1 条要求隔离分支，勘察器只读不写，落地前必须人工确认。
- **映射写成省略**：约定「跑门禁」没写落到哪个命令，工人自己发明了一个。现在 `none`
  是一等值，省略即非法。
- **键名写错被实测纠正（2026-11-08）**：`SKILL.md` 曾写「JSON 五个字段」并列出
  `kind/readings/mapping_hints/strict_ok/strict_problems`，且六步表写 `class`/`signals`。
  实跑 `python -X utf8 tools/wb_takeover.py --root . --json` ⇒ 非 strict **恰 5 键**
  `ok/root/kind/readings/mapping_hints`；`--strict --json` ⇒ 7 键；每条 reading 的键是
  `name/ok/detail`。教训：**字段名要跑一次再写**，别凭印象列清单。

## 脚本接口与以后怎么改

`tools/wb_takeover.py` 只有一条命令：

```
python -X utf8 tools/wb_takeover.py --root <目录> [--json] [--strict]
```

- 输出：`{ok, root, kind, readings[], mapping_hints[]}`（`--strict` 多 `strict_ok` / `strict_problems`）；
  `kind ∈ {A,B,C,D}`。
- 判据全部在 `classify()` 与 `strict_problems()` 里，一条判据一个 `reading`（`name/ok/detail`）。
- 加一类形态：在 `classify()` 加一组 `reading` 与 `kind` 常量，再在
  `tests/test_wb_takeover.py` 里造一个临时目录钉住它。
- 只读约定：函数内不许 `write_text` / `mkdir` / `subprocess`；这条由
  `tests/test_wb_takeover.py` 的源码扫描钉住。
