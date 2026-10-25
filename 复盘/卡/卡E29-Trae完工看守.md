# 卡 E29 —— Trae 完工看守：把「Trae 停了」变成可发现的

> 台账号 T-AG483 ｜ 树：`.wt/E29` ｜ 分区：E（CI 子系统）
> 依据：2026-10-25 实测（E10 / E27 两次「怎么停了」都是人发现的）

## 现在疼在哪（都是实测，不是猜）

Trae 是「一轮一交还」的模型：**没有常驻进程**，一轮干完就停在那里等下一句。于是「它停了」
这件事没有任何事实来源，只能靠人眼看面板或人来问一句「怎么停了」：

1. **被手动终止**：发送键在运行中**兼作停止键**（`span[data-testid]` 由 `chat-icon-arrow-up`
   变成 `chat-icon-stop`）。2026-10-25 10:39 我误点了一下，E10 会话里出现「手动终止输出」，
   卡树随后一小时零改动 —— 当时没有任何通知，是我事后翻面板才发现的。
2. **一轮跑完交还**：E27 那次助手在面板里交了一份很像样的收工报告，但没有任何落盘事件，
   `gates/diag/wb-<卡>.done` 不会出现，看守（`tools/wb_watch.py`）只认号池工人的日志，
   **不认 Trae**。
3. **看起来在跑、其实空转**：E10 停在 10:39，面板图标却还不是「空闲」，`.wt/E10` 的文件
   mtime 一小时没动 —— 这种「假在跑」比停了更贵，因为它会一直占着一个并发位。

今晚之前，唯一能读的量是 `node tools/trae_pool.mjs status`（一次性打面板 / 任务项 / running
标记），**没有采样、没有事件、没有 mark、没有退出码语义**。

## 要做成什么样

1. **`tools/trae_pool.mjs` 加只读采样**：`sample --task "<标题子串>" [--json]`
   —— 一次输出一行 JSON：`{"ok":true,"task":…,"icon":"chat-icon-stop|chat-icon-arrow-up|unknown",
   "running":bool,"bodyLen":N,"bodyHash":"…","terminated":bool}`。
   判定逻辑抽成**纯函数** `judgeTraeSample(prev, cur, opts)`（与文件里 `judgeSubmit` / `judgeEnter`
   一族同构），`selftest` 里逐条钉住；`terminated` 认正文里的「手动终止输出」。
2. **新增 `tools/trae_watch.py`**（与 `wb_watch.py` 同一套事件面，复用它的
   `diag_dir` / `done_path` / `append_notification` 三个函数，**不另造一份**）：
   ```
   python -X utf8 tools/trae_watch.py --task "E28" --card E28 [--tree .wt/E28] \
       --interval 30 --timeout 5400 [--stale-min 10] [--write-done] [--json]
   ```
   每拍采样一次，判**四态**并落事件：
   | 态 | 判据 | 落盘 |
   |---|---|---|
   | `finished` | icon 由 `stop` → `arrow-up` | `gates/diag/wb-<卡>.done`（复用 `wb_watch` 的行格式）+ 通知流 `state:"done"` |
   | `terminated` | 正文出现「手动终止输出」 | `gates/diag/trae-<卡>.stopped` + 通知流 `state:"trae-stopped"`，**退 5** |
   | `stalled` | icon 仍 `stop`，但 `bodyHash` 不变 ≥ `--stale-min`（给了 `--tree` 时还要树 mtime 也不动） | 同上 `.stopped`，`state:"trae-stalled"`，退 5 |
   | `running` | 其余 | 只写通知流（含 `bodyLen`），不落 mark |
3. `--write-done` 不给时**只读**：一个字节都不写，只把采样打出来（跟 `wb_watch` 同口径）。
4. 技能层一行：`skills/pipe-workbench/SKILL.md` 在 `wb_watch` 那一句后面并列 `trae_watch`，说清
   「Trae 侧的收工 / 被终止 / 空转塌陷，各落哪个文件」。

## 判据（四条，都要能红）

1. `pytest tests/test_trae_watch.py -q -o addopts=` 全绿，至少 8 条钉子：
   四态各一条 + `.stopped`/`.done` **幂等**（重复写不追加第二行）+ 无 `--write-done` 时不写盘
   + 通知流行格式与 `wb_watch` 逐字同构（键名一致）+ `--json` 输出的键名固定。
2. `node tools/trae_pool.mjs selftest` 全绿，且**新增** ≥6 条 E29 用例：
   icon 两个实测值 + `unknown`、`terminated` 命中/不命中、`bodyHash` 变/不变、四态分类。
3. **反向验证做过并写进申报**：把 `--stale-min` 调 0 ⇒ `stalled` 那条钉子必须红；
   把 `.stopped` 写入去掉 ⇒ `terminated` 那条必须红。
4. 真机一次（主控跑，工人不跑）：对 `.wt/E28` 那个任务起
   `python -X utf8 tools/trae_watch.py --task "E28" --card E28 --tree .wt/E28 --interval 20 --timeout 600 --write-done`
   —— 必须真的落一条事件（`done` / `trae-stopped` / `trae-stalled` 之一），原始输出进申报。

## 不许做

- 不许把 Trae 接进 `wb_dispatch.py`（卡 218 已裁定不接）；这张卡只加**看守**，不动派活。
- 不许在脚本里点发送键（运行中它是停止键）；采样路径**只读 DOM**。
- 不许另起一套通知文件：必须复用 `gates/diag/notifications.jsonl` 与 `wb-<卡>.done`。
- 不许把 Trae 的失败当号池工人的失败：`.done` 只在真收工时写。

## 证据（申报要带）

- `pytest tests/test_trae_watch.py -q -o addopts=` 原始输出。
- `node tools/trae_pool.mjs selftest` 原始输出（含新增 6 条）。
- 两条反向验证的红色原始输出。
- 真机那一次的 `gates/diag/trae-watch.jsonl` 尾部与 `.stopped`/`.done` 内容。
