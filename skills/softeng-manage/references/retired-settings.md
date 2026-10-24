# 旧设置退役表：哪条还活着、哪条已经死了、哪条改了名

> 主控的原话：「以前用的是旧设置，现在这套会不会冲突？」
> 这一页只回答一件事 —— **你读到的那句话，今天还算不算数**。
> 口径错了比不会用更贵：按旧口径干，门禁会在第 12 分钟才红。

| 旧口径（技能里曾这么写） | 今天的正确写法 | 状态 | 改成它的卡 | 证据命令 |
|---|---|---|---|---|
| 「提交前一律跑全量 19 道门」 | `wb_land` 自己传 `--profiles auto`，按**改动面**算必需档；碰 `scripts/**` `tools/**` `gates/**` 仍强制全量 | **已改判** | A327（`T-G247`） | `python -X utf8 tools/wb_review.py --check-gates`（必需 ⊆ 实跑） |
| 「先封存再提交」与「先提交再封存」两头说法都有 | 门禁读数只认「**每笔都是封存笔**」（`last.json.rev == 父提交`）；落地链在卡树里 staging，不在主树手工折腾 | **已改判** | A324（`T-AG437`） | `python -X utf8 tools/wb_verify.py --rev HEAD` |
| `--no-preflight` = 跳过预检 | 内层改名 `--skip-preflight`（跳 ③″ 快门禁预检）；`--preflight` 是**壳层只读体检**（11 条判据、零副作用）。旧写法仍收，会提示已改名 | **已改名** | G3（`T-AG458`，卡 E1 立的新义） | `python -X utf8 tools/wb_land.py --preflight --task <台账号> --allow <文件>`（0 / 1） |
| 「在 `.wt/<卡>` 里跑 `tools/*` 读到的是同一份台账」 | 台账 / 门禁产物跟**数据根**走（`PIPE_DATA` > cwd 像数据根 > `PIPE_HOME` / 工具根上一级）；门表跟**工具根**走 | **已改判** | A326（`T-AG441`） | `python -X utf8 tools/pipe_root.py --check`（0 / 2） |
| 「卡上的活留在工作区，卡树里先提交也行」 | 卡树 HEAD **必须**是主树 HEAD 的祖先；已经在卡树提交过的走 `git -C <树> checkout <主树 HEAD>` → `cherry-pick -n <那笔>` → `reset` | **半冲突**（工具会停手并给这三步） | E6（`T-AG448`） | 落地链退出码 3 + 原话 |
| 「台账证据只靠 `test:xxx.py::用例` 就够」 | `test:` 已剥 `::用例名`（`assertion_path`），但**同时写** `file:tests/xxx.py` 最稳；只写 `test:` 的测试文件在反向判据里曾永不算数 | **已改判** | E21（`T-AG474`） | `python -X utf8 scripts/audit_progress.py --rev <提交>`（0 / 1） |
| 「落地时人手把要声称的文件再塞一遍 `--evidence`」 | 不必再塞：`stage_card` 片段模式改成**合并**（已有条目保留、本次追加、去重） | **已改判** | E25（`T-AG479`） | `python -m pytest tests/test_stage_card_evidence_merge.py -q -o addopts=`（2 passed） |
| 「卡树里的 `gates/last.json` 挡路就删掉」 | **不许删**：`test_false_success_pins` 要读上一趟封存读数，删了直接 `FileNotFoundError`；挡路的是「封存时未跟踪」，把片段 `git add` 进去即可 | **半冲突**（删了会红） | F1（`T-AG449`）实证 | `python -m pytest tests/test_false_success_pins.py -q -o addopts=` |
| 「期望门名恒为 19 道」 | 按 `last.json.profiles_run` 派生期望集合；旧笔没有该字段才退回全量 | **已改判** | E24（`T-AG477`） | `python -m pytest tests/test_wb_verify_profiles.py -q -o addopts=`（5 passed） |

## 怎么用这一页

1. 你读到的口径**不在表里** ⇒ 按它干；表里的才算「已知变过」。
2. 表里 `已改名` ⇒ 旧写法多半仍能跑（会提示），但**别写进新文档**。
3. 表里 `半冲突` ⇒ 两条都能跑、结果不同；按「今天的正确写法」那一列。
4. 想加一行：这条口径得能指到**改成它的那张卡**与一条**能重跑的命令**，否则说明它还没定案。
