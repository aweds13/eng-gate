# 0010 门禁基点漂移不算伪造：复核器按「差在哪」分两档

Status: Accepted
Date: 2026-11-18
Supersedes:
Superseded-by:
来源: 台账 E137 / T-AG648（`docs/workbacklog.toml` 的 E137 条目）、E123 复核（`复盘/卡/卡E123-门禁跑完主树又前进时复核器怎么判.md`）；`tools/wb_review.py`、`scripts/audit_progress.py`、`tools/pool/landing.py`、`framework/src/framework/review.py`

## 背景与问题

落地链是「跑门禁 → 封存树 → 提交」，两步之间主树可能又被别的卡推了一笔（⑦ rebase / 别人合流），
于是 `gates/last.json` 的 `rev` 不再等于本笔父提交。复核器原来的判据是**字面不等即红**，
而且文案写的是「伪造门禁结论」「一次门禁跑完提交两笔？第二笔没验过」—— 现场根本没有这两件事：
门禁真跑过、没人伪造、也不是一笔提交两回。判红的代价是把可解释的基点前移与真篡改混成一档，
复核记录里因此留下了一段**不成立**的指控。

更硬的第二个病：`audit_verdict()` 不带 `--rev`，跑的是工作区 HEAD 的审计；被复核的那一笔
读到的不是它自己的产物，「产物时间早于父提交」这类读数会被当成这一笔的问题。
第三个病：`audit_verdict_from_output()` 在退出码非 0 时还会再叠一条「有豁免项」，
结论还靠 `re.search("审计通过", body)` 从输出里找字面 —— audit 回显的 `Gates:` trailer 里
恰好有这四个字，失败会被判成通过。

## 候选方案

A 保持字面不等即红，只把文案改成客观说法。改动最小，可解释的基点前移仍然照红，
复核侧于是长期存在「已知假红」——假红多了，真红就没人信了。

B 加一个纯分类器 `gate_basis_verdict(payload_rev, parent_short, recorded_tree, commit_sha, files)`，
返回 `(档位, 差异路径, 读数)`，档位只有 BASIS_DRIFT / TRUE_MISMATCH 两档；三处调用点
（`check_gate_evidence` / `check_seal_tree` / `check_gates_trailer_truth`）都改走它。
BASIS_DRIFT 只放行「真祖先 + 残差为空 + 树在对象库 + 差异不落被测代码档」**四条同时成立**的情况，
并且**不许静默绿**：打印一行「★ 基点漂移（未复验）」，`--json` 多一个 `waived_basis` 字段，
落地链 ⑧ 步把它念出来。

C 直接把门禁 `rev` 判据删掉（差异交给封存树那条判据）。判据少一条，门禁是不是为这一笔跑的
就没人问了 —— 否决。

## 决定

选 B。四条必要条件是**与**关系，缺一条即 TRUE_MISMATCH 照红并点名路径：
① `git merge-base --is-ancestor <gates_rev> <parent>` rc=0；② 树差异 − （`gates_rev..parent` 的改动
∪ 本笔 `files`）为空；③ `git cat-file -t <tree>` 回 `tree`；④ 差异路径的必需档位
（`gates.defs.domains.required_profiles`）不落 lang / product。**差异落 lang 或 product 一律照红**——
被测代码被中间提交带走过，门禁对它的结论就不成立，这条没有例外。

判据只留一份真源（`tools/wb_review.py::gate_basis_verdict`）。`framework/src/framework/review.py`
是纯库（模块头写着不 import 本仓模块），这一版没接，留 `TODO(E137)` 与一条 xfail strict 的
失败钉子 `tests/test_wb_review.py::test_framework_review_has_the_same_basis_ruler`。
旧口径产物（`tree_scope` 非期望值、树对象不在对象库）仍然**只标注、不判红**，一个字节没动。

`audit` 那侧同时改成判对对象：`audit_verdict(sha)` 传 `--rev`，`scripts/audit_progress.py` 在给了
`--rev` 且不是 HEAD 时取 `git show <rev>:gates/last.json`（默认行为不变）；结论只由退出码决定。

## 把握程度

medium —— 分类器有九条真 git 仓库的钉子（含一条真 BASIS_DRIFT 正例锚点 `db702d6d` 与
九笔历史提交的复算读数），但 framework 侧还没同源，`TODO(E137)` 是一处已知欠账。
