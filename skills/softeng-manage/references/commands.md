# 本仓命令速查（六段流水线）

> `softeng-manage/SKILL.md` 的按需参考。**这里不写判据** —— 每段的「怎样算成」在对应工具里；
> 本表只给命令与产物名，防止把 `pipe` CLI 的想象命令敲进终端。

## ① 开卡

```bash
python -X utf8 tools/wb_plan.py plan --concurrency 2   # 排批（只认 status=pending）
```

- 卡规格：`复盘/卡/卡<ID>-<短名>.md`，四段固定：问题 / 改法 / 判据 / 证据。
- 队列：`docs/workbacklog.toml`，字段 `id / task / title / tree / spec / files / depends / risk / status`。
- `status`：`pending` 可派 · `done` · `failed`。

## ② 派活

```bash
git worktree add .wt/<卡号> -b card/<卡号>
python -X utf8 tools/wb_dispatch.py --card <卡号> --spec <规格> --cwd .wt/<卡号> \
    --model <短名> --detach --execute
python -X utf8 tools/wb_dispatch.py --card <卡号> --status
```

- 模型名用**短名**；写 `vendor/model` 会被拒。
- 派活产物落在**主仓** `gates/diag/`（gitignored，卡树里没有）。

## ③ 跑门

```bash
python -X utf8 scripts/run_gates.py --fast     # 内循环（不落盘）
python -X utf8 scripts/run_gates.py            # 全量（提交前）
python -X utf8 scripts/audit_progress.py       # 台账 / 证据审计
```

结论在 `gates/last.json`（`ok` / `rev` / `gates[]` / `not_run` / `reused`）。

## ④ 落地

```bash
python -X utf8 tools/wb_land.py --card <卡号> --tree .wt/<卡号> --task <台账号> \
    --title "<一句话>" --type feat --scope <域> \
    --allow <文件>... --evidence <指针>... --port-base <端口段>
```

八步链：⓪回退派生物 → ①迁树 → ②文书 → ③sync_counts → ④门禁 → ⑤seal →
⑥白名单提交 → ⑦audit + ff → ⑧复核落盘。

## ⑤ 巡检

```bash
python -X utf8 tools/wb_daily.py                # 今日一页
python -X utf8 tools/pipeline_view.py --report  # 六块读数
python -X utf8 tools/wb_dash.py                 # 工人面板（只读本地页）
```

## ⑥ 复盘 / 对账

```bash
python -X utf8 tools/wb_verify.py --tree .      # 这一笔算不算数
python -X utf8 tools/wb_reconcile.py            # 队列 vs git
python -X utf8 tools/wb_diag.py gates/diag/wb-<卡>.jsonl   # 工人日志失败定位
```

## 附：技能自身

```bash
npx -y skills-ref@latest validate ./skills/<名>     # 官方校验器
python -X utf8 skills/nails/check_skills.py         # 格式钉子
python -X utf8 skills/nails/check_commands.py       # 命令名钉子
python -X utf8 tools/dsh_skills_link.py --check     # 注册（junction，零副本）
```
