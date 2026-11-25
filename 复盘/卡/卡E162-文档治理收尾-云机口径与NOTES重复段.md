# 卡 E162 · 文档治理收尾：云机口径残留 + 九份 NOTES 重复段

> 台账号 `T-AG698`｜分区 E（门禁与可信度）｜树 .wt/E162｜层 文书层｜depends E161

## 要解决的问题

卡 E160 给 `docs/subsystems/ci/云门禁机.md` 加了页首现状注、卡 E161 把 `云门禁-可复现性清单.md` 与
`测试流程.md` 的两处口气改了。剩三类**同一事实的多处投影**没收敛，读者会把它们当现状用：

### 问题 1 · `docs/subsystems/ci/测试流程.md` 还有三处把云机当在役

- `:59-62` 表一「谁能跑」说明：整段只讲「2026-10-28 起云机补装了 node v22.14.0」—— E161 的提交消息
  声称改过这里，实测**一字未动**（`git show 1fa2b452 -- docs/subsystems/ci/测试流程.md` 只有 §8 一个 hunk）。
- `:84` 表一 `ui_dom_probe` 行：「本机 / 云机（2026-10-28 起云机有 node）」。
- `:194-198` §8 边界首句「**云机 2026-10-28 前没有 node**」。

这三处的**事实内核是对的**（三道 node 门要 node，云机曾补装过），错的是口气 —— 读起来像「那台机器还在」。

### 问题 2 · `docs/subsystems/ci/GitHub-Actions-云门禁.md` 两处与代码实况不符

- `:166` 写「22 门 `exit_code=0`」：口径其实是「23 道门里 22 道 0 + `render` 记 `EXCLUDED`」，同页另有
  七处写「23 门全绿」，两读并存会被当成「这仓只有 22 道门」。
- `:328-330` §8.4 第 2 条写 `[workflow].install`「**连一个消费者都没有**」：代码实况是 build 段真的调
  `_install_workflows()`（缺 `src` 打 `MISSING_WORKFLOW_SRC` 退 2），`gate_profile.py` 也会校验 `dst` 不逃出
  快照、不与该键相冲，三条测试钉着；准确的现状是「**五份 profile 都没填**」。

### 问题 3 · 九个 `skills/*/NOTES.md` 各自重抄同一段「为什么分两页」

`skills/{pipe-card,pipe-forensics,pipe-gate,pipe-init,pipe-land,pipe-new,pipe-takeover,pipe-workbench,softeng-manage}/NOTES.md`
各有一节「★ 为什么分「SKILL.md / references/repo-bindings.md」两页」，九份共同骨架完全相同：引 2026-11-08
用户原话、引 `docs/reference/agent-skills-spec.md` §5/§6/§8/§9 第 ⑤ 条、三行「放哪/放什么」、一句「判据侧没放松」。
真源是 `skills/README.md` §2（`:90-116`）。九份副本已经埋下漂移（`pipe-init`/`pipe-new`/`pipe-takeover` 的标题
带「（2026-11-08）」后缀，其余不带；「四条钉子」的措辞各不相同）。

## 判据（逐条可执行）

1. `测试流程.md` 三处改完，且**都出现**「2026-11-25 起已不存在」这类时点话与一个回链（`云门禁机.md` 页首现状注
   或 `GitHub-Actions-云门禁.md`）；表一「谁能跑」列**只改说明文字**，23 行门名与顺序逐字不变。
2. `GitHub-Actions-云门禁.md` `:166` 改成「23 道门里 22 道 `exit_code=0`，`render` 记 `EXCLUDED`」；
   §8.4 第 2 条改成「代码已接线（含 `_install_workflows()` 的退码与三条测试），但五份 profile 都没填」。
3. 九份 `NOTES.md` 那一节各压到 ≤6 行，只留**本技能**搬走了什么 + 本技能踩的坑 + 一行回链到
   `skills/README.md` §2；九份**都不再**复述用户原话与规范条款号。
4. `skills/README.md` §2 第 5 条改成新口径（只写本技能搬走了什么、共同理由不重抄），并记一笔本卡压掉的行数。
5. 以下命令全部绿：
   - `python -X utf8 scripts/check_docs.py --mode report` ⇒ 死指针 **仍 147**（基线 147，只降不升）
   - `python -X utf8 scripts/check_layers.py` ⇒ `LAYER CHECKS: PASS`
   - `python -X utf8 scripts/check_derived_docs.py --check` ⇒ 双 OK（`docs/INDEX.md` 需重算）
   - `python -X utf8 skills/nails/check_skills.py` ⇒ 钉子② 绿（九个 SKILL.md 与 NOTES 三节）
   - `python -X utf8 tools/check_skills_claims.py --check --mode report` ⇒ 对不上 **0**（判不出不增）
   - `python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_ci_docs.py tests/test_ci_docs_counts.py tests/test_ci_portability.py tests/test_cloud_sync.py tests/test_gha_cloud_gate.py` ⇒ 全绿
6. 全部改过的文件仍是**纯 CRLF**（`count(b"\r\n") == count(b"\n")`）。

## 交付

- `docs/subsystems/ci/测试流程.md`：三处就地改（表一说明、`ui_dom_probe` 行、§8 首句）。
- `docs/subsystems/ci/GitHub-Actions-云门禁.md`：两处就地改。
- 九份 `skills/*/NOTES.md`：那一节各压到 ≤6 行。
- `skills/README.md`：§2 第 5 条 + 一行本卡记录。
- `docs/INDEX.md`：机器生成物，`scripts/gen_doc_index.py --target docs` 重跑。
- `docs/changelog.d/T-AG698.md` / `docs/traceability.d/T-AG698.toml`：落地链生成。

## 验收（落地前自跑）

```bash
cd .wt/E162
python -X utf8 scripts/check_docs.py --mode report            # 死指针 147（基线 147，+0）
python -X utf8 scripts/check_layers.py                        # LAYER CHECKS: PASS
python -X utf8 scripts/check_derived_docs.py --check          # 双 OK
python -X utf8 skills/nails/check_skills.py                   # 钉子② 绿
python -X utf8 tools/check_skills_claims.py --check --mode report   # 对不上 0
python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider \
    tests/test_ci_docs.py tests/test_ci_docs_counts.py tests/test_ci_portability.py \
    tests/test_cloud_sync.py tests/test_gha_cloud_gate.py
```

`--gate-on local` 是**故意**的：本期没有可用云机（E160/E161 写的正是这件事），`--gate-on cloud` 必退 2。

## 不许做

- 不许动 `测试流程.md` 的 `## 4. 表一：23 道门清单表` 标题、`:56-58` 耗时来源、23 行门名与顺序
  （`tests/test_ci_docs.py::doc_door_names()` / `door_table_diff()` 逐字比）。
- 不许动 `云门禁-可复现性清单.md`（E161 刚改完，本卡不碰）。
- 不许删九份 NOTES 的「这一层在防哪类错误」/「失败过什么（带读数）」/「脚本接口与以后怎么改」三节
  （`skills/nails/check_skills.py:61 NOTES_SECTIONS` 逐字判）。
- 不许把 `GitHub-Actions-云门禁.md` 的 §5 六个退出码与 `run_gate.sh` 的 2/9/4/5/7 合并 —— 两套失败面，
  同页 `:141-142` 已明写「不通用」。
- 不许在 `skills/` 里写判据（删掉整个 `skills/` 目录框架仍要可用）。
