# 卡 167 —— 派活器 `--effort` 透传：让"思考等级 MAX"有落点（T-G267）

**树**：`.wt/effort` ｜ **提交**：★ **不要 commit** ｜ **模型**：默认
**成员号**：任务 `B-EFFORT` 的 **M-1**

## 来路（用户 2026-10-03 的令）

> 「我希望你把这些层次全部扔给 **V4.1 的便宜工人**，让他们进行**深度思考。思考等级为 MAX**。」

**现状（核过，不是猜）**：CLI 支持 `--effort <minimal|low|medium|high|xhigh|max>`（从 `codebuddy --help` 的模型/参数清单里核出），
但 `tools/wb_dispatch.py` **刻意不传**它 —— 文件里两处注释写着：

```
line 64:  `--effort` **不加**（保持默认 High）；两条都对着 CLI 2.158.0 的 `--help` 核过。
line 394: 用户 2026-09-26 定：上下文窗口按 1M 自动压缩（`--effort` 不加 = 保持默认 High）
```

⇒ **不传 = 默认 High**。要跑 **MAX** 就必须加一条透传。

## 要做什么（小改，别扩权）

1. **新增 `--effort <level>` 参数**，值域**按 CLI 的白名单硬校验**：`minimal / low / medium / high / xhigh / max`；
   非法值 ⇒ **退 2、零副作用、点名合法值**（照 `--model` 闸门那套写法）。
2. **缺省行为一字不变**：不给 `--effort` ⇒ **仍然不传**（保持"默认 High"这条 2026-09-26 的口径）。
   ★ 不许把默认改成显式 `high` —— 那会改变现有每一笔的行为。
3. 透传到 `build_command` / `resume_command`（**续跑也要带上**，否则续跑那一轮掉回 High）。
4. `--help` 文案要与代码常量**同源**（本仓有一条老坑：help 文案与常量漂了）。

## 判据（每条都要反例钉子）

- ① `--effort max` ⇒ 生成的命令行里**真的出现** `--effort max`；
- ② **不给** `--effort` ⇒ 命令行里**没有** `--effort`（逐字与今天一致）；
- ③ `--effort 玄学` ⇒ 退 2、不起进程、不建 log、**点名合法值**；
- ④ **续跑**（`--resume`）也带 `--effort`；
- ⑤ help 文本里的值域与常量**同源**（改常量即改 help，或用同一处常量渲染）。

## 验收（真读数）

- `python -X utf8 tools/wb_dispatch.py --card 000 --effort max`（干跑）⇒ 打印的 `[cmd]` 里能看到 `--effort max`；
- 同样干跑**不带** `--effort` ⇒ `[cmd]` 里**没有**它；
- `--effort 玄学` ⇒ 贴退 2 的**原样输出**；
- `pytest tests/test_wb_dispatch.py --no-cov` 全绿；`ruff check tools tests` 干净。

## 边界（如实写）

- 本卡**只加透传**，**不改**任何既有默认值、不改 429 轮换链、不改 `--max-turns`。
- 「MAX 会不会更贵/更慢」**本卡不判断** —— 那是主控与用户的账；本卡只保证"能传下去"。
- 值域**以 CLI `--help` 为准**（本卡核到的是 6 档）；CLI 若新增档位，本卡不预判。
