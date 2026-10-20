# 四类判据（classify）—— 怎么认 A / B / C / D

> 判据全部落在「**文件在不在**」上，不依赖人的口头描述。
> 机器执行体是 `tools/wb_takeover.py`；这份表是它每条读数的人读版。

## 判定优先级

**A → D → B → C**：自己的管线最优先；没有自己的、先认别人的框架（D）；都没有、再借对方的测试与
CI（B）；什么都不沾就是裸仓（C，兜底类，含空目录）。

## A · 已有完整管线

「怎么认」的可执行读数（任一成立即 A）：

| 读数 | 信号 |
|---|---|
| `own_pipeline_config` | 仓根有 `pipeline.toml` 或 `harness.toml` |
| `own_trio` | 三件套齐：`docs/workbacklog.toml` + `gates/last.json` + `tools/wb_*.py` 至少一个 |

含义：门表、队列、台账都已有人在维护 ⇒ **不铺骨架**，新工作项直接进对方队列文件。

## B · 有测试无门禁

A 不成立，且下列任一成立：

| 读数 | 信号 |
|---|---|
| `tests` | `tests/` 目录、`pytest.ini`、`pyproject.toml`、`tox.ini` 任一；或 `package.json` 的 `scripts` 段有 `test` |
| `ci` | `.github/workflows/`、`Makefile`、`.gitlab-ci.yml`、`Jenkinsfile` 任一 |

含义：有门可借 ⇒ 先按 [映射表](mapping.md) 把 CI job / 测试报告翻译成门 / 证据，再铺最小骨架。

## C · 裸仓

A / D / B 的信号**全无**（有 `src/` 算 C；空目录也算 C）。

含义：没门可借 ⇒ 铺最小骨架（骨架配置 + 队列壳 + 台账壳 + 至少一道真门，**只加文件**）。

## D · 别人的框架

A 不成立，且检出别家 agent 框架标记（任一）：

`CLAUDE.md` · `.claude/` · `.cursor/` · `.cursorrules` · `.windsurfrules` · `.aider.conf.yml` ·
`.github/copilot-instructions.md`

含义：它已经在别人的 harness 下跑 ⇒ **只勘察、不落任何文件**；要接也是先对齐别人的框架，
不把我们的骨架铺进去。

## 常见误判

- 「有 git 仓库、有 README」**不构成**任何一类的信号 —— 看的是上表的具体文件。
- D 的信号压过 B：有 `tests/` 又有 `CLAUDE.md` ⇒ 判 D（先认框架，再谈借测试）。
- A 压过一切：仓里既有 `harness.toml` 又有 `CLAUDE.md` ⇒ 判 A。
- 对方「我们有 CI」但没判 B ⇒ 多半是它的 CI 形态不在信号清单里；加新信号要升级为一张卡，
  不许现场扩判据。
