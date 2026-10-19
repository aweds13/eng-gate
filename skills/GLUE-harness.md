# GLUE-harness —— 唯一允许写 harness 特有内容的地方

> ★ 本文件是 skills 层里**唯一**集中放 harness 胶水的地方（卡 §三条硬要求 1）。
> 除本文件外，任何 `SKILL.md` / `README.md` 都**不许**出现某个 harness 特有的路径 / 工具名作为前提。
> 换 harness = 改本文件（或照本文件的形状重写一份），**不动任何 `SKILL.md`**。

## 当前样本：DSH（CodeBuddy / DeepSeek 一族）—— 只作样本，不作前提

> 出处：本仓 `DSH-技能与插件开发参考.md`（本仓对 skill 格式最权威的一份参考）。
> ★ 下面这些**全是胶水**：换 harness 就换掉，别当通用知识。

| 编号 | 胶水项 | DSH 下的值（样本） |
|---|---|---|
| G1 | 注册方式 | 扫描根 + `ctx.skills` provider；把技能目录放进扫描根即被发现 |
| G2 | 目录约定 | 目录束 `<root>/<技能名>/SKILL.md`（也可平铺 `<root>/<技能名>.md`）；扫描根按 rank 100 / 200 / 300 / 400 / 500 排优先级，数字越小越优先 |
| G3 | frontmatter 字段 | 必填 `name`（kebab-case）+ `description`；可选 `whenToUse`（**驼峰**，写 `when-to-use` 会被静默忽略）；旧键 `modelInvocable` / `userInvocable` / `disableModelInvocation` 会**抛错** |
| G4 | 触发机制 | `description` 是触发器（模型靠它决定加载）；`/点名` 在直接用户消息里扫描；`disable-model-invocation: true` 可挡自动加载 |
| G5 | 调用入口 | 在本仓根用 `python framework/cli/main.py <命令>`；装包后 `pipe <命令>`。harness 只要能把它起成子进程即可 |
| G6 | 沙箱 / 权限 | 写权限按工作区；读不受限；跑 CLI 时的工作目录 = 仓库根 |

## 换 harness 的检查单

- [ ] G1 —— 把 `skills/` 指给新 harness 的注册方式
- [ ] G2 —— 核对新 harness 的目录约定与 `SKILL.md` 文件名
- [ ] G3 —— 核对新 harness 的必填 / 被拒 frontmatter 键
- [ ] G4 —— 核对触发机制（自动加载 vs 点名）
- [ ] G5 —— 核对 CLI 调用入口（`pipe` 在不在 PATH）
- [ ] G6 —— 核对权限档与工作目录
- [ ] 改完**不动任何 `SKILL.md`**（若被迫改，说明胶水漏进正文了 —— 那是 bug）

## 复盘缺口（外部调用两条）

- （缺口 EX1）MCP / 外部调用要开子进程并设超时：长任务冻住 stdio 等于把宿主一起冻死 —— 接新 harness 的外部调用时核对它是子进程 + 有超时（本仓样本：`tools/mcp_client.py`），stdio 直连且没超时的接法不许过。
  证据：`复盘/卡/卡130-MCP收申请改子进程.md`、`复盘/MCP与写操作-T-G65.md`、`复盘/独立MCP客户端-T-G78.md`
- （缺口 EX2）局域网接入用一次性配对码换会话令牌，令牌不许进 URL / 日志 / 证据指针 —— 接局域网能力时核对令牌落点：只在内存 / 本地配置，不写进任何会落盘或被引用的地方。
  证据：`复盘/局域网访问与配对码-T-G10b.md`、`复盘/坑总账.md`、`复盘/文档重整方案.md`
