# 卡 F13 —— dsh-web 逐包对照那份文档该挂「已废弃」的牌子

> 台账号 `T-AG585` ｜ 分区 F（文档治理）｜ 树 `.wt/F13` ｜ 层 文档层
> 依据：用户 2026-11-02 18:17 判「dsh-web 文档是废弃的了」（m77111），要求把该开的卡扔出来。
> 现读事实：`复盘/DSH插件-dsh-web逐包对照.md`（27098 B / 246 行 / 纯 CRLF）里
> `:99`「远程/移动面：**没有**」、`:101`「我们没有远程访问面」、`:102`「636 行配对状态机服务的是
> 一个我们没有的远程通道」、`:167`「无远程面」四条**全部不成立**，且是从写下那天就不成立。
> 而它现在既没有 frontmatter、也没有任何一处自声明过时 ⇒ 机器判不了，读者也判不了。

## 要解决的问题

1. **四条「没有远程面」被源码证伪，且写在源码之后**。`src/timeflow/core/lan.py`
   （17936 B）`:43 HEADER = "X-Timeflow-Pair"`、`:161 def verify(...)`、`:196 def gate(...)`、
   `:228 def check_pair(...)`、`:243 def status(...)`；接在 `src/timeflow/api/app.py:303
   async def lan_gate(request, call_next)` 与 `tools/serve.py:209 --lan`（绑 `0.0.0.0` + 装配对门），
   测试 `tests/test_lan_pairing_line.py` 24 条。`git log --diff-filter=A` 实测：
   `lan.py` 首现 **`15000b30` 2026-09-23 07:07**，本文件首现 **`f9fd1b7b` 2026-10-17 11:20**
   ⇒ 写这份文档时那套配对门**已经存在 24 天**。今天又多了 `b349ac6a`（卡 A365）的
   MCP Streamable HTTP 传输（`tools/pool/mcp_http.py`）⇒ 这句话三个时间点全错。
2. **「636 行配对状态机」没有出处**。上游 `D:/repo/_refs/dsh/dsh-web-dev/` 里
   `packages/dsh-remote-web-ui/src/pairing.ts` 按 `read_bytes().decode().split("\n")` 计是
   **766 行**；加 `pair-grant.ts`(131) + `pairing-access.ts`(36) 是 **933**；整包 `.ts` 里
   **没有任何一个 636 行的文件**（最接近 `tunnel.ts` 625）。错数被当成「所以不借」的理由。
3. **16 条本仓 `路径:行号` 引用全部指错段**（唯一对的是 `src/timeflow/core/focus/timer.py:180`）。
   逐条真身：`tools/pool/task.py:622`→真身 `:633 def cmd_claim(...)`；`:313`→`:324 def read_json(...)`；
   `:180`→空行（真身 `:189 def write_json_atomic(...)`）；`tools/pool/landing.py:960`→真身
   `:1960 def fast_preflight(...)`；`:1406`→真身 `:177`（`--diff-filter=U`）；`:138`→真身
   `:168 def resolve_derived_conflicts(...)`；`:1324`→真身是**嵌套**函数 `_sealed_tree()` `:2574`
   （模块级 `sealed_tree` 不存在）；`tools/wb_dispatch.py:795`/`:2490`、`tools/wb_plan.py:103`、
   `tools/wt_prune.py:8`/`:41`、`scripts/run_gates.py:1273`（`gates_ok` 真身 `:1828`）、
   `tools/dsh_skills_link.py:1` 同理。**根因**：`scripts/check_docs.py:346 normalize()` 剥掉
   `:\d+` 后只要文件在就算过，**从不校验行号** ⇒ 这类漂移没有任何门在看。
4. **机器判不了它作废**。`scripts/check_docs.py:847 check_superseded()` 只认三种自声明句式
   （`SUPERSEDED_PATTERNS` `:177` 两条 + `SUPERSEDED_HEADING` `:181`），且 frontmatter 里
   `status: superseded` **且** `supersedes:` 非空就跳过（`:869-873 labeled ⇒ continue`）。
   本文档两种情况都不满足 ⇒ 全仓 `superseded` 欠账**永远只有** `复盘/已废弃-学校通知聚合.md`
   那 1 条，这份错了四条硬结论的文档与它们并列，读者分不出谁该信。
5. **`复盘/` 与 `docs/` 下 frontmatter-first 的文件现在是 0 篇**（全仓 9 篇 frontmatter 全在
   `skills/*/SKILL.md`）⇒ 本卡是**首例**，必须同时把「解析器真的吃得下」钉住，否则下一张卡
   写个半截 frontmatter 就又变成机器读不到的废字。

## 判据（6 条）

1. **首行就是 frontmatter，且两个字段机器读得出**。`复盘/DSH插件-dsh-web逐包对照.md` 第一行
   必须逐字 `---`，块内必须有 `status: superseded` 与非空 `supersedes:`；用
   `scripts/check_docs.py::split_frontmatter` 读回 `meta["status"] == "superseded"` 且
   `meta["supersedes"].strip()` 非空。`supersedes` 必须点名现在该信什么（至少含
   `src/timeflow/core/lan.py` 与本仓 `docs/subsystems/pool/README.md` 两条之一以上），
   不许写成「同上」「见正文」这类指代。
2. **标题行一字不动**。原第一行 `# DSH 插件 · dsh-web 逐包对照（卡 265 · T-G384 · 树 \`.wt/265\`）`
   必须原样保留（只是被 frontmatter 往下推）。理由：全仓 17 处按文件名/标题引用它，
   标题改写会让 `grep` 面漂。**不许**把它改成 `# 已废弃：…` 那种标题式声明。
3. **正文加作废横幅，三条理由各带可复现锚点**。紧接 frontmatter 之后、原标题之前插入一段
   横幅（≤20 行），必须同时满足：
   - 含自声明句式（能被 `superseded_declarations()` 认出，「本」+「文件/文档」+`已废弃` 同句），
     使 frontmatter 一旦被后来者误删，`check_superseded` 立刻报红；
   - 三条理由分别点到：`15000b30`（`lan.py` 早 24 天）/ `f9fd1b7b`（本文档首现）/
     上游 `pairing.ts` 766 行 ≠ 636 / 16 条行号全错（点名 3 条代表 + 指向
     `scripts/check_docs.py:346 normalize()` 不校验行号）；
   - 明写「结论仍成立的部分」：`skills/softeng-manage/references/safety.md` 的 HS1（`~/.dsh`
     禁区）与 AI4（外部模型用完就撤）出自 `复盘/INDEX.md` §5.2，**不随本文件作废**。
4. **不许靠删错话「修好」它**。`git diff` 对该文件**只许有 `+` 行，零 `-` 行**（除 frontmatter
   与横幅的插入外，原有 246 行内容逐行不变）⇒ 四条被证伪的原句仍在，可查、可对照。
5. **新增 tests/test_deprecated_docs_labeled.py（≥4 条钉子，现读真源；本行不加反引号**
   —— 该文件落地前不存在，写成指针会顶破 docs 门的死指针基线（踩过 7 次））：
   - ① 真仓该文档：`split_frontmatter` 读出 `status=superseded` + 非空 `supersedes`，
     且第一行逐字 `---`；
   - ② **反向**：在内存里把 frontmatter 整块抹掉（只留横幅）⇒ 对同一份文本跑
     `superseded_declarations()` + `check_superseded()` 的等价判据，必须报 **1 条**且文案含
     该文件名（证明「frontmatter 是这道防线的唯一开关」）；
   - ③ 全仓不变式：`docs/` 与 `复盘/` 下凡第一行是 `---` 的文件，`status` 为 `superseded`
     时必须带非空 `supersedes`；**反向**：在 `tmp_path` 造一个只有 `status: superseded`
     没有 `supersedes` 的合成文档 ⇒ 钉子必须红；
   - ④ 该文档正文仍含四条原句的代表串（`远程/移动面：**没有**`、`我们没有远程访问面`、
     `636 行配对状态机`、`无远程面`）⇒ 钉住「留档」这件事本身。
   钉子必须现读真源（真仓文件 + `check_docs` 的函数），不许把行号写死进测试。
6. **行尾与派生文档一致**。改完 `复盘/DSH插件-dsh-web逐包对照.md` 仍是**纯 CRLF**、
   `bare == 0`；`docs/traceability.d/T-G384.toml` 改动后跑 `tools/sync_docs.py`，
   再 `tools/sync_docs.py --check` 必须 `[OK ]`。`skills/softeng-manage/references/safety.md`
   与 `docs/traceability.d/T-G384.toml` 的 `status`/`group`/`title`/`id` **一字不许改**。

## 交付

- 改 `复盘/DSH插件-dsh-web逐包对照.md`：首行 frontmatter（`status` + `supersedes`）+ 作废横幅。
- 改 `docs/traceability.d/T-G384.toml`：`evidence` 与 `gaps` 各补一句「该文档 2026-11-02 起
  标作废（卡 F13 / T-AG585），四条『没有远程面』已被 `src/timeflow/core/lan.py` 证伪；
  行号引用不可信」—— 只加不改，`status` 保持 `done`（那笔交付确实完成过）。
- 新增 tests/test_deprecated_docs_labeled.py（同上，不加反引号）。
- 卡规格本身（`复盘/卡/卡F13-dsh-web对照作废.md`）。

## 验收

```bash
cd .wt/F13
python -X utf8 -m pytest tests/test_deprecated_docs_labeled.py -q -o addopts= --no-cov
ruff check tests/test_deprecated_docs_labeled.py
python -X utf8 -c "import sys;sys.path.insert(0,'scripts');import check_docs as c,pathlib;p=pathlib.Path('复盘/DSH插件-dsh-web逐包对照.md');m,b,o=c.split_frontmatter(p.read_text(encoding='utf-8'));print(o,m.get('status'),repr(m.get('supersedes')))"
python -X utf8 scripts/check_docs.py --mode report
python -X utf8 tools/sync_docs.py --check
git diff --numstat -- 复盘/DSH插件-dsh-web逐包对照.md
python -X utf8 -c "import pathlib;b=pathlib.Path('复盘/DSH插件-dsh-web逐包对照.md').read_bytes();print(len(b),b.count(b'\r\n'),b.count(b'\n')-b.count(b'\r\n'))"
```

期望：pytest 全绿；ruff `All checks passed!`；`split_frontmatter` 打出 `superseded` 与非空串；
`check_docs --mode report` 仍是 `superseded 1（基线 1，+0）`、`死指针 148（基线 148，+0）`、退 0；
`sync_docs --check` 打 `[OK ]`；`git diff --numstat` 第二列（删除行数）是 **0**；
行尾读数 `crlf == 总行数`、`bare == 0`。

## 不许做

- 不许删、不许重写那 246 行里的任何一行（判据 4；只许插入）。
- 不许把标题改成 `# 已废弃：…`（判据 2）。
- 不许动 `skills/softeng-manage/references/safety.md`（HS1 / AI4 结论仍成立）。
- 不许改 `docs/traceability.d/T-G384.toml` 的 `id`/`title`/`group`/`status`。
- 不许改 `scripts/check_docs.py`、`scripts/gen_doc_index.py`、`docs/doc-debt-baseline.toml`
  （本卡只治这一篇 + 立钉子；把行号校验接进门是另一张卡）。
- 不许为了让门变绿去调基线或 `PINNED_FLOOR`。
- 不许批量给其它 715 条行号引用「顺手修一遍」—— 那是另一张卡的范围。
- 不写「未来会做」「即将」这类话。
- 不加 `# noqa`。
