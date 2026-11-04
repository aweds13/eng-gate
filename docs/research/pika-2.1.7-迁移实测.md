# pika 2.1.7 迁移实测（技能升级 / observer 修复 / vault 裁定 / 残留清理）

> 记录时间 2026-11-04。**这份文档只记实测读数与判据，不写「应该怎样」。**
> 素材与备份都在仓外；本仓只放结论与指针。

## 0. 一句话结论

装着的 **7 个 pika skill 就是 2.1.7 主体**（不是 2.1.4 旧版），升级动作只有「覆盖 71 个内容不同的文件 + 删 18 个 `.pyc`」；
vault 侧**「回填」是空操作**（zip 里没有一个文件是磁盘上没有的）；`_observer-tools` 的接收端丢了两份文件、已重建并通过 25 条 E2E。

## 1. 备份（先备份再动手）

- 脚本 `.tmp/pika_backup2.py`；产物 `D:/repo/_tools/pika-迁移/_backup_20261104T112516/`。
- 读数：`vault` **1135 文件** + `skills` **808 文件** = **1943 文件 / 262305645 B**；`MANIFEST.json` 有逐文件 sha256。
- ★ 第一版 `shutil.copytree` 失败：`C:/Users/example/.dsh/skills/nul` 是 **Windows 保留设备名残留**（`os.path.isfile` 假、`os.path.isdir` 假、`st_size = 0`、mtime `1970-01-01`）⇒ 抛 `[WinError 87] 参数错误`。改逐文件 copy + `SKIP_NAMES={'nul'}`，`skipped` 只剩这一条。
- ★ 备份**没有覆盖**后来删掉的三个 0 字节 SKILL.md（备份侧只有 1 个 0 字节命中）⇒ 这三个的**唯一还原路径是 `git checkout`**（仓 = `D:/repo`）。

## 2. 技能升级：7 包 466 文件与 2.1.7 payload 逐字节相同

### 2.1 出发点被推翻一次

原假设「散落在 D 盘的是旧版 2.1.4，要清除旧版装新版」。逐文件 sha256 比对后不成立：

| skill | 2.1.7 包 | 升级前已装 |
|---|---|---|
| manage-personal-knowledge | v1.11.5 | v1.11.3 |
| obsidian-vault-notes | v1.13.5 | v1.13.3 |
| pdf-problem-search | v1.12.3 | v1.12.2 |
| math-science-computation | v1.12.0 | v1.11.4 |
| math-coach | v1.13.0 | v1.12.1 |
| math-research-solve | v3.2.8 | v3.1.11 |
| compute-fleet-manager | v1.0.6 | v1.0.6（16/16 全同） |

对比 2.1.4 payload 的 `onlyInst`（`math-coach` 53、`math-research-solve` 50、`manage-personal-knowledge` 18）与 2.1.7 的（`math-coach` 0、`math-research-solve` 0、`manage-personal-knowledge` 14 且全为 `__pycache__`）⇒ **已装的是 2.1.7 主体**，只是每包落后一两个小版本。

### 2.2 升级动作只有两条

```
zip 新增文件 = 0（zip 里没有已装目录缺少的文件）
① 覆盖「内容不同」的 71 个文件
② 删掉已装侧 18 个 __pycache__/*.pyc（4 个 __pycache__ 目录）
```
报告 `.tmp/skill_upgrade_report.json`：`{changed: 71, zip_new: 0, pycache_dirs: 4, pycache_pyc: 18, problems: []}`。

### 2.3 终态复核（口径：排除 `__pycache__`）

```
compute-fleet-manager        v1.0.6     same= 16 diff=0 onlyZip=0 onlyInst=0  CLEAN
manage-personal-knowledge    v1.11.5    same= 57 diff=0 onlyZip=0 onlyInst=0  CLEAN
math-coach                   v1.13.0    same= 97 diff=0 onlyZip=0 onlyInst=0  CLEAN
math-research-solve          v3.2.8     same=115 diff=0 onlyZip=0 onlyInst=0  CLEAN
math-science-computation     v1.12.0    same= 59 diff=0 onlyZip=0 onlyInst=0  CLEAN
obsidian-vault-notes         v1.13.5    same= 81 diff=0 onlyZip=0 onlyInst=0  CLEAN
pdf-problem-search           v1.12.3    same= 42 diff=0 onlyZip=0 onlyInst=0  CLEAN
TOTAL same=466
```
`__pycache__` / `*.pyc` / `.pytest_cache` 全树残留 = **0**。

### 2.4 ★ 一处判据被我自己推翻（保留补丁 → 撤销补丁）

升级前「已装 vs zip」只差 **4 处**，初判「① 是死代码不保留、② 无行为差异不保留、③ 真有用要保留、④ zip 已官方修好不保留」。
**第 ③ 条判错了**，两向实测（同一 `math-coach` 目录的两份副本，PS `5.1.26100.8655` 与 `pwsh 7.6.7` 各跑一次）：

| 版本 | Windows PowerShell 5.1 | pwsh 7.6.7 |
|---|---|---|
| zip 原版（**无** `-AsHashtable`） | **PASS 10 generic cases** | PASS 10 generic cases |
| 已装补丁（**有** `-AsHashtable`） | **挂掉** `NamedParameterNotFound` | PASS 10 generic cases |

报错原文：

```
ConvertFrom-Json : 找不到与参数名称“AsHashtable”匹配的参数。
所在位置 C:/Users/example\.dsh\skills\math-coach\scripts\tests\test_dsh_rational_identity.ps1:19 字符: 56
FullyQualifiedErrorId : NamedParameterNotFound,Microsoft.PowerShell.Commands.ConvertFromJsonCommand
```

根因：**PS 5.1 的 `ConvertFrom-Json` 没有 `-AsHashtable`**（7.x 才有）。所以「已装那行」不是本机补丁，是**上一版遗留的坏行**；**2.1.7 恰好把它删掉了**，zip 原版才是修好的版本。
处置：`live.write_bytes(zip_bytes)`，`1484 B（sha 0c9a99d3882208a1）` → **`1471 B（sha 8fd2e07c63fd50f8）`，与 zip 逐字节相同**；复验两个引擎都 `PASS 10 generic cases`。
★ 教训：**「本机补丁」要先证明它在坏环境下真的更好**，否则就是把上游的修复改回去。

### 2.5 自检读数（升级后，未动 Vault）

- `suite_doctor.py`：`status installed`、`python 3.14.6 supported true`、7 包全 `true`；`optional_capabilities` = `pdf_text_extraction available(pdftotext)` / `mathematica available_command`（仍需真 MCP 调用才可声称可用）/ `sagemath not_detected` / `primecount not_detected`。
- 7 包 `validate_terminology.py --skill-root "../"` 全 `{"ok": true, "code": "terminology_valid"}`（**`--skill-root` 是必填**；term_count 3/3/2/9/4/45/3）。
- `setup_local.py check`：`healthy`、`schema_version 3`、`vault_markdown_count 697`、`indexed_note_count 683`、`newer_markdown_count 3`、`missing_indexed_count 28`、**`index_stale true`**（陈旧但可刷新，不是升级破坏）。
- `manage_kb.py status`：`healthy`、`docs 2422 / pages 59301 / coverage 96.28%`。
- ★ 各包 pytest 有既有红，**用备份老版同跑对照证明不是本次引入**：`manage-personal-knowledge` 2 failed（老版 3）、`obsidian-vault-notes` 7 failed + 2 subfailed（老版 9 + 2）、`math-coach` 1 failed（同）、`math-research-solve` 2 failed（老版 19）、其余为 0。
- ★ **跑自检会重新生成 `.pyc`**（13:09 那次生成了 18 个，已再清）⇒ 清理必须放在最后一次自检之后。

## 3. `_observer-tools` 接收端修复

### 3.1 修复前状态

- 目录 `D:/repo/知识库/pika文件_Pro/_observer-tools/`，`observer_receiver.py` 18437 B 可用（`--self-test` 通过）。
- ★ README 承诺的两个文件**不存在**：`hermes_observer.py`（桥接器）与 `test_e2e.py`。且 `git ls-files --error-unmatch` 认不出、`git log --all` 只有 `cde23b0 init` ⇒ **从未被跟踪**。
- 4318 端口没在听；`%LOCALAPPDATA%/pika-skill-observer/` 是空目录（无 `phase-batches.jsonl`）⇒ **从没收到过数据**。
- 7 个 skill 的 `observer_run.py` 是 **fail-open**（`timeout=0.05` + `except Exception: return`）⇒ 收端不在时静默丢弃，不影响业务。2.1.7 包里**只有发送端没有 receiver**。

### 3.2 重建后的读数（我独立复核，不采信子 agent）

- 产物：`hermes_observer.py` **9776 B / 254 行**、`test_e2e.py` **11001 B / 263 行**、README.md 4269 → **5104 B**；全部 LF 无 BOM；`observer_receiver.py` 未动。
- `observer_receiver.py --self-test` → **`self-test: PASS`**
- `test_e2e.py` → **`E2E: 25/25 PASS`**
- `netstat` 确认 4318 无监听（没留进程）。
- 真落盘（`C:/Users/example/AppData/Local/pika-skill-observer/phase-batches.jsonl`，2 行 / 329 B）：

```json
{"received_at":"2026-11-04T12:24:48.243+08:00","skill_name":"obsidian-vault-notes","thread_key":null,"catalog_version":"obsidian-vault-notes/v1","script_sha256":null,"interval_count":1,"intervals":[{"phase_code":"retrieve","started_at_ns":1793766288147109500,"ended_at_ns":1793766288231688400,"fields":{"operation":"process"}}]}
```

- ★ 子 agent 自报「`thread_key` 与 `script_sha256` 全是 null，未被覆盖」。我另起随机端口 `http.server` + 造真 `.py` 脚本 + `CODEX_THREAD_ID=thread-probe-12345` 补测：

```
thread_key       thread-probe-12345
script_sha256    fa49639e2862f7fad507bf35d293adedcfea6b48fbf7828ad19b77882233a646
EXPECTED_SHA     fa49639e2862f7fad507bf35d293adedcfea6b48fbf7828ad19b77882233a646
thread_key 非空: True   script_sha256 非空: True   sha 对得上: True
```

⇒ **两条非空路径也通过**。

- 契约：`send_phase_batch()` 外层 `except Exception` 全兜返回 `(bool, str)` 不抛；上报在 `finally`；`resolve_endpoint()` 强制 `scheme == "http"` + `hostname in {127.0.0.1, localhost}` + 端口非空；`FileNotFoundError → 127`、`PermissionError → 126`。payload 逐字段照抄 `observer_run.py`（gzip `compresslevel=1, mtime=0` + `Content-Encoding: gzip`）。
- 隐私契约：只允许 11 个字段，违禁字段（`path` / `query` / `body` / `excerpt` 等）只记名字到 `_rejected_fields`、**不记值**。

## 4. vault：回填是空操作，只剩两处差异与一个独有文件

### 4.1 总体比对

zip 第 3 层（`_extracted/笔记共享vault/笔记共享vault/笔记共享vault`，三层套娃）vs 磁盘 `知识库/pika文件_Pro/笔记共享vault`：

```
zip files 1127   local files 1128
only_zip 0   only_local 1   both 1127   same 1125   diff 2
```

⇒ **zip 里没有一个文件是磁盘上没有的**；「回填」实质是空操作。

### 4.2 差异1 —— 保留本地版（zip 是排版退化）

math/一致几乎处处有界函数列算术平均值几乎处处收敛的问题.md：zip 8118 B / 本地 8117 B，首个不同字节 offset **441**：

- zip 版在全角冒号前**多一个半角空格** `0x20`（`非常类似 ：`）
- 本地版无该空格（`非常类似：`）

`local == git HEAD True`、`zip == git HEAD False` ⇒ **本地即基线**，判定 **保留本地版**。

### 4.3 差异2 —— 以 zip 为主体，把旧稿独有的数值核对并进附录

math/模长总和为1的n个复数中，至少能合成一个模长多大的复数.md：zip 165 行 / 13497 B vs 本地 115 行 / 8431 B。

- zip 独有 54 非空行（章节化重写：`问题0：CMO 1986,p3`、`想法0`、`1.1 玩具模型`、`1.2 按象限分类`、`定理2.2.1`、`定理2.3.1（Netuka，Veselý 1978）`，并解析给出 `c_d = ∫₀^{π/2} cosθ (sinθ)^{d−2} dθ / ∫₀^π (sinθ)^{d−2} dθ`）。
- 本地独有 32 非空行，其中 **24 行 Mathematica 数值核对代码**（`generateVectorsSimple[n_, k_]` 随机取向量、`averageOfPositiveInnerProducts[vectorData_]`、`vectorData = generateVectorsSimple[10, 3]; m = 100000`）。
- 判定：zip 是**内容更全的重写**，但旧稿那段代码 zip 没有 ⇒ **以 zip 为主体 + 旧稿代码作为附录**。
- 已写盘（`.tmp/merge_note2.py --write`）：**13497 → 14806 B / 193 行**，结构 = zip 全文 + `## 附：数值核对（旧稿保留）` 节 + 说明段 + 代码块；断言 `crlf == 0`。备份 `…md.bak-before-merge-20261104`（8431 B = 旧版逐字节）。
- ★ 差异2 的本地版**也是 git HEAD**（8431/8431 SAME）⇒ 本地版本不是「后来新编辑的」，mtime `2026-10-31 20:45` 是 zip 解压时间。

### 4.4 本地独有文件 —— 保留

math/用概率计算含参数积分的极限.md（10001 B，frontmatter `tags: [math, tool_idea]`，**在 git HEAD 里**）：

- 与 zip 内全部 math/*.md 做 difflib，最高相似度只有 **0.322**；与 176 个 `.stego_backups/*.bak` 最高 **0.347** ⇒ zip 里没有对应版本。
- 与 math/含参数积分的概率表示与收敛.md（41916 B）**不同题**。
- 判定：**保留**。

## 5. 残留清理（已执行）

| 对象 | 位置 | 证据 |
|---|---|---|
| 3 个 0 字节 SKILL.md | `知识库/Codex Skills/{obsidian-vault-notes,pdf-problem-search}/`、`知识库/pika文件_Pro/Codex Skills/manage-personal-knowledge/` | 三者均 0 字节、`git ls-files --error-unmatch` 通过（可 `git checkout` 还原）、目录里只有该文件 |
| 1 个空目录 | `知识库/pika文件_Pro/笔记共享vault/笔记共享vault` | `files 0 / subdirs 0` |

删除后 `rmdir` 了已成空的父目录。全盘扫确认**只有这 3 个 0 字节 SKILL.md**，`笔记共享vault` 同名嵌套**只此一处**。

## 6. 顺带关闭的两个「不知道」

- **两个 remotion zip 与 zip 侧逐字节相同**（`remotion-project.zip` 1815414 B、`cognitive-encoding-remotion-source.zip` 43385 B；zip 内 entries 13 / 20）⇒ **第 8 项无需动作**。
- **vault 里的 grid-covering 副本零本机独有内容**：`…/笔记共享vault/math/代码/grid-covering-lab`（48 文件）vs `Tool/代码与数据/grid-covering-lab-source`（48 文件）= `same 45 / diff 3`；3 处差异**只是 ASCII 连字符 `-` 换成 U+2010**（18 / 11 / 3 处），把 U+2010 归一回 `-` 后**逐字节相同**；`.stego_backups` 的 3 个 `.bak` 与 Tool 版**逐字节相同 3/3**。

## 7. 回收站快照：第三方交叉验证（并关闭「不知道 #1」）

★ 早前那条「磁盘上还有另一份 `pika文件_Pro.zip`」的怀疑**是我误判**，已证伪：回收站里躺着的
是**被删掉的整个文件夹**，不是第二个 zip。

| 读什么 | 读数 |
|---|---|
| 回收站唯一 pika 记录 | `$IFO3P23`，`$I` 元数据 `recorded size 1460747606`（1393.1 MiB）、`deleted at 2026-10-30 15:36:05 (UTC)`、`original name` = `D:/downloads\pika文件_Pro (2)` |
| 全盘 `pika文件_Pro.zip` | 只有 **1 份**（`D:/downloads/`，1451498774 B / 2411 条目，`zipfile.namelist()` 实测） |
| 回收站该文件夹 | 3531 文件 / 1460747606 B |

把它当成「删除前快照」，对三篇争议笔记做**第三方对照**（这三个来源互相独立：回收站快照、live vault、包内 zip）：

| 笔记 | 回收站快照 | live | 包内 zip |
|---|---|---|---|
| math/模长总和为1的n个复数中，至少能合成一个模长多大的复数.md | 8431 B `043b4cc1cfc0` | 14806 B `7a8bb3e8d695` | 13497 B `1a200a72fb19` |
| math/一致几乎处处有界函数列算术平均值几乎处处收敛的问题.md | 8117 B `38c07c897005` | 8117 B（同） | 8118 B `a3882d5cc9a0` |
| math/用概率计算含参数积分的极限.md | 10001 B `4efcd8312e53` | 10001 B（同） | **不存在** |

**印证了 §4 的两处裁定**：

- 差异 1（`一致几乎处处有界函数列…`）回收站版与 live **逐字节相同**（8117 B）⇒ 只有 zip 多那个半角空格，**留本地正确**。
- 本地独有文件 用概率计算含参数积分的极限.md 在回收站快照里也有（10001 B 同 sha）⇒ 它是**源 vault 真有、被打包漏掉**的，不是本地孤儿；live 内对它的 wikilink 引用实测 **5 处 / 3 文件**。

其它读数：

- live 比快照多 2 篇（都是删除**之后**新增）：math/Kolmogorov强大数定律.md（11502 B）、math/含参数积分的概率表示与收敛.md（41916 B），mtime 均 `2026-10-31 19:53`。
- 全量 sha256（回收站 `pika文件_Pro` 1123 文件 vs live 1129，both 1123）：`only in recycle = 0`；内容不同**只有 2 个**（`workspace.json` 7697→7924、`模长总和为1…md` 8431→14806）。
- ★ **事故版 `workspace.json` 已救回**（7697 B / sha `c3b4564498a3`）—— 这正是早前记为「唯一不可恢复」的那个文件，现已有原件。

### 7.1 回收站里还藏着一整个 `pika资料共享`（live 已完全消失）

| 顶层 | 回收站 | live |
|---|---|---|
| `pika资料共享` | **2408** | **0** |
| `笔记共享vault` | 1123 | 1129 |
| `_observer-tools` | 0 | 6 |
| `AI工具` | 0 | 2 |

回收站独有 2408 个 / **1215609789 B = 1159.3 MiB**，全部在 `pika资料共享/` 下（`.pdf 2341` / `.tex 19` / `.csv 17` / `.png 8` / `.docx 7` / `.py 5` / `.doc 4` / `.zip 2` / `.md 2` / `.wl 1` / `.txt 1` / `.jpg 1`）。

**全部可从 `D:/downloads/pika文件_Pro.zip` 逐字节还原**：2407 个在 zip 内有对应条目，CRC32 逐文件比对 **2407/2407 一致、0 不一致，共 1158 MiB / 24.9s**。唯一不在 zip 的 `AI工具/pika_math_learning_toolkit-2.1.4.zip`（sha `7ad8f0ee86ea6cba1408`）与 `_backup_20261104T112516/vault/AI工具/` 里那份**逐字节相同**。

外层 zip 完整性：`zipfile.testzip()` → **ALL OK**（0.9s）。

**与 `D:/repo/Library` 的关系**（Library 2466 文件 / 2.7 GB）：按（文件名, 大小）配对 2373，全量 sha256 **2373/2373 identical、0 different（1156 MiB / 5s）**。Library 里没有的 **35 个**：`代码与数据/` 34 个（`math_peak_age_study_public/*` 23 + `grid-covering-lab-source.zip` + `word_count.py` + `wolfram/plotRecurrence.wl` 等）+ `2.1.4.zip`。⇒ 那批 PDF 绝大部分已在 Library 里（只是目录结构不同）。

**没有任何活的引用依赖它**：vault 内 .md 引用 `pika资料共享` = 0、`C:/Users/example/.dsh/skills` 内 = 0、`git ls-files '*pika资料共享*'` = 0。

### 7.2 保底抽取（都在快照目录里）

`D:/repo/_tools/pika-迁移/_snapshot_recycle_20261030/`，**797 文件 / 9.0 MiB**：

| 内容 | 读数 |
|---|---|
| `笔记`（只抽 .md/`.bak`，对应删除前快照） | 741 文件 / 5207617 B |
| `pika资料共享-文本与代码/` | 45 文件 / 634812 B（全部非 PDF 文本/代码） |
| `pika资料共享-文本与代码/代码与数据/` | 34 文件 / 2154875 B（含 8 PNG + 17 CSV，Library 里没有） |
| `_pre-accident-workspace.json` | 7697 B / sha `c3b4564498a3` |

`MANIFEST.json`（138914 B）带逐文件 sha256 + 五个 verification 子块 + `disposition`。

**处置决定：回收站原件不删**（可随时清空回收 1.4 GiB）。理由：全部内容已验证可从 zip 还原，但删回收站不可逆，按会话纪律不自动做，且 D: 还剩 93G 不紧张。

## 8. 仍然「不知道」的

1. ~~磁盘上是否还有第二份 `pika文件_Pro.zip`~~ —— **已关闭**，见 §7：只有一份，回收站里的是被删的文件夹。
2. 旧 toolkit 的 `install.py` 是否真跑过 —— 没有找到运行痕迹。
3. `_observer-tools` 那两份丢失的文件是**怎么丢的**（未跟踪 ⇒ git 里没有历史可比）。
4. vault git 最后提交（2026-09-14）之后到底改了多少 —— 未做逐提交考古。

## 9. 指针

- 备份：`D:/repo/_tools/pika-迁移/_backup_20261104T112516/`（`MANIFEST.json` 有逐文件 sha256）
- 解包素材：`D:/repo/_tools/pika-迁移/_extracted/`（`pika_math_learning_toolkit-2.1.7` / `2.1.4` / `笔记共享vault` / `grid-covering-lab-source`）
- 原始压缩包：`D:/downloads/pika文件_Pro.zip`
- 迁移脚本与报告：`.tmp/pika_backup2.py`、`.tmp/skill_upgrade.py`、`.tmp/skill_upgrade_report.json`、`.tmp/merge_note2.py`
