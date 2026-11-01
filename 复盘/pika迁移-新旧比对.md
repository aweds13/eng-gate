# pika 迁移 —— 新版 vs 旧版比对报告

> 卡 B3 交付物。**本报告只做比对，未删除 / 覆盖 / 移动任何文件**（`D:/downloads\pika文件_Pro.zip` 全程只读）。
> 真跑（清旧版、铺新版）必须另开卡 **B5** 并要人确认；本报告第 8 节列了必须由用户拍板的点。
> 读者：新窗口里的工程师。照着第 6 节的执行方案做即可，不需要重跑勘察。

---

## 0. 一句话结论

| 问题 | 答案 |
|---|---|
| 压缩包里有几个 skills？ | **7 个**（不是 6 个，也不是「6–7 个」）。名字与完整路径见 §3。 |
| 新版文件总数 | 展开后 **4071 个文件 / 1477431482 B**（另有 3 个嵌套压缩包容器本身不入文件数） |
| 旧版找到逐字节相同副本 | **3697 个**（在 3771 个「能对上」的对子里） |
| 能对上但内容不同 | **74 个**（其中 vault 3 个、skills 71 个） |
| 只在旧版有（新版没有） | **2 个**（见 §5.3） |
| 内容相同但路径不同（逐文件） | **0 个**。用户的「层级变动」发生在**容器层**，不在文件层 —— 见 §4 |
| 个性化配置在哪 | **不在任何 skill 文件里**。在 `%APPDATA%` 下的 5 个 JSON 里，而且其中 3 个互相矛盾 —— 见 §5 |

**最要紧的一条**：用户担心的「回填旧版个性化设置到新版」这件事，在 skill 文件层面是**空操作**（no-op）。
新版 7 个 skill 里没有任何硬编码的个人绝对路径，旧版也没有。所有个性化都在外部配置文件里，
升级 skill 文件**不会**动它们。真正要修的是那 5 个配置文件之间的矛盾和一条已经失效的 Hermes 路径。

---

## 1. 事实基线与口径

### 1.1 新版的物理形态

| 项 | 值 |
|---|---|
| 压缩包 | `D:/downloads/pika文件_Pro.zip`，**1451498774 B**，mtime `2026-10-30 23:32:07` |
| 条目数 | **2411**，全部 stored（不压缩），无目录条目 |
| 条目尺寸合计 | 1450343061 B（与上行的差 1155713 B = 本地头 + 中央目录，两者自洽） |
| 顶层 | 单一母目录 `pika文件_Pro/`，根下无散落文件 |

压缩包里套了 3 个压缩包（已剥，见 §1.2）：

| 容器（zip 内路径） | 压缩包本体 | 展开后 |
|---|---|---|
| `pika文件_Pro/笔记共享vault.zip` | 223808905 B | 1127 文件 / 245602915 B |
| `pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip` | 2026561 B | 488 文件 / 7190171 B |
| `pika文件_Pro/pika资料共享/代码与数据/grid-covering-lab-source.zip` | 62044 B | 48 文件 / 192845 B |

### 1.2 账目 reconciliation（三处口径都对得上）

```
4074 行（比对单元）        = 4071 展开文件 + 3 个嵌套容器
1703328992 B（行尺寸合计）  = 1477431482 B（展开）+ 225897510 B（3 个容器）
4071 展开文件              = 2408（外层散文件）+ 1127（vault）+ 488（toolkit）+ 48（gridlab）
```

**唯一容易搞错的地方**：`笔记共享vault.zip` 这一行在 `old_candidates.json` 里的 origin 是
`outer:zipfile` 而不是 `outer`。所以三个容器分属两种 origin：

| 容器 | origin | 是否计入 `outer` 的 2410 |
|---|---|---|
| `笔记共享vault.zip` | `outer:zipfile` | **否** |
| `AI工具/pika_math_learning_toolkit-2.1.7.zip` | `outer` | 是 |
| `代码与数据/grid-covering-lab-source.zip` | `outer` | 是 |

⇒ 外层散文件 = `2410 - 2 = 2408`（不是 `2410 - 3`），按 origin 分组统计时别漏掉那个 `outer:zipfile`。

### 1.3 五组「根」的对应（这是旧版散落位置的全部答案）

新版的东西不是散落在 D 盘任意层级 —— 它们**全部**落在 5 个确定的根下面，且每个文件保留自己的相对路径。

| # | zip 内的根 | D 盘旧版的根 | 依据 |
|---|---|---|---|
| 1 | `pika资料共享/开源资源/` | `D:/repo/Library/开源资源/` | 2223 对，2223 全 SAME |
| 2 | `pika资料共享/pika的presentations/` | `D:/repo/Library/pika的presentations/` | 65 对，65 全 SAME |
| 3 | `pika资料共享/代码与数据/` | `D:/repo/Tool/代码与数据/` | 34 对，34 全 SAME |
| 4 | `pika资料共享/AI工具/` | `D:/repo/知识库/pika文件_Pro/AI工具/` | 0 对（版本号变了，见 §5.3） |
| 5 | `__vault__/`（vault 包内） | `D:/repo/知识库/pika文件_Pro/笔记共享vault/` | 1079 对（1076 SAME / 3 DIFF） |
| 附 | `__gridlab__/`（gridlab 包内） | `D:/repo/Tool/代码与数据/grid-covering-lab-source/` | 48 对，48 全 SAME |
| 附 | `__toolkit__/payload/<skill>/` | `C:/Users/example/.dsh/skills/<skill>/` | 322 对（251 SAME / 71 DIFF） |

> 参照系提醒：`D:/repo/代码与数据` **已不存在**，只剩 `Tool/代码与数据`。
> 也就是说「代码与数据」这一级的搬迁**已经完成了**，不需要再搬。

### 1.4 证据等级

- **逐字节**：sha256，两侧都流式算（1 MiB 缓冲）。3771/3771 对全部算过，**0 个读取错误**。
- **全量落盘**：`inventory/b3_fullhash.tsv`（3771 行 / 1312577 B），
  表头 `zip_path  origin  new_size  new_sha256  old_path  old_size  old_sha256  verdict`，按 `zip_path` 排序。
  本报告正文只给聚合与抽样，**逐条证据在 TSV 里**，任何人可以 `grep` 复核。
- **抽样交叉**：上一轮用 243 个分层抽样验证过「同尺寸即同内容」，本轮全量复算把这个结论坐实了
  —— **同尺寸 ⇒ 逐字节相同，命中率 3697/3697**；不同尺寸 ⇒ 内容必不同，命中率 74/74。

---

## 2. 判据 1：逐条对应 + 内容级证据

### 2.1 主表（按区域聚合）

| 区域 | 行数 | 新版字节 | 对上 | SAME | DIFF | 新版独有 | 新版独有字节 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 开源资源 | 2306 | 1158432475 | 2223 | 2223 | 0 | 83 | 598032325 |
| 笔记共享vault（内层） | 1127 | 245602915 | 1079 | 1076 | 3 | 48 | 184022617 |
| 嵌套容器本身（vault.zip） | 1 | 223808905 | 0 | 0 | 0 | 1 | 223808905 |
| pika的presentations | 69 | 63920245 | 65 | 65 | 0 | 4 | 30917825 |
| toolkit skills | 488 | 7190171 | 322 | 251 | 71 | 166 | 1932435 |
| 代码与数据 | 34 | 2154875 | 34 | 34 | 0 | 0 | 0 |
| AI工具 | 1 | 2026561 | 0 | 0 | 0 | 1 | 2026561 |
| gridlab | 48 | 192845 | 48 | 48 | 0 | 0 | 0 |
| **合计** | **4074** | **1703328992** | **3771** | **3697** | **74** | **303** | **1040740668** |

读法：`对上` 是「路径 + 内容都能配上一一对应」的行数；`SAME` 是其中 sha256 完全相等的；
`DIFF` 是同路径但内容不同（逐条列在附录 A）；`新版独有` 是 D 盘找不到对应物的。

### 2.2 抽样：三种原子证据

**（a）典型 PDF —— 两侧 hash 完全相同**

```
zip_path : pika资料共享/pika的presentations/防御性证明.pdf
old_path : Library/pika的presentations/防御性证明.pdf
new: 484231 B  ba084252f910533e3a220bb83c180ef60e58f0dd1c4b7b469a0138716650c2f7
old: 484231 B  ba084252f910533e3a220bb83c180ef60e58f0dd1c4b7b469a0138716650c2f7
verdict: SAME
```

**（b）典型 markdown 笔记**

```
zip_path : __vault__/math/插值不等式.md
old_path : 知识库/pika文件_Pro/笔记共享vault/math/插值不等式.md
new: 8302 B  fdfb88635284a6a2f6ac047f732b189ed0b7a1dc5c4d8776583d199e6f436526
old: 8302 B  fdfb88635284a6a2f6ac047f732b189ed0b7a1dc5c4d8776583d199e6f436526
verdict: SAME
```

**（c）两条路径各自独立的判据 —— 相对路径恒等**

我另外做了一次「剥根后相对路径」恒等检查：把每个 `zip_path` 和对应 `old_path` 各自去掉自己的根前缀，
比较剩余部分。**3771/3771 完全相同，0 例外。** 这解释了为什么 §4 的结论是「文件层没有搬动」：

| 行类型 | zip 侧剥法 | old 侧剥法 |
|---|---|---|
| outer | 去 `pika资料共享/<子根>` | 去 `Library/<子根>` 等 |
| vault | 去 `__vault__/` | 去 `知识库/pika文件_Pro/笔记共享vault/` |
| toolkit | `split('/')[3:]`（注意：**索引是 3 不是 4**） | 定位 `skills` 段后 `+2` |
| gridlab | 去 `__gridlab__/` | 去 `Tool/代码与数据/grid-covering-lab-source/` |

> 坑：这一检查我第一次写成「取最短匹配前缀」，`gridlab` 行会被短前缀 `Tool/代码与数据` 抢走，
> 报出 48 个假不匹配。**必须取最长匹配前缀。** 改完即 0。

### 2.3 PDF 单独交代（占绝对多数，按聚合写、不逐个列）

用户提示里说「PDF 占 82.52%」是**按条目总数**的口径，实测按字节算是这样：

| 口径 | PDF | 非 PDF |
|---|---|---|
| 行数 | **2344 / 4074 = 57.54%** | 1730 |
| 字节 | **1219147083 / 1703328992 = 71.57%** | 484181909 |
| 对上且 SAME | **2258（100%，0 个 DIFF）** | 1439 |
| 对上但 DIFF | **0** | 74 |
| 新版独有 | 86 / 626787259 B | 217 / 413953409 B |

**PDF 这一边是最干净的**：2258 个能对上的 PDF，**全部逐字节相同，没有一个不同**。
所有 74 个 DIFF 都在非 PDF（3 个 vault 文本 + 71 个 skill 文件），合计只有 1823157 B。

---

## 3. 判据 3：skills 实测条数与名字

### 3.1 实测：**7 个**

工具包 `pika_math_learning_toolkit-2.1.7.zip` 共 488 个文件条目，`payload/` 下正好 **7 个目录**。
每个 skill 在 zip 里的完整路径是（外层包 → 内层包 → payload）：

```
D:/downloads/pika文件_Pro.zip
  └─ pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip
       └─ payload/<skill>/
```

| # | skill 名 | zip 内完整路径 | 文件数 | 新版 SKILL.md 版本 |
|---|---|---|---:|---|
| 1 | `compute-fleet-manager` | `pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip!payload/compute-fleet-manager/` | 16 | v1.0.6 |
| 2 | `manage-personal-knowledge` | `…!payload/manage-personal-knowledge/` | 57 | v1.11.5 |
| 3 | `math-coach` | `…!payload/math-coach/` | 97 | v1.13.0 |
| 4 | `math-research-solve` | `…!payload/math-research-solve/` | 115 | v3.2.8 |
| 5 | `math-science-computation` | `…!payload/math-science-computation/` | 59 | v1.12.0 |
| 6 | `obsidian-vault-notes` | `…!payload/obsidian-vault-notes/` | 81 | （SKILL.md 无 `version:` 行，只有 description；包级版本 1.13.5） |
| 7 | `pdf-problem-search` | `…!payload/pdf-problem-search/` | 42 | v1.12.3 |

`payload/` 外还有 21 个文件（146325 B）：17 个包顶层文件
（`package-manifest.json`、`install.py`、`checksums.sha256`、`SOURCE_VERSIONS.json`、`RELEASE_NOTES.md`、
`START_HERE.md`、`PORTABLE_ADAPTATIONS.json`、`PRIVACY_REPORT.md`、`TEST_MATRIX.md`、`AGENTS.md`、
`CLAUDE.md`、`GEMINI.md`、`AGENT_INSTALL.md`、`INSTALL_PROMPT.md`、`INSTALL_TEST_RECEIPT.json`、
`INSTALL_WINDOWS.cmd`、`install.sh`）与 `tests/` 下 4 个。**这 21 个不属于任何 skill**，
在旧版 `C:/Users/example/.dsh/skills/` 里也没有对应物（`no_old_root`），**不要往 skills 目录里装**。

依据 `package-manifest.json`：artifact 版本 **2.1.7**，type `portable-skill-suite`，
`payload_root` = `payload/manage-personal-knowledge` ⇒ **`manage-personal-knowledge` 是主 skill，其余 6 个是依赖**；
`update_policy` = `stop-unless-replace`（不整包替换就停），`transaction` = `all-payloads`（7 个必须一起换）。
依赖图：`manage-personal-knowledge` → [`obsidian-vault-notes`, `pdf-problem-search`]；
`pdf-problem-search` → [`obsidian-vault-notes`]；`math-research-solve` → [`math-science-computation`, `obsidian-vault-notes`]；其余 4 个无依赖。

### 3.2 旧版实际情况：装了 6 个，差一个

| skill | 旧版安装位置 | 旧版版本 | 新版版本 |
|---|---|---|---|
| `compute-fleet-manager` | **不存在** | — | v1.0.6 |
| `manage-personal-knowledge` | `C:/Users/example/.dsh/skills/` | v1.11.3 | v1.11.5 |
| `math-coach` | 同上 | v1.12.1 | v1.13.0 |
| `math-research-solve` | 同上 | v3.1.11 | v3.2.8 |
| `math-science-computation` | 同上 | v1.11.4 | v1.12.0 |
| `obsidian-vault-notes` | 同上 | v1.13.3 | 1.13.5 |
| `pdf-problem-search` | 同上 | v1.12.2 | v1.12.3 |

旧版工具包版本是 **2.1.4**（`知识库/pika文件_Pro/AI工具/pika_math_learning_toolkit-2.1.4.zip`，339 文件）。
我逐字节比过：**该 zip 的 322 个 payload 文件与 `C:/Users/example/.dsh/skills/` 下安装的树 322/322 全部相同，
0 diff、0 missing** ⇒ 现在装着的这 6 个 skill 就是工具包 2.1.4 的原样，没有被本地改过。
版本链 2.1.0 → 2.1.1 → 2.1.2 → 2.1.4 → 2.1.7。

### 3.3 安装拓扑（审计必读，别以为只有一处）

| 位置 | 形态 | 状态 |
|---|---|---|
| `C:/Users/example/.dsh/skills/` | **真实目录**（不是 junction，`os.lstat` reparse=False） | 6 个 pika skill 在这，是**唯一实物** |
| `C:/Users/example/.dsh/skills-math/` | 6 个 **junction**（2026-10-23 23:29）→ `C:/Users/example\.dsh\skills\<skill>` | 只是链接，改实物即可 |
| `C:/Users/example/.dsh/skills-softeng/` | 9 个 `pipe-*` / `softeng-manage` | 与 pika 无关 |
| `C:/Users/example/.dsh/skill-library/` | 空 | 无 |
| `D:/Hermes Agent CN Desktop/data/hermes-home/skills/` | **旧的安装目标，6 个 pika skill 已不在**（现存 26 个无关 skill 目录） | `INSTALL_REPORT.json` 记录的 target_root 已失效 |
| `C:/Users/example/.dsh/profiles/desktop/` | 只有 plugin，无 skills 子目录 | 与 skills 无关 |

`C:/Users/example/AppData/Local/pika_math_learning_toolkit/INSTALL_REPORT.json` 证明旧版
**确实装过**（`status: installed`，`timestamp_utc 2026-09-12T09:48:24Z`，`checksums_verified: 289`），
目标就是那个 Hermes 根，6 个 skill 的备份也都还在 `backups/` 下。
**⇒ 现在存在「第三份残留」的风险：Hermes 根虽然空了，但备份目录里还有整套旧版。
B5 不要从备份恢复任何东西，否则会把已经下线的 Hermes 路径复活。**

### 3.4 有 3 个 skill 当前是**停用**状态（不是卸载）

`C:/Users/example/.dsh/skills-manager/state.json` 的 `disabledSkills.dsh` 含
`math-coach`、`math-research-solve`、`math-science-computation`
（日志 `dsh-skills-manager.log` 有 `policy-disable` 事件，2026-10-24T14:15:42/44/47Z，
detail 写的是「停用 …（本地策略，源文件不变）」）。**源文件完好。**
B5 换完文件后，这个停用标记会**照旧生效** —— 如果用户希望这三个换完就能用，得另外去开。

---

## 4. 判据 2：「层级已变动」专节

### 4.1 结论：层级变动在**容器层**，不在文件层

用户说「我整理的时候把那个文件的层级有所变动」。实测结果是：

> **3771 个能对上的文件，剥掉各自的根之后，相对路径 100% 相同（3771/3771）。**
> 所以用户所说的「层级变动」，指的是**上一级容器被挪到了别的地方**（甚至换了盘符、换了父目录名），
> 而**文件与文件之间的相对位置一个都没变**。

换句话说：不需要为任何一个文件猜测「它现在在哪个层级」。只要把根对上，整棵树就对上了。

### 4.2 五组「路径对不上但内容对得上」的对子

这是本判据要的交待。每一组都给「凭什么认定是同一份」：

| # | 新版根 | 旧版根 | 凭什么认定同一 |
|---|---|---|---|
| 1 | `pika资料共享/开源资源` | `Library/开源资源` | 2223 对 sha256 **全部相同**；剥根后相对路径 2223/2223 相同；旧侧目录名 `开源资源` 在全盘 246 个同名目录里全部落在此根下 |
| 2 | `pika资料共享/pika的presentations` | `Library/pika的presentations` | 65 对 sha256 全相同；相对路径 65/65 相同 |
| 3 | `pika资料共享/代码与数据` | `Tool/代码与数据` | 34 对 sha256 全相同；旧版 `D:/repo/代码与数据` 已不存在，`Tool/` 下是唯一一份 |
| 4 | `pika资料共享/AI工具` | `知识库/pika文件_Pro/AI工具` | 唯一文件是工具包本身，**旧 2.1.4 / 新 2.1.7**，靠 `package-manifest.json` 的 artifact 版本号认定同一产物；旧包 322 个 payload 与已安装树 322/322 逐字节相同 |
| 5 | `__vault__/`（vault 包内） | `知识库/pika文件_Pro/笔记共享vault/` | 1079 对，1076 对 sha256 相同、3 对不同（附录 A 前三行，均为已知且新版更优）；相对路径 1079/1079 相同 |
| 附A | `__gridlab__/` | `Tool/代码与数据/grid-covering-lab-source/` | 48 对 sha256 **48/48 全相同**；且 `Tool/代码与数据/grid-covering-lab-source.zip`（62044 B，deflate）解出来的 48 个条目与这个目录 **48/48 同 hash** ⇒ 一份 payload 三个容器 |
| 附B | `__toolkit__/payload/<skill>/` | `C:/Users/example/.dsh/skills/<skill>/` | 322 对，251 对 sha256 相同、71 对不同（版本 2.1.4→2.1.7 的差距，附录 A） |

### 4.3 反证：新版独有的 303 个文件，有没有可能是「被搬走的旧文件」？

这个必须证，否则「新版独有」里可能藏着用户整理时挪走的旧版。做法：把 303 个新文件的 sha256
拿到全盘去撞（`D:/repo` 全索引 274763 个文件，按体积分组后 3166 个候选 / 59 MB / 3196 对全算）。

- **真正撞上的只有 4 个，而且全部落在 `program/engineering/blobs/`** —— 那是本工程流水线的
  **gitignore 二进制 CAS**（`docs/subsystems/ci/README.md:44` 明确写了 `blobs/` 进 `.gitignore`），
  **不是用户的内容树**。这 4 个是流水线自己存的暂存副本，不是「旧版藏在这里」：
  - `开源资源/名人采访/snow_1959 two cultures.pdf` 2152723
  - `开源资源/组合学/(Ben Green)sumsets-sumfreesets.pdf` 4435740
  - `开源资源/数论基础/丢番图逼近/metric number theory.pdf` 40774499
  - `开源资源/数论基础/陶哲轩254A解析数论/无穷递降法/on fermat's method of infinite descent.pdf` 3183551
- **其余 299 个：全盘没有任何逐字节相同的文件。** 我另外核对了它们「本该在的父目录」确实没有它们
  （例：`Library/开源资源/名人采访` 有 22 个文件但没有 snow_1959；
  `Library/开源资源/数论基础/丢番图逼近` 里有个 `Metric-Number-Theory-notes.pdf` 343609 B，是**另一个文件**，不是那个 40 MB 的）。

**⇒ 结论：303 个全是真正的新增内容，没有一个是「被搬走的旧文件」。**
这一条与上一轮用文件名搜索得到的结论一致，但这一轮用的是 hash，比文件名可靠。

### 4.4 一个特例要说清：gridlab 有两个「只差排版」的副本

| 位置 | 文件数 | 字节 |
|---|---:|---:|
| `Tool/代码与数据/grid-covering-lab-source/`（= zip 内 gridlab 包解开） | 48 | 192845 |
| `知识库/pika文件_Pro/笔记共享vault/math/代码/grid-covering-lab/` | 48 | **192909**（多 64 B） |

多出来的 64 B **不是内容差异，是排版差异**：3 个文件把 ASCII 连字符 `-` 换成了 `‐`（U+2010 HYPHEN）：

| 文件 | A（192845 侧） | B（192909 侧） | U+2010 个数 | 字节差 |
|---|---:|---:|---:|---:|
| `AI_AGENT_ONE_SHOT.md` | 3936 | 3942 | 3 | +6 |
| `README.md` | 9787 | 9823 | 18 | +36 |
| `README_AGENT.md` | 5590 | 5612 | 11 | +22 |

把 U+2010 全部换回 `-` 之后，这三个文件**逐字节相同**（`identical=True`）。
其余 45 个文件（含 `D:/repo\_tools\pika-迁移\_extracted\grid-covering-lab-source\src\grid_covering_lab\app.py` 3836 B、`geometry.py` 8012 B）本来就同 hash。
**⇒ 同一份发布的两个排版变体，不是两个版本。** 升级时以 `Tool/代码与数据/grid-covering-lab-source/` 为准即可，
vault 里那份可以不动（它属于笔记库内部引用）。

### 4.5 还有两个 one-to-many 的候选，都已判掉

**（A）`.obsidian` 配置目录有三份**

| 位置 | 文件数 | 字节 | 与 zip 内 `.obsidian` 的 hash 比对 |
|---|---:|---:|---|
| zip 内 `笔记共享vault/笔记共享vault/.obsidian/` | 14 | 16970550 | （基准） |
| `知识库/pika文件_Pro/笔记共享vault/.obsidian/` | 14 | 16970323 | **13/14 相同**，只有 `workspace.json` 不同（zip 7924 vs 盘 7697） |
| `知识库/.obsidian/` | 15 | 16973207 | **11/14 相同**；`appearance.json` 130 vs 221、`graph.json` 667 vs 658、`workspace.json` 7697 vs 7412，且多一个 `snippets/bold-use-real-pjp-b.css` 3087 B |

**判定：内层（`知识库/pika文件_Pro/笔记共享vault/.obsidian`）是升级目标；外层 `知识库/.obsidian` 是用户
真正在用的那个库自己的配置，绝对不能当 pika 的副本覆盖。** 依据是 Obsidian 自己的注册表
`C:/Users/example/AppData/Roaming/obsidian/obsidian.json`（原样）：

```json
{"vaults":{"bcdcbb444ed9fb91":{"path":"D:/repo\\知识库","ts":1793267830128,"open":true}},"frame":"hidden","openSchemes":{"mailto":true}}
```

**只注册了一个库，就是 `知识库`（外层）。** 修改时间也支持这个判断：外层 `.obsidian` 是 `2026-09-24 19:29:45`，
内层是 `2026-10-03 21:41:41`（内层更新，与外层是主库不矛盾 —— 内层是 pika 分发的快照）。

**（B）gridlab 三容器** —— 已在 §4.2 附 A 判完：一份 payload、三个容器（外层包内嵌 zip / 落的 .zip 文件 / 解开目录），
外加 §4.4 的排版变体。

---

## 5. 个性化配置：真正要「回填」的东西在哪

### 5.1 先说结论：skill 文件里没有个性化设置，回填是空操作

我把旧版 6 个 skill 与新版 7 个 skill 的 `.md / .yaml / .yml / .json` 全扫了一遍，
正则找 `jelly_ware | D:/docs | Hermes Agent | AppData | .dsh/skills | 知识库 | 题库 | Library`。
旧版命中 6 个文件、新版命中 12 个文件，逐行看过之后：

| 命中的文件 | 命中的内容 | 新版是否相同 |
|---|---|---|
| `manage-personal-knowledge/references/question-database.md:21` | 「The default discovery root is `数据/题库` relative to `knowledge_root`…」 | **逐字节相同** |
| 同上 `:33 / :39 / :50 / :73` | `--source-relative "数据/题库/2017—2026年高考数学真题逐题库"` 等示例 | **逐字节相同** |
| `manage-personal-knowledge/references/terminology-registry.json:129` | `"display_name_zh": "结构化题库覆盖状态"` | **相同** |
| `math-coach/references/operations.md:40` | 默认 DB 路径 `%LOCALAPPDATA%\MathCoach`（Win）/ `~/Library/Application Support/math-coach`（mac）/ `${XDG_STATE_HOME:-~/.local/state}/math-coach`（Linux） | **相同** |
| `math-coach/references/harness-contract.md:5` | DB 表清单（problems, sessions, turns, …） | **相同** |
| `manage-personal-knowledge/references/pdf-library.md`、`pdf-problem-search/references/direct-pdf-operations.md` | 只是泛泛提到 `Library` 这个词，不是个人路径 | 相同 |

**⇒ 用户记忆里「对某些题库、知识库根目录做出了明确的规定」的那个规定，
不是写在 skill 里，而是写在外部的配置文件里。所以「把旧版的配置回填到新版」在文件层面无事可做 ——
升级 skill 不会影响这些配置，它们本来就在 skill 目录外面。**

另外确认：`zip_path` 里含 `知识库` / `Library` / `jelly_ware` / `AppData` 的行数 **都是 0**
⇒ 新版 payload 内部也没有夹带任何个人绝对路径。

### 5.2 真正的配置在这儿：5 个文件，其中 3 个互相矛盾

**（1）`C:/Users/example/AppData/Roaming/manage-personal-knowledge/config.json`**（474 B，schema v2，Oct 24 10:24）

```json
{
  "knowledge_root": "D:/repo",
  "knowledge_root_id": "KBROOT-442OME7QWTER5T5W7OO7RGNPB4",
  "knowledge_root_name": "jelly_ware",
  "registry": {"excluded_relative_paths": [], "manifest_relative_path": ".mpk/resources.jsonl"},
  "sources": {
    "library": {"kind": "pdf-library", "relative_path": "Library"},
    "vault":   {"kind": "obsidian-vault", "relative_path": "知识库"}
  }
}
```

**这是最重要的一份，也是最新的一份（schema v2）。** 注意 `vault.relative_path` = `知识库`（外层库），
不是 `知识库/pika文件_Pro/笔记共享vault`。这与 Obsidian 注册表一致（§4.5A）。

**（2）`C:/Users/example/AppData/Roaming/manage-personal-knowledge/obsidian-vault-notes.json`**（313 B，Sep 12 18:54）

```
vault_root : D:/repo\知识库
kb_root    : D:\Hermes Agent CN Desktop\data\hermes-home\skills\obsidian-vault-notes\scripts\obsidian_local_kb   ← 已失效
db_path    : C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3           ← 存在
```

**（3）`C:/Users/example/AppData/Roaming/pika_math_learning_toolkit/config.json`** —— schema **v1** 旧副本，
内容与（1）等价（同 `knowledge_root`、同 `Library` / `知识库` 两个 source），但**没有** `knowledge_root_id` 与 `registry`。

**（4）`C:/Users/example/AppData/Roaming/pika_math_learning_toolkit/obsidian-vault-notes.json`**

```
vault_root : D:/repo\知识库
kb_root    : C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb   ← 这条的父目录存在
db_path    : C:/Users/example\AppData\Local\obsidian-vault-notes\vault.sqlite3
```

**（5）`C:/Users/example/AppData/Roaming/obsidian-vault-notes/config.json`**（旁边还有个
`config.json.bak-20261024-102212` 备份）

```
vault_root : D:/repo\知识库
kb_root    : D:\Hermes Agent CN Desktop\data\hermes-home\skills\obsidian-vault-notes\scripts\obsidian_local_kb   ← 已失效
db_path    : C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3
```

### 5.3 矛盾点与「哪份生效」

三份 `obsidian-vault-notes` 的 JSON（2）（4）（5）在 **`kb_root` 与 `db_path` 上都不一致**，而且

- `kb_root` 指向的 Hermes 路径 **实测不存在**：`D:/Hermes Agent CN Desktop/data/hermes-home/skills/`
  下现存 26 个无关 skill 目录（`analyse/ apple/ … grill-me/ … yuanbao/`），**没有任何一个 pika skill**。
  只有（4）的 `C:/Users/example/.dsh/skills/obsidian-vault-notes/…` 这一支是真的存在。
  代码里 `setup_local.py:139` 会校验 `kb_root` 下 `obsidian_local_kb/__main__.py` 是否存在，
  **失效路径会显式报错，不会静默走错**。
- `db_path` 有两种：`…/obsidian-vault-notes/vault.sqlite3`（不存在）与
  `…/pika_math_learning_toolkit/obsidian-vault-notes/vault.sqlite3`（**存在**，带 `-wal` / `-shm`）。

**哪份生效？看代码：** `obsidian-vault-notes/scripts/setup_local.py`

```
:23  return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
:31  return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
:38  override = os.environ.get("OBSIDIAN_VAULT_NOTES_CONFIG")
:41  return (platform_config_root() / SKILL_NAME / "config.json").resolve()
:77  environment["OBSIDIAN_VAULT_NOTES_CONFIG"] = str(config)
```

`SKILL_NAME` = `obsidian-vault-notes` ⇒ **生效的是（5）`%APPDATA%/obsidian-vault-notes/config.json`**，
而它的 `kb_root` 正是**已失效**的 Hermes 路径。
`manage-personal-knowledge` 读的是 `%APPDATA%/manage-personal-knowledge/config.json`，即（1）。
（3）（4）是旧命名空间留下的孤儿，除非有 `*_CONFIG` 环境变量指过去，否则不生效。

### 5.4 配置解析代码：新版与旧版**相同**

我比过两侧的 `config.py` / `setup_local.py` 关键行，**路径解析逻辑一字未改**
（`MPK_CONFIG_PATH` / `APPDATA` / 回落 `base/"manage-personal-knowledge"/"config.json"`；
state 目录 `MPK_STATE_DIR` / `LOCALAPPDATA`；`SUPPORTED_SCHEMA_VERSIONS` 与 v1→v2 迁移路径）。
**⇒ 换新 skill 之后，读的还是同样的位置、同样的文件名。不会因为升级而「找不到配置」。**

### 5.5 「题库」这条个性化设置，磁盘上根本没有对应目录

`manage-personal-knowledge/references/question-database.md:21` 规定默认题库发现根是
`数据/题库`（相对 `knowledge_root`），识别标志是 `source-manifest.json` / `work/receipt.json` /
`work/collection_index.sqlite3` 之一。实测：

- `D:/repo/数据` **不存在**（`ls` 报 No such file or directory）。
- 深度 6 以内**没有任何** `source-manifest.json` / `collection_index.sqlite3`。

**⇒ 题库联邦是空的。这条个性化设置只存在于文档里，没有盘上实体。**
新版这一行与旧版逐字节相同，所以**不需要回填，也不需要新建目录**（要建也是用户的决定，见 §8）。

### 5.6 知识库 root 的现状与一处不一致

| 项 | 值 |
|---|---|
| `knowledge_root` | `D:/repo` |
| `knowledge_root_id` | `KBROOT-442OME7QWTER5T5W7OO7RGNPB4` |
| `D:/repo/.mpk/root.json` | **存在**：`{"knowledge_root_id": "KBROOT-442OME7QWTER5T5W7OO7RGNPB4", "knowledge_root_name": "jelly_ware", "schema_version": 1}` |
| `D:/repo/.mpk/resources.jsonl` | **存在**（308 B，1 行，manifest 记录，`generation: 0`，`vault_relative_path: "知识库"`） |
| `D:/repo/知识库/.mpk/root.json` | **不存在**（配置说是 knowledge_root，但这个子标记缺） |
| registry SQLite | `C:/Users/example/AppData/Local/manage-personal-knowledge/registry.sqlite3` 86016 B；表 `registry_meta, resources, path_history, sqlite_sequence, resource_versions, note_documents, note_references, operation_log`；`resources` 0 行、`note_documents` 0 行 ⇒ **初始化过但从未登记资源** |
| PDF 索引 | `…/manage-personal-knowledge/library.sqlite3` **448417792 B**（Sep 15 13:41）—— 真正在用的 PDF 索引 |
| `Library` 目录 | 存在，2379 文件 |

`D:/repo` 下共发现 **5 个** `.obsidian`：
`知识库/.obsidian`、`知识库/pika文件_Pro/笔记共享vault/.obsidian`、`研究项目/工作材料/_备份_含备注版_20260916/.obsidian`、
`研究项目/工作材料/_纯净版/.obsidian`、`课程与学习/my_python project/.obsidian`。
**配置选的是最外层 `知识库`**，与 Obsidian 注册表一致。

### 5.7 历史坑（配置时别踩）

`.obsidian` **不能**被当成知识库根 —— 历史上出过「知识库根子孙里含 `.obsidian` 导致 library 候选被剪成 0」的 bug，
当时的修法是把 `D:/docs\知识库\Library` 物理搬到 `D:/docs\Library`。
现在 Library 是 `D:/repo\Library`（在 `knowledge_root` 之下、与 `知识库` 平级），**配置时再确认一次**。

---

## 6. 给 B5 的执行方案（本报告不执行，只写清怎么做）

前提：**先备份**，再动手；**不要**从 `AppData/Local/pika_math_learning_toolkit/backups/` 恢复任何东西（§3.3）。

### 6.1 三个区域，三种处理

| 区域 | 现状 | B5 要做什么 |
|---|---|---|
| 开源资源（2306） | 2223 对上且全 SAME，83 新版独有 | 只**新增** 83 个，**不覆盖**任何已存在文件（内容已相同，覆盖是纯风险） |
| pika的presentations（69） | 65 全 SAME，4 新增 | 只**新增** 4 个 |
| 代码与数据（34）+ gridlab（48） | 全部 SAME | **无需任何操作** |
| 笔记共享vault（1127） | 1076 SAME / 3 DIFF / 48 新增 | 新增 48；3 个 DIFF 见 §6.3 决策 |
| toolkit skills（488） | 322 对上（251 SAME / 71 DIFF）+ 166 新版独有 | 按 2.1.7 整包替换 6 个已装 skill，**另加** `compute-fleet-manager`（见 §8 决策 D3） |
| AI工具（1） | 新版 2.1.7 zip，旧版 2.1.4 zip | 放入 2.1.7 zip；旧的 2.1.4 zip 是否删见 §8 决策 D4 |

### 6.2 解压口径（两个坑，都会让人解错位置）

1. **vault 包要剥两层。** `笔记共享vault.zip` 里的条目形如
   `笔记共享vault/笔记共享vault/<真实内容>`（深度分布 `{3:571, 4:473, 5:69, 6:6, 7:8}`）。
   只剥一层会得到 `笔记共享vault/笔记共享vault/...` 的套娃。
   注意 `_extracted/笔记共享vault/` 目录里是**三层**（`_extracted/笔记共享vault/笔记共享vault/笔记共享vault/<真实内容>`），
   那是上一轮解压时的历史产物，**别拿它当标准**。
2. **外层包条目名要带 `pika文件_Pro/` 前缀**，否则 `zo.open()` 抛
   `KeyError: There is no item named '…' in the archive`。
   三个嵌套包的准确键名：
   `pika文件_Pro/笔记共享vault.zip`、
   `pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip`、
   `pika文件_Pro/pika资料共享/代码与数据/grid-covering-lab-source.zip`。

### 6.3 三个 DIFF 的 vault 文件，逐个人工确认过（可以直接照这个判）

| 文件（相对 vault 根） | 新 | 旧 | 差异实质 | 建议 |
|---|---:|---:|---|---|
| `.obsidian/workspace.json` | 7924 | 7697 | 纯 UI 状态（窗口/面板布局），无内容 | **保留旧版**（覆盖只会让 Obsidian 重新排列面板） |
| `math/一致几乎处处有界函数列算术平均值几乎处处收敛的问题.md` | 8118 | 8117 | **1 处，+1/−1**：`…非常类似：` → `…非常类似 ：`（冒号前多一个空格） | 用新版（无害），或干脆跳过 |
| `math/模长总和为1的n个复数中，至少能合成一个模长多大的复数.md` | 13497 | 8431 | **15 处，+82/−32**，真扩写：`> [!note] CMO 1986,p3` → `> [!question] 问题0：CMO 1986,p3`，并新增一大段「对于"问题0"，我们可以一句话理解为：…」 | **用新版**（内容明显更完整） |

### 6.4 三个「看起来要做、其实不用做」的

1. **2 个 SVG 不要恢复。** `AI工具/图片/human_obsidian_ai_collaboration.svg` / `…_v2.svg`
   在旧版里没有（新版独有），但上一轮已判定是**有意删除**：正文
   `AI工具/把ai agent接入obsidian笔记库.md` 里对它们**零引用**，同一位置用的是两个 GIF
   （`图片/ai_obsidian_agent_loop.gif` 837024 B 在第 45 行、`…_v2.gif` 811321 B 在第 63 行，都还在），
   而且那两个 SVG 的 `<title>` 自己写着「**旧**人机协作模式示意图」。
   ⇒ 新版带着它们回来是**打包时的历史残留**，不是要恢复。
2. **`_observer-tools/` 不要动。** `知识库/pika文件_Pro/_observer-tools/` 4 个文件
   （`README.md` 4269、`_diag_pdf.py` 2798、`_list_notext.py` 1886、`observer_receiver.py` 18437，Sep 12）
   在 zip 的 4074 行里**一条都没有** ⇒ 是旧版本地杂物，不属于本次升级。
3. **2 个 remotion zip 不用管。** `思考随笔/assets/人类与AI共同写作动画/remotion-project.zip` 1815414
   与 `…/写作是一种认知编码/cognitive-encoding-remotion-source.zip` 43385 **都在 zip 里且都 SAME**
   ⇒ 跟其他文件一样处理即可。

### 6.5 执行顺序建议

1. 备份：`Tool/代码与数据/`、`Library/开源资源/` 的「将在 B5 新增的部分」不需要备份（全是新增），
   但 **vault 3 个 DIFF + 6 个 skill 目录必须先整体复制一份**（skills 已有 2026-09-12 的 pre-update 备份，
   再打一份当前状态的）。
2. 先做**纯新增**的区域（开源资源 83、presentations 4、vault 48、代码与数据 0、gridlab 0）—— 零覆盖、零删除。
3. 再做 vault 的 3 个 DIFF（按 §6.3）。
4. 最后做 skills（整包换 6 个 + 是否加第 7 个由用户定）。**skills 放在最后**，因为它有 `stop-unless-replace` 与
   `all-payloads` 的事务约束，必须 7 个（或 6 个）一次性换完，中途失败要能回滚。
5. 换完 skills 后，**去检查三份 `obsidian-vault-notes` 配置**，把生效的那份（§5.3：`%APPDATA%/obsidian-vault-notes/config.json`）
   的 `kb_root` 从失效的 Hermes 路径改到实际位置。
6. 全程**不删** `D:/downloads/pika文件_Pro.zip`。

---

## 7. 「不知道」清单（如实，不编）

按重要性排序。前面标 ★ 的是会影响执行的。

1. ★ **用户到底想让哪个 vault 被「升级」。** zip 里的是内层库 `知识库/pika文件_Pro/笔记共享vault`（1127 文件），
   而 Obsidian 实际打开的、配置里 `sources.vault` 指向的，都是外层 `知识库`（1392 文件）。
   两者不是同一个库。**我无法从现有证据判断用户认为「我的笔记库」是哪一个。**
2. ★ **`compute-fleet-manager` 该不该装。** 它在新包里（16 文件 / v1.0.6），旧版从未安装过。
   `package-manifest.json` 把它算作依赖之一（7 个 payload 一起事务），但用户从没提过这个 skill。
3. ★ **三份 `obsidian-vault-notes` 配置哪一份是「用户的意图」。** 生效的是（5），但它指向已失效的 Hermes 路径；
   唯一路径存在的是（4）。我无法判断用户是**想**用 `.dsh/skills` 下的那份，还是想用别的。
4. **`知识库/.mpk/root.json` 为什么不存在。** 配置声明 `knowledge_root_id = KBROOT-442OME…`，
   `D:/repo\.mpk\root.json` 在 `D:/repo/.mpk/` 下有，但 `知识库/.mpk/` 下没有。不知道是漏写还是有意。
5. **`代码与数据` 是什么时候、为什么从 `D:/repo/代码与数据` 搬到 `Tool/代码与数据` 的。**
   搬迁已完成（旧位置不存在），但没有任何记录说明时间点。
   对执行无影响（只要根对上），所以不阻塞。
6. **`知识库/Codex Skills/` 下 3 个 0 字节 `SKILL.md` 是谁造的。**
   已定位：`知识库/Codex Skills/obsidian-vault-notes/SKILL.md`（0 B，目录 Sep 13 18:23）、
   `知识库/Codex Skills/pdf-problem-search/SKILL.md`（0 B，目录 Sep 07 21:45）、
   `知识库/pika文件_Pro/Codex Skills/manage-personal-knowledge/SKILL.md`（0 B，目录 Sep 06 17:23），
   每个父目录里只有这一个空文件。看起来是早期尝试留下的空壳，**但不知道用户是否还想用这个位置**。
7. **vault 在 git 最后一次提交（`924c087`，2026-09-14 18:42）之后改了多少。**
   我只做了 11 篇笔记的三方比对（结论：**磁盘 == zip，11/11 逐字节相同**，所以 zip 不会盖掉任何手改；
   其中 2 篇与 git 只差行尾，9 篇是 git 落后），**没有**对全部 1080 个文件做三方比对。
   ⇒ 「zip 覆盖不会丢失磁盘上的手改」这个结论在 11 篇采样上成立，全量未验证。
8. **`知识库/Jelly文件_Pro`（271 文件 / 293115084 B）是什么。** 它与 pika 无关（zip 里 0 条对应），
   但占了整个 `知识库` 一半以上的体积，不知道是否该留在 vault 里。
9. **`用概率计算含参数积分的极限.md`（旧版独有，10001 B，tags `math, tool_idea`）该不该留。**
   见 §8 决策 D2 —— 我有证据说明它不是新版某篇的「旧版」，但不知道用户要不要保留这个草稿。

---

## 8. 需要用户拍板的决策点

真跑请另开 **B5** 并让人确认。下面每一条都给「不拍板会怎样」。

| # | 决策 | 选项 | 不拍板的后果 |
|---|---|---|---|
| **D1** | **升级哪个 vault？** | (a) 内层 `知识库/pika文件_Pro/笔记共享vault`（zip 对应它，1079 对已验）；(b) 外层 `知识库`（Obsidian 实际打开的） | 选错就是把新内容铺进一个用户不打开的地方，或者把一个用户没要的结构塞进主库 |
| **D2** | **`math/用概率计算含参数积分的极限.md` 怎么办** | (a) 保留（它是独立草稿）；(b) 归档到 `_archive/`；(c) 删 | 它是**唯一一个只在旧版存在**的内容文件。删了就没了 |
| **D3** | **`compute-fleet-manager` 装不装** | (a) 装（7 个齐全，符合 manifest 事务）；(b) 不装（只换 6 个，与旧版一致） | 装了会多一个用户没要的 skill；不装则 `all-payloads` 事务约束被人为打破，manifest 的 `stop-unless-replace` 可能报错 |
| **D4** | **旧的 `pika_math_learning_toolkit-2.1.4.zip` 删不删** | (a) 删（新版 2.1.7 已就位）；(b) 留着当回滚点 | 留着只是占 1367591 B；删了就没有这个精确回滚点了 |
| **D5** | **三份 `obsidian-vault-notes` 配置怎么收口** | (a) 只修生效那份（`%APPDATA%/obsidian-vault-notes/config.json`）的 `kb_root`；(b) 三份都改成同一个值；(c) 删掉两个孤儿（`pika_math_learning_toolkit/` 与 `manage-personal-knowledge/` 下的） | 不修则 `kb_root` 继续指向不存在的 Hermes 路径，`setup_local.py` 的健康检查会一直报错 |
| **D6** | **`数据/题库` 要不要建** | (a) 不建（保持现状，题库联邦为空）；(b) 建空目录 + 把现有题库搬进去 | 建了但没内容等于空；如果把散落的题库搬进去，那是一次新的目录整理，风险另算 |
| **D7** | **3 个停用的 skill 换完要不要启用** | (a) 保持停用（`math-coach` / `math-research-solve` / `math-science-computation`）；(b) 启用 | 换完仍是停用状态，用户可能以为升级没生效 |
| **D8** | **vault 3 个 DIFF 是否按 §6.3 的建议走** | 建议已给（`workspace.json` 留旧；另两个用新） | `workspace.json` 若被覆盖，Obsidian 面板布局会重置（数据不丢，但体验变） |
| **D9** | **`Tool/代码与数据/` 里 zip 与解压目录并存，要不要清一个** | (a) 都留；(b) 只留目录 | 重复占 62044 B，无实质风险，但会让下次比对又看到「one-to-many」 |
| **D10** | **`_observer-tools/`（4 文件 / 27390 B）还留着吗** | (a) 留；(b) 删 | 与本次升级无关，但它在 vault 里，会被 Obsidian 索引 |

---

## 9. 数据出处

全部原始证据在 `D:/repo/_tools/pika-迁移/inventory/`：

| 文件 | 内容 | 本报告用在哪 |
|---|---|---|
| **`b3_fullhash.tsv`** | **3771 行逐条 hash（本报告的核心证据）** | §2 全节、附录 A |
| `b3_fullhash.json` | 同上，JSON 形态 | §2 |
| `b3_orphans.json` | 303 新版独有 + 2 旧版独有 + 0 跨侧碰撞 | §2.1、§4.3、§5.3 |
| `b3_wide_full.json` | 303 个新文件全盘撞 hash 的结果（3166 候选 / 3196 对，`truncated: 0`） | §4.3 |
| `old_candidates.json` | 4074 行，`method` = relative-path anchored，counts `matched_relpath 3771 / old_missing 281 / no_old_root 22` | §1、§2、§4 |
| `relpath_diff.json` | 按根统计的 zip/old/same_size/changed/only_zip/only_old | §4、§5.3 |
| `d_index.json` | `D:/repo` 全索引 274763 文件 | §4.3 |
| `three_way_notes.md` | 11 篇笔记 git/磁盘/zip 三方比对（磁盘==zip 11/11） | §6.4、§7.7 |
| `勘察报告.md` | 上一轮 680 行勘察 | 全部背景 |
| `zip_tree.md` / `root_map.json` | zip 结构 / 根映射 | §1.3 |
| `_scripts/` | `p1…p40` 与 `b3_fullhash.py` / `b3_orphans.py` / `b3_wide.py` | 可复跑 |

`D:/downloads/pika文件_Pro.zip` **全程只读**，mtime 仍为 `2026-10-30 23:32:07`。

---

## 附录 A：74 个「同路径但内容不同」的全表

`新尺寸 → 旧尺寸`。全部 74 个合计 1823157 B（相对 1.7 GB 总量微不足道）。
读法：vault 3 个是内容增补（§6.3 已逐个判）；skills 71 个是 **2.1.4 → 2.1.7 的版本差**，
**其中 6 个新版反而更小**（用 `←` 标出），说明新版不是旧版的超集，不能假设「旧的 ⊂ 新的」。

### A.1 vault（3）

```
  7924 ->  7697  .obsidian/workspace.json
  8118 ->  8117  math/一致几乎处处有界函数列算术平均值几乎处处收敛的问题.md
 13497 ->  8431  math/模长总和为1的n个复数中，至少能合成一个模长多大的复数.md
```

### A.2 manage-personal-knowledge（6）

```
 23700 -> 23067  SKILL.md
  8307 ->  7757  references/root-migration.md
 19143 -> 18794  references/version-coupling-manifest.json
 10208 <- 10209  scripts/migration_check.py                            ← 新版更小
  2703 ->  2534  scripts/suite_doctor.py
 15967 -> 15870  tests/test_config_discovery.py
```

### A.3 math-coach（7）

```
 22680 -> 22281  SKILL.md
  4091 ->  1765  references/terminology-registry.json
 10892 ->  3481  references/terminology.md
 89444 ->  2397  references/version-coupling-manifest.json
 20240 -> 18210  references/windows-dsh-compatibility.md
 11478 ->  9636  scripts/check_rational_identity.ps1
  1471 <-  1483  scripts/tests/test_dsh_rational_identity.ps1          ← 新版更小
```

### A.4 math-research-solve（36）

```
 26130 -> 25119  SKILL.md
 16494 ->  9407  references/archive-review-operations.md
 12283 -> 11676  references/continuity.md
 26958 -> 23138  references/core-workflow.md
 31468 -> 29054  references/data-contract.md
 35928 <- 38368  references/dsh-execution.md                          ← 新版更小
 30687 -> 19865  references/planned-export.md
  9525 ->  5743  references/project-layout.md
  3768 ->  3766  references/recovery-diagnostics.md
 43700 -> 23791  references/terminology-registry.json
 75845 -> 39984  references/terminology.md
130568 -> 83517  references/version-coupling-manifest.json
  9561 ->  9297  references/web-reading.md
 36459 -> 33634  references/workflows.md
  8580 ->  8284  scripts/dsh_guide.py
105960 -> 70837  scripts/mrs.py
 23241 -> 22632  scripts/mrs_continuity.py
 37812 -> 28767  scripts/mrs_delivery.py
  5677 ->  4995  scripts/mrs_delivery_reuse.py
128626 -> 109096 scripts/mrs_exchange.py
 57325 -> 42355  scripts/mrs_export_plan.py
 10624 ->  9884  scripts/mrs_finish.py
  8075 ->  7875  scripts/mrs_math.py
 11230 ->  1650  scripts/mrs_metrics.py
 28997 -> 27661  scripts/mrs_model.py
 10423 ->  5959  scripts/mrs_obsidian.py
 59478 -> 35311  scripts/mrs_output.py
  7392 ->  7250  scripts/mrs_prediction.py
  6582 ->  6259  scripts/mrs_preparation.py
 22843 -> 12592  scripts/mrs_project.py
  6534 ->  4466  scripts/mrs_reads.py
 19645 -> 11682  scripts/mrs_recipient.py
 78595 -> 63593  scripts/mrs_store.py
  4292 ->  2771  scripts/mrs_temp.py
 27697 -> 19189  scripts/mrs_unique.py
 26931 -> 26905  scripts/mrs_web.py
```

### A.5 math-science-computation（10）

```
 30782 -> 28117  SKILL.md
  4527 ->  3537  references/observer-data-dictionary.md
  1489 ->  1261  references/observer-phases.json
 10800 ->  1838  references/terminology-registry.json
 16381 ->  3534  references/terminology.md
 30654 -> 13505  references/version-coupling-manifest.json
 10653 ->  4240  scripts/computation_child.py
 18308 -> 10392  scripts/computation_output.py
 13334 ->  5446  scripts/run_python_capability.py
  4699 ->  4484  scripts/tests/test_probe_backends.py
```

### A.6 obsidian-vault-notes（6）

```
 29176 -> 28644  SKILL.md
  6908 ->  6525  references/retrieval-protocol.md
 20339 -> 20133  references/version-coupling-manifest.json
  4093 <-  4189  scripts/_common.py                                   ← 新版更小
 33308 -> 32946  scripts/obsidian_local_kb/obsidian_local_kb/cli.py
 67611 -> 67041  scripts/recall_notes.py
```

### A.7 pdf-problem-search（6）

```
 15766 -> 15367  SKILL.md
  1496 ->  1492  references/regression-operations.md
 10638 <- 10656  references/version-coupling-manifest.json             ← 新版更小
  8598 ->  7456  scripts/pdf_problem_search/paths.py
 24264 <- 24286  scripts/sample_problem_search_cases.py                ← 新版更小
  3537 ->  1448  scripts/test_portable_paths.py
```

---

## 附录 B：303 个新版独有（按区域聚合，不逐个列）

| 区域 | 个数 | 字节 | 分布 |
|---|---:|---:|---|
| 开源资源 | 83 | 598032325 | `分析学基础/陶哲轩分析学讲义` 18、`数论基础/陶哲轩254A解析数论` 9、`分析学基础/陶哲轩概率论讲义` 8、`分析学基础/analysis tools with applications` 3、`分析学基础/stonybrook分析教程` 3、`代数学基础/stonybrook代数教程` 3、`组合学/yufei zhao…` 2、`几何学基础/hatcher代数拓扑及部分答案` 2、其余 35 个分散 |
| 笔记共享vault | 48 | 184022617 | `math` 25、`思考随笔` 7、`编程与开发` 7、`AI工具` 5、`info` 4 |
| 嵌套容器本体 | 1 | 223808905 | `笔记共享vault.zip` |
| pika的presentations | 4 | 30917825 | 4 个 PDF（见下） |
| toolkit skills | 166 | 1932435 | `math-coach` 53、`math-research-solve` 50、包顶层 21、`math-science-computation` 19、`compute-fleet-manager` 16、`manage-personal-knowledge` 4、`obsidian-vault-notes` 2、`pdf-problem-search` 1 |
| AI工具 | 1 | 2026561 | `pika_math_learning_toolkit-2.1.7.zip` |

**presentations 的 4 个**：`陶哲轩对数学学习和工作的建议_part1.pdf` 18399806、
`【数学自学指南】如何学数学上瘾.pdf` 5551309、`陶哲轩与让布尔甘的故事.pdf` 3986113、
`Dirichlet是怎么想的_一个判别定理的思考.pdf` 2980597。

**vault 的 48 个里体积最大的几个**：`编程与开发/图片/sagemath installation gif2.gif` 32577287、
`math/图片_math/Professor_Hillel_Furstenberg.jpg` 24699044、`编程与开发/图片/sagemath installation gif 7.gif` 14033522、
`思考随笔/图片/珊瑚礁模型1.png` 6457095、`math/图片_math/DonZagier-talking.jpg` 6045201。
另有两篇**新笔记**：`math/Kolmogorov强大数定律.md` 11502、`math/含参数积分的概率表示与收敛.md` 41916。

**新版独有内部的 3 组重复（6 个文件，同一内容两个文件名）**：
1. `几何学基础/hatcher代数拓扑.pdf` ≡ `几何学基础/hatcher代数拓扑及部分答案/Hatcher algebraic topology.pdf`（8021995 B，`c4d26dd1cab1…`）
2. `组合学/yufei zhao组合学当中的概率方法/probmethod_notes.pdf` ≡ `…/probmethod_notes(1).pdf`（2243402 B，`37f5f76c2f70…`）
3. `__toolkit__/CLAUDE.md` ≡ `__toolkit__/GEMINI.md`（234 B，`93dbb7032f16…`）

---

## 附录 C：2 个旧版独有（新版没有）—— 请连同 §8 的 D2 / D4 一起看

| # | 路径 | 字节 | sha256 前缀 | 判断 |
|---|---|---:|---|---|
| 1 | `D:/repo/知识库/pika文件_Pro/AI工具/pika_math_learning_toolkit-2.1.4.zip` | 1367591 | `7ad8f0ee86ea…` | 旧版工具包本体，被 2.1.7 取代。留作回滚点还是删 → 决策 D4 |
| 2 | `D:/repo/知识库/pika文件_Pro/笔记共享vault/math/用概率计算含参数积分的极限.md` | 10001 | `4efcd8312e53…` | 唯一一个「只存在于旧版的内容文件」。见下 |

**关于第 2 个，我做了句子级比对，结论是「同话题、不同文章」而不是「同一篇的新旧版」：**

| 项 | 旧（10001 B / 146 行） | 新（41916 B / 718 行） |
|---|---|---|
| 路径 | `math/用概率计算含参数积分的极限.md` | `math/含参数积分的概率表示与收敛.md` |
| tags | `math`, `tool_idea` | `math`, `微积分`, `概率论`, `测度论` |
| 开头小节 | `### 1. 基本的思路` / `#### 1.1 转换为求随机变量的期望的极限` | `### 1. 把含参数的积分写成随机变量的期望` / `### 2. 这种表示能带来什么好处？` 及其 2.1–2.4 |
| 核心公式 | `I_n := (1/(b-a)^n) ∫_[a,b]^n f_n …` | 换成 `例a/例b/例c` 三个具体极限题；`\frac{1}{(b-a)^n}` 在新版**不出现** |
| 独有关键词 | `大数定律` | `Slutsky`、`次序统计量`、`中心极限` |

句子级（剥掉 `$…$` 数学式后按 `。`/换行切句，长度 ≥12 字）：
**新版 429 句 / 旧版 98 句 / 完全相同 0 句 / Jaccard 0.000。**

⇒ 旧版是同一话题下的**一份草稿**（带 `tool_idea` 标签，说明当时是「工具想法」阶段），
新版是围绕同一话题**重写的长文**（还多出 2.1–2.4 四个小节）。两者**不构成新旧版本关系**，
所以新版出现并不代表旧版「已被取代」。**要不要留这个草稿，只能由用户定（决策 D2）。**
