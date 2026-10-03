# skills —— 框架自带的人机接口（薄适配层）

> 这一层是**核心之上的薄适配层**：它把「怎么用 `pipe` CLI 才不出错」教给 agent（和人）。
> ★ 本层的判据：**删掉整个 `skills/` 目录，框架仍然完整可用。** 做不到，就说明判据漏进 skill 了。

## 定位

- 框架本体 = 核心库（`framework/src/framework/**`）+ 薄 CLI（`framework/cli/main.py`）+ 模板仓 + 例子。
- skills = **只有操作知识**的一层：顺序、前置检查、常见错、该看哪个产物。
- ★ skills 包的是**真实存在的命令**：`pipe init` · `pipe gate` · `pipe doctor` · `pipe card new` · `pipe claim` · `pipe land` · `pipe ledger check` · `pipe trace seal`。命令面以 `pipe --help` 为准，**不凭设计书想象命令名**。

## §1 ★ 分工判据：这东西该放哪

| 这东西该放哪 | 判据 |
|---|---|
| **核心库**（`framework/src/framework/**`） | 逻辑与判据；不 `print`、不 `sys.exit`；换个前端照样成立 |
| **CLI 子命令**（`pipe <命令>`） | 人 / 机器都能用的**稳定契约**：参数 / 输出 / 退出码 / `--json` |
| **skill**（本目录） | ★ **只有**「怎么用 CLI 才不出错」这层**操作知识**：顺序、前置检查、常见错、该看哪个产物 |
| **不许进 skill** | 任何**判据本身**、任何**业务逻辑**、任何**只能在这一个 harness 里成立**的东西 |

### 反例（放错会怎样）

1. **把一条判据塞进 skill** ⇒ 判据只在那个 harness 里成立，**换 harness 就没了**；而且库里、门里、skill 里各留一份，必漂。判据的唯一落点 = 库 / 门。
2. **把一条操作知识留在库里** ⇒ **库被迫知道交互顺序**（顺序、前置检查、常见错都是「怎么调」的事），于是「换个前端照样成立」这条判据破了 —— 库本不该知道谁先跑、谁后跑。
3. **把 harness 胶水塞进核心库 / CLI** ⇒ 换 harness 要**改库**；库就被一个 runtime 绑死，泛用性最差。
4. **把 skill 当"判据真源"** ⇒ 删掉 `skills/` 后框架判据缺失 ⇒ 触发本层自检（删掉 skills 框架仍完整）失败。

**一句话分界**：**判据 → 库 / 门；怎么用 → skill；换个 harness 要改的 → 只许集中在 `GLUE-harness.md`。**

## §2 skills 清单

| skill | 覆盖的动作 | 包的 CLI |
|---|---|---|
| `pipe-init` | 铺骨架 | `pipe init` |
| `pipe-gate` | 跑门禁并读懂三值判决 | `pipe gate` |
| `pipe-card` | 写卡 / 认领 / 申报 | `pipe card new` · `pipe claim` |
| `pipe-land` | 集成与发布 | `pipe land` |
| `pipe-forensics` | 出事了从证据里查 | `pipe gate` · `pipe doctor` · `pipe ledger check` · `pipe trace seal` |

## §3 ★ 换 harness 要改什么（清单式）

**通用的（一个字不改）：**

- 每个 `SKILL.md` 的正文：什么时候用 / 什么时候别用 / 前置检查 / 真命令 / 怎么读结果 / 常见错与处置。只要 CLI 契约不变，这些就是**跨 harness** 的。
- 本 README 的 §1 分工判据、§4 版本对齐。

**每个 harness 的胶水（要改的这几处；★ 全部集中在 `GLUE-harness.md`，别处不许出现）：**

- **G1 注册方式** —— 把 `skills/` 目录指给该 harness 的 skill 扫描根 / 注册接口。
- **G2 目录约定** —— skill 放哪个目录、`SKILL.md` 的文件名与目录束层级。
- **G3 frontmatter 字段名** —— 哪些键必填、哪些键会被拒（不同 harness 不同）。
- **G4 触发机制** —— 自动加载 vs `/点名`，以及「描述进不进上下文」。
- **G5 调用入口** —— CLI 怎么被 harness 调起（PATH 上的 `pipe`，还是 `python framework/cli/main.py`）。
- **G6 沙箱 / 权限** —— 该 harness 下跑 CLI 需要的权限档与工作目录。

★ 除这六条外，**任何 harness 特有的路径 / 工具名都不许进 skill 正文**（卡 §三条硬要求 1）。

## §4 版本对齐

- **框架版本**：`framework/pyproject.toml` 里的版本（现为 `0.1.0`）。
- **skills 版本**：跟框架**同版** —— 本目录随框架版本一起动；本版 = `0.1.0`。
- **契约**：`SKILL.md` 里引用的每个命令名，必须能在**同版** `pipe --help` 里找到（钉子①机器判）。
- **兼容规则**：CLI **加**命令 / 加字段 = 次版本（skills 可照旧，钉子仍绿）；**删**命令 / **改**命令名 / 改退出码表 = 主版本（skills 必须同版改，否则钉子①红）。

## §5 钉子（怎么自证）

两道钉子都在 `nails/`，都**只读**、可用退出码判读（`0` 绿 / `1` 红）：

```bash
python skills/nails/check_commands.py    # ① skills 里引用的命令名，都能在 CLI 帮助里找到
python skills/nails/check_skills.py      # ② SKILL.md 有 frontmatter（name + description）且含「什么时候别用」
```

- 钉子①：扫 `skills/**/SKILL.md` 里代码段 / 围栏 / 标题中的 `pipe <命令>`，与 CLI 的 `--help`（含各子命令）对账；引用不存在的命令或子命令 ⇒ 红。
- 钉子②：扫每个 `SKILL.md`：缺 frontmatter、缺 `name` / `description`、`name` 不是 kebab-case 或与目录名不符、或缺「什么时候别用」（以及其余必需小节）⇒ 红。

## §6 边界（如实写）

- skills **只有操作知识**；**框架能不能用，不由 skills 证明** —— 那是框架自己门禁的事（卡 181）。
- 命令面里有几个是**薄壳**（`claim` / `land` / `ledger check` / `trace seal`）：签名在、行为未建，调用即退 `5`。skill 里**如实标注**了，没拿「未实现」冒充「通过」。
- 本层**不绑某个 harness**：harness 特有值只在 `GLUE-harness.md`。
