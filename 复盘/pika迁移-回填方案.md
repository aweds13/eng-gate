# pika 迁移回填方案（新版 2.1.7 ← 旧版 2.1.4 的个性化配置）

> **操作部分已由 `docs/runbooks/pika-升级规程.md` 接管（2026-11-09，卡 B9 / T-BG011）。**
> 本文保留为**当时的证据**：每一条读数都是 2026-11-01 实测的，不随规程更新。
> 要动手请读规程，不要照本文分步走 —— 本文至少四处与实测不符（「DSH 技能根 6 个已装」实为 7 个；
> `%APPDATA%` 那份 config 的字节数；§5 B5 的三个 0 字节 `SKILL.md`；§3.1 改 env 的方向与实测相反）。

> 逐行可审版。每条都给出「旧版哪一行 → 新版哪一行 → 回填后是什么」。
> **所有「旧版」引用一律以 `pika_math_learning_toolkit-2.1.4.zip` 为准**，不读 `C:/Users/example/.dsh/skills/` ——
> 那 71 个文件已在 2026-10-31 19:53 的一次误操作里被写成新版内容了（见 §7 事故记录）。
> 选手册：`_tools/pika-迁移/inventory/勘察报告.md`、`b3_fullhash.json`、`root_map.json`。

| 项 | 值 |
| --- | --- |
| 知识根 | `D:/repo` |
| 外层包（只读） | `D:/downloads\pika文件_Pro.zip`（2411 条目 / 1.4 GB / stored） |
| 新版包 | `pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip`（2026561 B / 488 条目） |
| 旧版包 | `知识库\pika文件_Pro\AI工具\pika_math_learning_toolkit-2.1.4.zip`（1367591 B / 339 条目） |
| DSH 技能根 | `C:/Users/example\.dsh\skills\`（6 个已装，缺 `compute-fleet-manager`） |
| 迁移脚本 | `tools/pika_migrate.py`（默认 dry-run） |
| 实测口径 | 3755 条命中里 3697 条 SAME、74 条 DIFF、281 条新版独有、22 条无映射根 |

---

## 0. 一句话结论

**这个包里没有「个性化配置」需要回填到 skill 代码里。** 用户的个性化（知识库根目录、题库路径、本机绝对路径）
全部活在 skill **之外**的两份 JSON 配置 + 三个用户环境变量里，而新版读写这些配置的**键名一个都没变**。
真正需要动手的只有 4 处「结构变了」的代码差异和 1 处必须保持不动的配置，见 §3。

如果直接照「把旧配置合进新代码」的直觉去改，会踩到的坑是：改错文件、改出死路径、把用户的 Obsidian 字体覆盖掉。

---

## 1. 个性化配置到底在哪（先定位，再谈回填）

### 1.1 三个用户环境变量（注册表 User 域，Machine 域 0 条）

| 变量 | 值 | 存在性 |
| --- | --- | --- |
| `OBSIDIAN_LOCAL_KB_ROOT` | `C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb` | ✅ |
| `OBSIDIAN_VAULT_NOTES_CONFIG` | `C:/Users/example\AppData\Roaming\pika_math_learning_toolkit\obsidian-vault-notes.json` | ✅ 260 B |
| `OBSIDIAN_LOCAL_KB_DB` | `C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3` | ⚠️ 存在但**已成死库**，见 §5-A2 |

其余相关变量**全部未设**：`OBSIDIAN_VAULT_ROOT`、`OBSIDIAN_LOCAL_KB_DATA_ROOT`、`PDF_PROBLEM_SEARCH_ROOT`、
`PERSONAL_KNOWLEDGE_ROOT`、`MPK_CONFIG_PATH`、`MPK_STATE_DIR`、`MPK_SKILLS_ROOT`、`CODEX_HOME`。

> **这三条 env 优先级高于任何配置文件**。这意味着：即使配置文件写错，只要 env 对，技能就能跑。
> 反过来，改了配置文件但这三条 env 没动，**行为不会变**。这是本次最容易误判的点。

### 1.2 活配置 A —— obsidian-vault-notes（`OBSIDIAN_VAULT_NOTES_CONFIG` 指向）

`C:/Users/example\AppData\Roaming\pika_math_learning_toolkit\obsidian-vault-notes.json`（260 B，6 行）

```
2|  "schema_version": 1,
3|  "vault_root": "D:/repo\\知识库",
4|  "kb_root": "C:/Users/example\\.dsh\\skills\\obsidian-vault-notes\\scripts\\obsidian_local_kb",
5|  "db_path": "C:/Users/example\\AppData\\Local\\obsidian-vault-notes\\vault.sqlite3"
```

### 1.3 活配置 B —— manage-personal-knowledge（schema 2）

`C:/Users/example\AppData\Roaming\manage-personal-knowledge\config.json`（474 B，20 行）

```
2|  "knowledge_root": "D:/repo",
3|  "knowledge_root_id": "KBROOT-442OME7QWTER5T5W7OO7RGNPB4",
4|  "knowledge_root_name": "jelly_ware",
6|  "excluded_relative_paths": [],
7|  "manifest_relative_path": ".mpk/resources.jsonl",
9|  "schema_version": 2,
12|    "kind": "pdf-library",      13|    "relative_path": "Library",
16|    "kind": "obsidian-vault",   17|    "relative_path": "知识库"
```

配套：`D:/repo\.mpk\root.json`（4 行，id/name/schema_version 1）、
`.mpk\resources.jsonl`（1 行 manifest，`generation: 0`）。

### 1.4 三个死配置（**不要改，也不要当成活配置**）

| 路径 | 大小 | 为什么是死的 |
| --- | --- | --- |
| `AppData\Roaming\obsidian-vault-notes\config.json` | 313 B | 被 `OBSIDIAN_VAULT_NOTES_CONFIG` 压过；且其 `kb_root` 指向 `D:\Hermes Agent CN Desktop\...\obsidian_local_kb`，**该目录已不存在** |
| 同名 `.bak-20261024-102212` | 313 B | 与上者逐字节相同，是它的备份 |
| `AppData\Roaming\manage-personal-knowledge\obsidian-vault-notes.json` | 313 B | mpk 的 companion 副本（`setup_local.py:56` 同步写），内容与上者 IDENTICAL，同样指向死路径 |

### 1.5 skill 代码里有没有本机绝对路径？——几乎没有

对 `C:/Users/example/.dsh/skills/` 全树 grep `jelly_ware` → **0 命中**；grep `D:/docs` / `D:文档` → **0 命中**。
122 条形如 `C:\...` 的命中里，真代码级只有两条：

| 文件 | 行 | 内容 | 性质 |
| --- | --- | --- | --- |
| `manage-personal-knowledge/scripts/manage_personal_knowledge/ocr.py` | 20 | `DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")` | 第三方工具默认位，新旧**完全一致** |
| `manage-personal-knowledge/scripts/manage_personal_knowledge/text.py` | 227, 232 | `Path(os.environ.get("ProgramFiles", r"C:\Program Files"))` | 系统变量兜底，新旧**完全一致** |

⇒ **结论：没有任何「旧版写死了本机路径、新版需要补回去」的情况。** 用户记忆里的「个性化设置」实体就是 §1.2 / §1.3 那两份 JSON。

---

## 2. 逐 skill 比对：配置项与结构变化

### 2.1 `obsidian-vault-notes`（v1.13.3 → v1.13.5）—— 删了一个解析候选

**旧版** `C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\_common.py`（2.1.4 里 4189 B / 128 行）

```
 89| VAULT_KB_ROOT = DEFAULT_VAULT_ROOT / "scripts" / "obsidian_local_kb"
 90| LEGACY_KB_ROOT = Path.home() / "Documents" / "obsidian_local_kb"
 93| def resolve_kb_root() -> Path:
 94|     env_root = os.environ.get("OBSIDIAN_LOCAL_KB_ROOT")
 95|     return resolve_existing_path(
 96|         [
 97|             Path(env_root) if env_root else None,
 98|             configured_path(LOCAL_CONFIG, "kb_root"),
 99|             BUNDLED_KB_ROOT,
100|             VAULT_KB_ROOT,          ← 新版删掉这一项
101|             LEGACY_KB_ROOT,
102|         ]
103|     )
```

**新版** `_extracted/pika_math_learning_toolkit-2.1.7/payload/obsidian-vault-notes/scripts/_common.py`（4093 B / 123 行）

```
 89| LEGACY_KB_ROOT = Path.home() / "Documents" / "obsidian_local_kb"    ← VAULT_KB_ROOT 整行删除
 92| def resolve_kb_root() -> Path:
 93|     env_root = os.environ.get("OBSIDIAN_LOCAL_KB_ROOT")
 94|     return resolve_existing_path(
 95|         [
 96|             Path(env_root) if env_root else None,
 97|             configured_path(LOCAL_CONFIG, "kb_root"),
 98|             BUNDLED_KB_ROOT,
 99|             LEGACY_KB_ROOT,          ← 原 L101 上移到 L99
100|         ]
101|     )
```

| 项 | 旧 | 新 | 回填动作 |
| --- | --- | --- | --- |
| `VAULT_KB_ROOT` 常量 | L89 定义 | **不存在** | 无需回填（这是包内自定位路径，不是用户配置） |
| `resolve_kb_root()` 候选数 | 5（L96-101） | 4（L96-99） | 无需回填 |
| `resolve_note_db_path()` | L106-117 | L104-115，**逐字节相同** | 无需回填 |
| 生效的 `kb_root` | env 第 1 顺位命中 | 同左 | **实测新旧解析结果完全相同** |

**实测（`inventory/_scripts/resolve_probe.py` 分别 import 新旧两版纯函数）**

| 返回值 | 旧版 | 新版 |
| --- | --- | --- |
| `LOCAL_CONFIG` | `AppData\Roaming\pika_math_learning_toolkit\obsidian-vault-notes.json` | 相同 |
| `DEFAULT_VAULT_ROOT` | `D:/repo\知识库` | 相同 |
| `resolve_kb_root()` | `C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb` | 相同 |
| `resolve_note_db_path()` | `AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3` | 相同 |

⇒ **这一对 skill 是「结构变了但结果不变」**：删掉的候选本来就被 env 挡在前面，从未生效。
**回填动作：无。** 但要在验收时保留这条实测结论，免得日后有人以为删候选会改行为。

---

### 2.2 `pdf-problem-search`（v1.12.2 → v1.12.3）—— ★真正的结构变化：env → JSON 键

这是本次唯一一处「新版换了配置来源」的地方，必须按新结构映射，**不能把旧 env 塞回去**。

**旧版** `pdf-problem-search/scripts/pdf_problem_search/paths.py`（7456 B / 220 行）

```
 48| def resolve_project_root(script_path: Path | None = None) -> Path:
 49|     vault_root = infer_vault_root(script_path)        ← 靠「目录形状猜」
 50|     env_root = os.environ.get("OBSIDIAN_LOCAL_KB_ROOT")
 51|     pdf_search_root = os.environ.get("PDF_PROBLEM_SEARCH_ROOT")
 52|     pdf_search_project = Path(pdf_search_root) / "scripts" / "obsidian_local_kb" if pdf_search_root else None
 53|     vault_project = vault_root / "scripts" / "obsidian_local_kb" if vault_root else None
 54|     return resolve_existing_path(
 55|         [
 56|             Path(env_root) if env_root else None,
 57|             pdf_search_project,
 58|             vault_project,
 59|             legacy_project_root(),
 60|         ]
 61|     )

 64| def resolve_data_root(script_path=None, project_root=None) -> Path:
 65|     env_data_root = os.environ.get("OBSIDIAN_LOCAL_KB_DATA_ROOT")
 66|     project = project_root or resolve_project_root(script_path)
 67|     vault_root = infer_vault_root(script_path)
 68|     vault_data = vault_root / "scripts" / "obsidian_local_kb" / "data" if vault_root else None   ← 新版删
 69|     candidates = [
 70|         Path(env_data_root) if env_data_root else None,
 71|         project / "data",
 72|         vault_data,                                     ← 新版删
 73|         legacy_project_root() / "data",
 74|     ]
```

**新版** `D:/repo\_tools\pika-迁移\_extracted\pika_math_learning_toolkit-2.1.7\payload\pdf-problem-search\scripts\pdf_problem_search\paths.py`（8598 B / 232 行）

```
  3| import json                                          ← 新增
 35| def infer_knowledge_root() -> Path | None:            ← ★全新函数
 36|     explicit = os.environ.get("PERSONAL_KNOWLEDGE_ROOT")
 37|     if explicit:
 38|         return Path(explicit).expanduser().resolve()
 39|     configured_path = os.environ.get("MPK_CONFIG_PATH")
 40|     if configured_path:
 41|         config = Path(configured_path).expanduser()
 42|     else:
 43|         if sys.platform.startswith("win"):
 44|             base = Path(os.environ["APPDATA"]) if os.environ.get("APPDATA") else Path.home() / "AppData" / "Roaming"
 45|         elif sys.platform == "darwin":
 46|             base = Path.home() / "Library" / "Application Support"
 47|         else:
 48|             base = Path(os.environ.get("XDG_CONFIG_HOME")).expanduser() if ... else Path.home() / ".config"
 49|         config = base / "manage-personal-knowledge" / "config.json"
 50|     try:
 51|         payload = json.loads(config.read_text(encoding="utf-8-sig"))
 52|     except (OSError, UnicodeError, json.JSONDecodeError):
 53|         return None
 54|     value = payload.get("knowledge_root") if isinstance(payload, dict) else None
 55|     return Path(value).expanduser().resolve() if isinstance(value, str) and value.strip() else None

 72| def resolve_project_root(script_path: Path | None = None) -> Path:
 73|     knowledge_root = infer_knowledge_root()                                    ← 新来源
 74|     env_root = os.environ.get("OBSIDIAN_LOCAL_KB_ROOT")
 75|     pdf_search_root = os.environ.get("PDF_PROBLEM_SEARCH_ROOT")
 76|     pdf_search_project = Path(pdf_search_root) / "scripts" / "obsidian_local_kb" if pdf_search_root else None
 77|     knowledge_project = knowledge_root / "scripts" / "obsidian_local_kb" if knowledge_root else None
 78|     sibling_project = infer_skill_root(script_path).parent / "obsidian-vault-notes" / "scripts" / "obsidian_local_kb"
 79|     return resolve_existing_path(
 80|         [
 81|             Path(env_root) if env_root else None,
 82|             pdf_search_project,
 83|             knowledge_project,        ← 新
 84|             sibling_project,          ← 新
 85|             legacy_project_root(),
 86|         ]
 87|     )

 90| def resolve_data_root(script_path=None, project_root=None) -> Path:
 91|     env_data_root = os.environ.get("OBSIDIAN_LOCAL_KB_DATA_ROOT")
 92|     project = project_root or resolve_project_root(script_path)
 93|     candidates = [                    ← vault_data 整体删除
 94|         Path(env_data_root) if env_data_root else None,
 95|         project / "data",
 96|         legacy_project_root() / "data",
 97|     ]
```

**映射表（旧结构 → 新结构）**

| 旧版怎么拿到根 | 新版怎么拿到根 | 回填动作 |
| --- | --- | --- |
| `infer_vault_root()`：从脚本位置向上找 `Obsidian Vault` + `Codex Skills` 目录形状（旧 L49、L67） | `infer_knowledge_root()`：读 `%APPDATA%\manage-personal-knowledge\config.json` 的 **`knowledge_root` 键**（新 L35-55、L73） | **不用改配置**。活配置 B 的 `knowledge_root` = `D:/repo` 已就位，新函数能直接读到 |
| `vault_project = vault_root/"scripts"/"obsidian_local_kb"`（旧 L53） | `knowledge_project = knowledge_root/"scripts"/"obsidian_local_kb"`（新 L77） | 本机 `D:/repo\scripts\` **不存在** ⇒ 该候选永不命中（无害） |
| — | `sibling_project`：`<skills>/obsidian-vault-notes/scripts/obsidian_local_kb`（新 L78） | **本机实际走这条**（§2.1 的 env 也指向同一处） |
| `vault_data = vault_root/.../data`（旧 L68） | 删除 | 不用管 |
| env `OBSIDIAN_VAULT_ROOT` | **不再被 pdf 读取**（新版 pdf 的 env 清单里没有它） | **不要**去设 `OBSIDIAN_VAULT_ROOT` 企图影响 pdf，新版不认 |

**实测（`resolve_probe.py`）**

| 函数 | 旧版 | 新版 |
| --- | --- | --- |
| `infer_knowledge_root()` | *不存在* | **`D:/repo`** ✅ 读 mpk config 成功 |
| `infer_vault_root()` | **`None`**（本机没有 `Obsidian Vault`+`Codex Skills` 形状） | `None`（函数还在，但 `resolve_project_root` 已不用它；仅 `doctor_problem_search.py:18,101` 还调） |
| `resolve_project_root()` | `C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb` | 相同（env 第 1 顺位） |
| `resolve_data_root()` | 同上 `\data`，**exists=False** | 同上，**exists=False** |

⇒ 结论：新版 pdf **确实换了解析机制**（从「猜目录形状」变成「读 mpk 的 `knowledge_root` 键」），
但因为本机有 env 兜底，两条路径最终落到同一处。
**真正的缺口是 `resolve_data_root()` 三个候选全不命中**，见 §5-A1。

---

### 2.3 `manage-personal-knowledge`（v1.11.3 → v1.11.5）—— 1 行路径基准变化

**旧版** `D:/repo\_tools\pika-迁移\_extracted\pika_math_learning_toolkit-2.1.4\payload\manage-personal-knowledge\scripts\migration_check.py` L140（2.1.4 zip，10209 B / 194 行）
```
140|     toolkit = vault / 'scripts/kb-migration-toolkit'
```
**新版** 同文件 L140（10208 B / 194 行）
```
140|     toolkit = root / 'scripts/kb-migration-toolkit'
```
一个变量名从 `vault` 改成 `root`，语义从「Vault 根下」变成「知识根下」。

| 项 | 值 |
| --- | --- |
| 回填动作 | **无**（这是包内工具位置约定，不是用户配置） |
| 实测影响 | `D:/repo\scripts\kb-migration-toolkit` 与 `D:/repo\知识库\scripts\kb-migration-toolkit` **两个都不存在** ⇒ `checks['config_tool_available']` 恒为 `False`，新旧一致 |

其余 mpk 差异（`SKILL.md`、`references/root-migration.md`、`version-coupling-manifest.json`、
`D:/repo\_tools\pika-迁移\_extracted\pika_math_learning_toolkit-2.1.4\payload\manage-personal-knowledge\tests\test_config_discovery.py`）都是**文档与测试**更新，不含用户配置。

`config.py` 新旧**逐字节相同**（这是最要紧的一条）：
`LEGACY_SCHEMA_VERSION=1`(L19)、`SCHEMA_VERSION=2`(L20)、`DEFAULT_MANIFEST_RELATIVE_PATH=".mpk/resources.jsonl"`(L22)、
`_ROOT_ID_PATTERN=^KBROOT-[A-Z2-7]{26}$`(L23)、`SOURCE_KINDS={"vault":"obsidian-vault","library":"pdf-library"}`(L24)、
`get_config_path()`(L39，`MPK_CONFIG_PATH`→L41，`APPDATA`→L45，L52 落 `%APPDATA%/manage-personal-knowledge/config.json`)、
`get_state_dir()`(L55，`MPK_STATE_DIR`→L57，`LOCALAPPDATA`→L61，L68 落 `%LOCALAPPDATA%/manage-personal-knowledge`)。
⇒ **活配置 B 的路径与 schema 在新版下完全兼容，一个字都不用改。**

---

### 2.4 `suite_doctor.py`（mpk，2534 → 2703 B）—— 必报错的一处

**旧版** L22-27（60 行文件）：
```
 22|     required = {
 23|         "manage-personal-knowledge": skills_root / "manage-personal-knowledge" / "SKILL.md",
 24|         "obsidian-vault-notes":      skills_root / "obsidian-vault-notes" / "SKILL.md",
 25|         "pdf-problem-search":        skills_root / "pdf-problem-search" / "SKILL.md",
 26|         "math-science-computation":  skills_root / "math-science-computation" / "SKILL.md",
 27|     }
```
**新版** L22-30（63 行文件）：
```
 22|     required = {
 23|         "manage-personal-knowledge": skills_root / "manage-personal-knowledge" / "SKILL.md",
 24|         "obsidian-vault-notes":      skills_root / "obsidian-vault-notes" / "SKILL.md",
 25|         "pdf-problem-search":        skills_root / "pdf-problem-search" / "SKILL.md",
 26|         "math-science-computation":  skills_root / "math-science-computation" / "SKILL.md",
 27|         "math-coach":                skills_root / "math-coach" / "SKILL.md",          ← 新增
 28|         "math-research-solve":       skills_root / "math-research-solve" / "SKILL.md", ← 新增
 29|         "compute-fleet-manager":     skills_root / "compute-fleet-manager" / "SKILL.md",← 新增
 30|     }
```
必装项 4 → **7**。`skills_root` 取 `MPK_SKILLS_ROOT` env，未设则 `Path(__file__).parents[1].parent`。

| 项 | 值 |
| --- | --- |
| 本机现状 | `.dsh/skills/` 有 6 个，**没有 `compute-fleet-manager`** |
| 迁移后行为 | `suite_doctor.py` 必报 `"status": "missing_skill_payload"`，**exit 1** |
| 回填动作 | 无代码可改 —— 必须把第 7 个 skill 也装上，见 §5-C1 |

---

### 2.5 其余 3 个 skill（math-coach / math-research-solve / math-science-computation）

纯版本升级，**无配置项变化**：

| skill | 版本 | env 变化 | 配置文件 | 回填动作 |
| --- | --- | --- | --- | --- |
| `math-coach` | v1.12.1 → v1.13.0 | 10 个，新旧**同** | 无 | 无 |
| `math-research-solve` | v3.1.11 → v3.2.8 | 3 → 6（+`LOCALAPPDATA`、`MRS_ARCHIVE_PLAYWRIGHT_MODULE`、`XDG_CACHE_HOME`，全在 `mrs_search.py` / `mrs_archive_completion.py`，**均有默认值**） | 无 | 无 |
| `math-science-computation` | v1.11.4 → v1.12.0 | 7 → 14（+6 个 `MSC_*_ROOT` 仅在 zip 内 `…/math-science-computation/tests/test_job_runner.py`（2.1.7 zip 内相对路径；本机未解出该文件）；+`PYTHONPATH` 在 `job_runner.py`，**均有默认值**） | 无 | 无 |

（`compute-fleet-manager` 是全新 skill，本机没有旧版可对；其 env 为 `CODEX_SKILL_OBSERVER_CLI`、`SKILL_EVALUATION_LAB_ROOT`，均可不设。）

---

### 2.6 六个 SKILL.md 的版本与换行符（动手前必须知道）

| skill | 版本 旧→新 | 行数 旧→新 | 旧 CRLF | 新 CRLF |
| --- | --- | --- | --- | --- |
| manage-personal-knowledge | v1.11.3 → v1.11.5 | 202 → 207 | **201（CRLF）** | **0（LF）** |
| obsidian-vault-notes | v1.13.3 → v1.13.5 | 156 → 161 | **155（CRLF）** | **0（LF）** |
| pdf-problem-search | v1.12.2 → v1.12.3 | 176 → 181 | 0 | 0 |
| math-coach | v1.12.1 → v1.13.0 | 347 → 352 | 0 | 0 |
| math-science-computation | v1.11.4 → v1.12.0 | 187 → 204 | 0 | 0 |
| math-research-solve | v3.1.11 → v3.2.8 | 109 → 152 | 0 | 0 |

⇒ 前两个 skill 的 SKILL.md 回填后会从 CRLF 变 LF。这是**新版本身的形态**（不是我们改坏的），
但会让人以为「整个文件都变了」。git diff 时加 `--ignore-cr-at-eol` 才能看清真实改动。

---

## 3. 回填后的最终内容（逐条）

按 §2 的结论，**真正要落盘的「回填」只有 1 条**，其余都是「保持不动」：

### 3.1 【唯一要改的】`OBSIDIAN_LOCAL_KB_DB` 与活配置 A 的 `db_path` 不一致

| | 值 |
| --- | --- |
| env `OBSIDIAN_LOCAL_KB_DB` | `C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3`（23764992 B，09-13，**废弃库**） |
| 活配置 A L5 `db_path` | `C:/Users/example\AppData\Local\obsidian-vault-notes\vault.sqlite3`（23449600 B，**10-03，活库**） |

两者指向**不同的库**。因为 env 优先，**当前实际用的是废弃库**。

| 证据 | 废弃库 | 活库 |
| --- | --- | --- |
| `index_meta.indexed_at_utc` | `2026-09-13T13:21:44Z` | `2026-10-03T13:54:29Z` |
| `index_meta.note_count` | 685 | 683 |
| `sections` / `section_fts` | 3365 / **4354（不一致，旧格式残留）** | 3129 / 3129 ✅ |
| 磁盘实际 `.md`（`知识库` 全树） | — | **697**，683 ≈ 697−14 |

⇒ **建议改 env `OBSIDIAN_LOCAL_KB_DB` 为 `C:/Users/example\AppData\Local\obsidian-vault-notes\vault.sqlite3`**（即与配置 A 一致）。
这是一条**人必须点头**的改动（改用户环境变量），列入 §5-A2。

### 3.2 保持不动（写清楚「不要做什么」）

| 配置 | 现值 | 为什么不动 |
| --- | --- | --- |
| 活配置 A L3 `vault_root` | `D:/repo\知识库` | 索引 683 ≈ 全知识库 697−14，**它就是按整个 `知识库` 建的**；改成 `pika文件_Pro\笔记共享vault` 会让索引与现状不符 |
| 活配置 A L4 `kb_root` | `C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb` | 与 env 同值，指向现装位置，存在 |
| 活配置 B L2 `knowledge_root` | `D:/repo` | 新版 pdf 的 `infer_knowledge_root()` 正是读这个键；改了就断 |
| 活配置 B L3 `knowledge_root_id` | `KBROOT-442OME7QWTER5T5W7OO7RGNPB4` | 符合 `^KBROOT-[A-Z2-7]{26}$`；`D:/repo\.mpk\root.json` 与 `D:/repo\.mpk\resources.jsonl` 三处必须一致 |
| 活配置 B L13 `Library` / L17 `知识库` | 相对路径 | `sources_must_be_non_nested` 要求相对且不嵌套；实测两者都在知识根下且不互相包含 |
| 三个死配置（§1.4） | 原样 | 被 env 压过；改了不生效，删了可能影响 mpk 的 companion 同步 |

---

## 4. 迁移操作顺序（与脚本的两阶段对齐）

`tools/pika_migrate.py` 的固定顺序：**① verify → ② backup → ③ delete → ④ place**。理由写在脚本注释里：

1. **verify 先于一切**：验证「新版存在且 sha256 相同」+「旧版现场未变」。
   任一条不过 ⇒ 不进清单 ⇒ 后面三步都拿不到它。这是卡 B3 硬判据的落地方式。
2. **backup 先于 delete**：没备份就删 = 旧版直接抹掉，回不来。
3. **delete 先于 place**：用户原话是「把旧版文件清除之后找新版文件」——先清空位，再由新版填充。
4. **备份失败 ⇒ 后面两步都不跑**（`return 3`）；**删除中止 ⇒ 不进入 place**（`return 4`）。

推荐分步跑（每步都能停）：

```bash
python -X utf8 tools/pika_migrate.py                          # 全量 dry-run，先看
python -X utf8 tools/pika_migrate.py --only skills            # 只看 skills（71 条 DIFF）
python -X utf8 tools/pika_migrate.py --only vault             # 只看 vault（3 条 DIFF）
python -X utf8 tools/pika_migrate.py --explain-arbitration    # 只看需要人裁决的 5 条
```

审完清单再执行（两个旗 + 一个清单，缺一不可）：

```bash
python -X utf8 tools/pika_migrate.py --execute --i-understand-delete \
    --plan D:/repo\_tools\pika-迁移\_plans\plan_<时间戳>.json
```

六个分类的实测条数（`--only` 可用值）：

| `--only` | 内容 | SAME | DIFF | 只写不删 |
| --- | --- | --- | --- | --- |
| `library` | `Library/开源资源` + `Library/pika的presentations` | 2288 | 0 | 87 |
| `tool` | `Tool/代码与数据`（不含 gridlab） | 34 | 0 | 0 |
| `aitools` | `知识库/pika文件_Pro/AI工具` | 0 | 0 | 1 |
| `vault` | `知识库/pika文件_Pro/笔记共享vault` | 1076 | 3 | 48 |
| `skills` | `C:/Users/example\.dsh\skills\<6 个>` | 251 | 71 | 145 |
| `gridlab` | `Tool/代码与数据/grid-covering-lab-source` | 48 | 0 | 1 |

---

## 5. 需要人确认的点

每条写清：**不问会怎样 / 默认选哪个 / 为什么**。

### A1 —— `pdf-problem-search` 的 PDF 索引库在本机根本不存在

- **事实**：`resolve_data_root()` 三条候选（env `OBSIDIAN_LOCAL_KB_DATA_ROOT` / `project/data` / `~/Documents/obsidian_local_kb/data`）
  全不命中；全盘 find 无任何 `pdf*.sqlite3`；`~/.dsh/.../obsidian_local_kb/data/` 不存在。
  2.1.4 与 2.1.7 两个包 payload 里也没有 `data/` 目录。函数最终走 `normalized[0]` 兜底（= `project/data`，空）。
- **不问会怎样**：迁移完 `pdf-problem-search` 仍然是「找不到库」的状态，
  用户会以为「迁移把它搞坏了」，其实迁移前就是这样。
- **默认选**：**不新建索引**。迁移只搬文件，`indexes={pdf: explicit-opt-in}` 是包自己声明的策略。
- **为什么**：建 PDF 索引要扫 `library.sqlite3`（448 MB / 2422 篇 PDF / 50591 页）并另建 `pdf*.sqlite3`，
  是几十分钟级的新动作，不属于「回填配置」。且 `library.sqlite3` 的 `last_scan_at=2026-09-15`，重建会顺带刷新它。

### A2 —— `OBSIDIAN_LOCAL_KB_DB` 指向废弃库（见 §3.1）

- **事实**：env 指向 `pika_math_learning_toolkit\...\vault.sqlite3`（09-13 / 685 篇 / `section_fts` 与 `sections` 不一致），
  配置 A 的 `db_path` 指向 `obsidian-vault-notes\vault.sqlite3`（10-03 / 683 篇 / 结构自洽）。
  env 优先，所以**当前用的是旧库**。
- **不问会怎样**：笔记检索会一直命中 09-13 的快照，10-03 之后的新笔记搜不到。
- **默认选**：**改 env 指向活库**（`C:/Users/example\AppData\Local\obsidian-vault-notes\vault.sqlite3`）。
- **为什么**：活库的 `note_count` 与磁盘 `.md` 数量（697−14）吻合，且 `sections`=`section_fts`；
  废弃库的 fts 行数与 sections 对不上，是旧格式迁移残留。但**改环境变量是改用户机器状态**，必须人点头。

### A3 —— 481 个 `.md` 未入库？（vault_root 口径疑点）

- **事实**：`vault_root` 配的是 `知识库` 整棵树（索引 683 篇），但 `知识库` 下 `.md` 有 697 篇。
- **不问会怎样**：那 14 篇（`未命名.md`/`杜5.md`/`问题.md` 等根下散篇 + 子目录）是否该被索引，没人知道。
- **默认选**：**维持 `知识库` 整棵树**，不改成 `pika文件_Pro\笔记共享vault`。
- **为什么**：683 vs 697 的差额可能只是 `.obsidian/`、`.trash/` 等被 `prune dot-prefixed` 规则排除的目录，
  不是漏索引。改成子目录会**丢掉根下散篇**，风险大于收益。

### B1 —— `.obsidian/` 两候选：用户当前在用的那份会被覆盖

- **事实**：
  - `知识库\.obsidian\` = **15 文件**，`appearance.json` 221 B（`interfaceFontFamily: "Microsoft YaHei UI,GenYoGothic2 PJP N"`、
    `textFontFamily: "MV Boli,Microsoft YaHei Light"`、`enabledCssSnippets: ["bold-use-real-pjp-b"]`），
    `workspace.json` 7412 B（mtime **2026-10-30 17:03**），多一个 `snippets/bold-use-real-pjp-b.css`。
  - `知识库\pika文件_Pro\笔记共享vault\.obsidian\` = **14 文件**，`appearance.json` 130 B（**与新版 zip 逐字节相同**）、
    `workspace.json` 7697 B（mtime 2026-05-30，zip 里是 7924）。
- **不问会怎样**：迁移会把 vault 内那份 `appearance.json` 写成 zip 里那份（`Comic Sans MS` / `MV Boli,Arial Black` / **无 snippet**），
  用户的字体设置与 CSS snippet **被抹掉**。
- **默认选**：**不动 `知识库\.obsidian\`**；`vault\.obsidian\` 里那 3 条 DIFF（workspace/appearance/graph）按脚本清单走，
  但**执行前必须人确认是否保留用户在用的那份**。
- **为什么**：`知识库\.obsidian\` 的 mtime（10-30）晚于 zip 构建（10-24），且带 CSS snippet —— 这是用户**正在用的活配置**，
  vault 内那份是旧快照。覆盖 = 回退用户几天前的设置。（脚本已把 `知识库\.obsidian` 列入裁决清单，不会自动删。）

### B2 —— 2 个已被用户删掉的 SVG 会被「复活」

- **事实**：`知识库\pika文件_Pro\笔记共享vault\AI工具\图片\human_obsidian_ai_collaboration.svg`（1437534 B）
  与 `..._v2.svg`（1437545 B）在 git HEAD 有记录、磁盘没有、新版 zip 里有，合计 **2.87 MB**。
- **不问会怎样**：迁移后这两个文件会重新出现，用户会以为「删了的东西又回来了」。
- **默认选**：**照新版写入**（它们是 `old_missing`，脚本的 place 阶段会建）。
- **为什么**：迁移语义是「以新版为准」。但这属于「用户主动删过」的逆操作，**必须点头**。

### B3 —— 1 篇笔记疑似改名，但不能自动判继承

- **事实**：旧版仅有的 1 条 `数学/用概率计算含参数积分的极限.md`（10001 B，tags `[math, tool_idea]`），
  新版疑似对应 `数学/含参数积分的概率表示与收敛.md`（41916 B）。但 token-set Jaccard（前 4000 字符）= **0.043**。
- **不问会怎样**：这篇 10 KB 的旧笔记会被当「磁盘独有」留在原地，而新版 42 KB 的新笔记另建一份 —— 两篇并存。
- **默认选**：**两篇都留**（不删旧的、不合并）。
- **为什么**：Jaccard 0.043 说明内容几乎不重叠，很可能是**另一篇**而不是改名。
  自动判改名然后删旧的，等于删掉一篇用户可能还要的笔记。新版「含参数积分」是一族 6 篇 + 1 张图，不是单篇。

### B4 —— `_observer-tools/` 4 个文件（27 KB）新版没有

- **事实**：`知识库\pika文件_Pro\_observer-tools\`：`observer_receiver.py` 18437 B、`README.md` 4269 B、
  `_diag_pdf.py` 2798 B、`_list_notext.py` 1886 B。zip 里完全没有。
- **不问会怎样**：这是用户自建的工具，**误删就没了**（且不在 git 的 tracked 范围里风险更高）。
- **默认选**：**保留不动**（脚本已列入裁决清单，不会删）。
- **为什么**：新版没有替代品；名字带 `_` 前缀，明显是本地私有工具。

### B5 —— `知识库\Codex Skills\` 3 个 0 字节 SKILL.md 空壳

- **事实**：`知识库\Codex Skills\obsidian-vault-notes\SKILL.md` 0 B、
  `…\pdf-problem-search\SKILL.md` 0 B、`D:/repo\知识库\pika文件_Pro\Codex Skills\manage-personal-knowledge\SKILL.md` 0 B。
- **不问会怎样**：看着像垃圾，但删了 `_common.py` 的 `INFERRED_VAULT_ROOT`（判据 `(parent/"Codex Skills").exists()`）
  与 pdf 的 `infer_vault_root()` 会失去定位标记。
- **默认选**：**保留**。
- **为什么**：当前 `infer_vault_root()` 返回 `None`（本机不靠这个机制），但保留空壳成本为 0，
  删了可能让别的 skill 的探测结果变化。**保留比删除安全。**

### B6 —— `笔记共享vault\笔记共享vault\` 空目录（双层套娃残留）

- **默认选**：**保留**（空目录，0 字节）。
- **为什么**：删空目录没有收益，但可能有脚本按「双层」路径做探测。脚本已列入裁决清单。

### C1 —— `compute-fleet-manager` 装不装（★直接影响 `suite_doctor.py` 是否 exit 1）

- **事实**：新版 payload 有 7 个 skill，本机只装 6 个；新版 `suite_doctor.py` 的 `required` 已扩到 7 项（§2.4）。
- **不问会怎样**：迁移后跑 `suite_doctor.py` 必报 `"status": "missing_skill_payload"` 并 **exit 1**，
  看起来像「迁移失败」，其实只是缺第 7 个 skill。
- **默认选**：**装上**（16 文件 / 135666 B）。
- **为什么**：它在新版 `dependency_graph` 里虽无人依赖，但 `update_policy.transaction=all-payloads`
  要求 7 个一起替换；只装 6 个等于违反包自己的事务约定，且 doctor 会一直红。

### C2 —— 官方 `install.py` 的 `--target-root` 必须显式给

- **事实**：`install.py:221-229`，不给 `--target-root` 时落点是
  `os.environ.get("CODEX_HOME", ~/.codex)/"skills"`。本机 `CODEX_HOME` **未设** ⇒ 会装到 `C:/Users/example\.codex\skills`。
- **不问会怎样**：技能装到 `~/.codex/skills`，DSH 根本看不到，用户以为「没装上」。
- **默认选**：**显式 `--target-root C:/Users/example\.dsh\skills`**。
- **为什么**：本机现装就在这里（6 个裸目录），`skills-math/` 是指向它们的 junction（实测 inode 相同，只有一份实体）。

### C3 —— 装 skill 时 `.dsh/skills/nul` 这个 0 字节垃圾文件

- **事实**：`C:/Users/example\.dsh\skills\nul` 存在，0 B。Windows 上对它调 `os.path.relpath` 会抛
  `ValueError: path is on mount '\\\\.\\nul', start on 'C:'`。
- **默认选**：**迁移脚本跳过它**（已实现：按设备名 `nul/con/prn/aux/com1-9/lpt1-9` 剪枝）。
- **为什么**：删它是「顺手清理」，不属于迁移范围；但任何遍历 `skills/` 的脚本都必须防它。

### D1 —— 仓库脏状态与 git 提交

- **事实**：`D:/repo` 的 `git status --porcelain` 有 49 行（`.mpk/`、`Tool/`、`_archive/`、`infra/` 等 `??`）。
  这是**长期存在**的（勘察时就有 46 行），不是本次造成。
- **默认选**：**不提交、不 `git add -A`**。
- **为什么**：迁移只动文件，不动版本库；一旦 `add -A` 会把 448 MB 的 `library.sqlite3` 之类的路径风险引进来。

---

## 6. 验收清单（跑完怎么确认没坏）

| # | 检查 | 期望 |
| --- | --- | --- |
| 1 | `python -X utf8 tools/pika_migrate.py` | 会删 **0** 条（因为旧版已被换掉）、验证失败 0 条 |
| 2 | `python -X utf8 .../skills/obsidian-vault-notes/scripts/obsidian_local_kb/...` 解析探针 | `kb_root` / `db_path` 与 §2.1 表一致 |
| 3 | `python -X utf8 .../manage-personal-knowledge/scripts/suite_doctor.py` | 装齐 7 个后 exit 0 |
| 4 | 活配置 A/B 两份 JSON | 键名与 §1.2/§1.3 完全一致，`schema_version` 未被改 |
| 5 | `知识库\.obsidian\appearance.json` | 仍是 221 B 的 `Microsoft YaHei UI` + `enabledCssSnippets`，**没变成 130 B** |
| 6 | `_observer-tools\` 4 文件 | 仍在 |
| 7 | `D:/downloads\pika文件_Pro.zip` | sha256 全程未变（脚本只以 `'r'` 打开） |

---

## 7. 事故记录（必须如实留档）

**2026-10-31 19:53，我在验证 `--execute --plan` 分支时，探针只打桩了 `delete()` 与 `backup()`，漏了 `place()`，
导致 place 阶段以 `dry_run=False` 真跑，写入了 355 个文件（74 覆盖 + 281 新建）。**

| 项 | 读数 |
| --- | --- |
| 删除数 | **0**（`delete()` 被强制 `dry_run=True`） |
| 覆盖写 | 74（= 74 条 DIFF 全部） |
| 新建 | 281（= 全部 `old_missing`，含 `compute-fleet-manager` 16 个文件） |
| 影响范围 | `skills` 216、`library` 87、`vault` 51、`aitools` 1 |
| 净损失 | **1 个文件**：`notes/.obsidian/workspace.json`（7697 B，Obsidian UI 布局状态，被 `.gitignore:21` 忽略，无任何副本） |
| 可还原 | **73 条**（71 条来自 `pika_math_learning_toolkit-2.1.4.zip!payload/`，2 条 vault 笔记来自 `git HEAD`） |

**还原脚本**：`_tools/pika-迁移/restore_accident.py`（默认 dry-run）。实测
`可还原 73 条 / 不可还原 1 条 / 校验失败 0 条`（日志 `gates/diag/pika_restore_dryrun.log`）。

**事后证明两阶段设计是对的**：事故后重跑 `pika_migrate.py`，verify 立刻把 74 条全部判为
`旧文件已被改动（现场 ≠ 记录），拒绝纳入清单`，`会删 0 条`。**即使当时加了 `--execute`，delete 也拿不到可删的条目。**

**教训**：任何「只读探针」如果要驱动真实 `main()`，必须把**所有**会写盘的阶段一起打桩，
或者干脆不要调 `main()` 而是单独测纯函数。这次的漏洞就出在「打桩了两个阶段，忘了第三个」。

---

## 附：本方案引用的一次性脚本

| 脚本 | 用途 |
| --- | --- |
| `inventory/_scripts/resolve_probe.py` | 分别 import 新旧 `_common.py` / `paths.py`，打印实解析值 |
| `inventory/_scripts/old214.py` | 从 2.1.4 zip 读权威旧版行（磁盘已被覆盖，不可再读） |
| `inventory/_scripts/print_lines.py` | 按行号打印新旧文件片段 |
| `inventory/_scripts/env_cfg_scan.py` | 扫新旧树所有 `os.environ.get` / `$env:` / config 键 |
| `inventory/_scripts/skillmd_anchors.py` | 6 个 SKILL.md 的版本行/节锚点 + CRLF 统计 |
| `_tools/pika-迁移/restore_accident.py` | 事故还原（默认 dry-run） |
