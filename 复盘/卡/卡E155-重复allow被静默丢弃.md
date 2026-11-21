# 卡 E155 · `--allow` 重复给被 argparse 静默丢弃：落地链白名单只剩最后一条

> 台账号 `T-AG690`｜分区 E（门禁与可信度）｜树 .wt/E155｜层 代码层（一段小修）+ 钉子｜
> depends E154（本卡由它那趟的现场暴露）

## 要解决的问题

### 问题 1 · 重复给 `--allow` 时只有**最后一条**生效，前面的被静默丢掉

卡 E154（`T-AG689`）第一趟落地（`gates/diag/land-E154.log`，2026-11-22 02:28）的结果是：
提交 `c05b9b51` 里**只有派生物**（10 件 docs/gates/交接），本卡唯一的内容改动
`复盘/收口后待用户清单.md` **一个字都没进**，而那笔提交的消息正文第一条就在讲这个文件改了什么。

探针（`gates/diag/_probe154.py` 包 `pool.landing.run`，日志 `gates/diag/land-E154b.log`）
抓到的实参原文：

```
[probe] git add rc=0 :: git add -- docs/subsystems/pool/README.md docs/changelog.d/T-AG689.md ...
```

9 条 `--allow` 传进去，`git add` 只收到 **1 条**。根因是 argparse 的默认 action：

```
python -c "...ap.add_argument('--allow', nargs='*'); ap.parse_args(['--allow','a','--allow','b','--allow','c'])"
  => ['c']        # 前两条被覆盖，不报错、不警告
```

两处定义都中招：
- `tools/wb_land.py:317` `ap.add_argument("--allow", nargs="*", default=None, ...)`
- `tools/pool/landing.py:2669` `ap.add_argument("--allow", nargs="+", required=True)`

同族的 `--evidence`（`tools/pool/landing.py:2668` `nargs="+"`）与 `--affected`
（`:2682`）是**同一个病**：实测 `--evidence e1 --evidence e3` ⇒ `['e3']`。

### 问题 2 · 为什么一直没人发现：所有既有钉子都用「一条 + 空格分隔」

`tests/test_wb_land.py:597` 的 `_wand()` 拼的是 `"--allow", *allow` —— 一条开关带多个值；
`tests/test_wb_land.py` 与 `tests/test_pool_landing.py` 里没有任何一条用重复开关的写法。
于是「重复给 = 只有最后一条」这条静默行为**一次都没被咬过**。

### 问题 3 · 失败方式是最坏的那种：门禁绿、审计过、提交成功

`c05b9b51` 那趟：门禁全绿、审计「926 条提交全部合格」、封存一致、⑧ 复核 problems=0 ——
**每一道闸都说好**，因为丢掉的正好是「卡域」本身：`extra=[]`（暂存全是 allow 内的派生物），
`staged` 非空 ⇒ 判据「计划外或空暂存区 ⇒ 停手」不触发。它只在最后 rebase 时以
`error: cannot rebase: You have unstaged changes.` 这种**完全指错方向**的方式失败一次。

## 判据（逐条可执行）

### 判据 1 · 重复给 `--allow` 全部生效（两条入口都要咬）

`tools/wb_land.py` 的 `--allow` 与 `tools/pool/landing.py` 的 `--allow` 都改成
`action="extend"`（`nargs` 保留原值）。判据是行为不是写法：给
`--allow a --allow b c` ⇒ 收到 `['a','b','c']`。

### 判据 2 · 同族的重复开关一起修

`--evidence`（`tools/pool/landing.py:2668`）与 `--affected`（`:2682`）同样是
`action="extend"`。不进这两条的键（`nargs="?"` / 布尔开关）不动。

### 判据 3 · 钉子：重复给 `--allow` 时，卡域外的东西仍被判「计划外」

新增一条端到端钉子（`tests/test_wb_land.py`）：假仓里造两个改动文件，只有第一个在白名单里，
命令行写成 `--allow <第一个> --allow <第二个的目录>` 之外再加 `--allow <一个不存在的路径>` ——
断言 ① 两个文件**都**进了暂存（证明前面的开关没被丢）；② 若只保留最后一条会出现的症状
（第一个文件留在工作区未暂存）**不出现**。

反向验证（必须做，写进卡的复盘）：把 `action="extend"` 改回默认，这条钉子必须红。

### 判据 4 · 落地链的「丢卡域」不再静默

`staged_and_extra()` 之后加一条：若 `allow` 里**每一项都在暂存区之外**且暂存区非空 ⇒
打印点名（哪些 allow 路径既没改动也没进暂存），而不是当「一切都好」。这条只打印、不改退出码
（`extra` 那条判据已经管「计划外」，本条管「卡域整个没生效」）。

### 判据 5 · 三道文档门不涨

死指针仍 147（基线 147，+0）；`check_layers.py` PASS；`check_derived_docs.py --check` 双 OK。

## 交付

1. `tools/wb_land.py` —— `--allow` 改 `action="extend"`。
2. `tools/pool/landing.py` —— `--allow` / `--evidence` / `--affected` 三处改 `action="extend"`；
   `staged_and_extra()` 调用点之后加「卡域没生效」点名（判据 4）。
3. `tests/test_wb_land.py` —— 判据 3 的端到端钉子（含反向验证说明写在 docstring 里）。
4. `tests/test_pool_landing.py` —— 判据 1/2 的 parser 级钉子（三条开关各一条）。

## 验收（落地前自跑）

    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_wb_land.py tests/test_pool_landing.py
    python -X utf8 -m pytest -q -o addopts= -p no:cacheprovider tests/test_landing_counts_refresh.py tests/test_landing_derived_resolvable.py
    python -X utf8 scripts/check_docs.py --mode report
    python -X utf8 scripts/check_layers.py
    python -X utf8 scripts/check_derived_docs.py --check

## 不许做

- 不许靠「以后记得只给一条 `--allow`」这种口头约定收口 —— 那是把静默失败留给人记性。
- 不许把重复开关改成「重复就报错退出」：现有脚本 `gates/diag/_land154.sh` 那种写法是历史惯例，
  一刀切报错会让所有老命令当场失效；要的是**都收下**。
- 不许改 `gates/diag/` 下的历史日志与探针脚本（`_probe154.py` / `_land154*.sh` 是一次性现场件，
  已在 .gitignore 里；本卡只在文档里引用它们，不进提交面）。
- 不许顺手重跑 E154 的历史落地或改写 `fadb0e12`。
- 不许在反引号里写不存在的路径（`check_docs.py` 会判死指针，基线只许降）。
