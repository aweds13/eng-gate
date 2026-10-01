# `ui_flow` 等待原语根治 · T-G188（卡 092，华为码道 pool 第四张真卡）

> 一句话：`ui_flow` 那道真机门在**满载**下会随机挂 1~2 条行为流，而且**每趟挂的不是同一条**
> （⑮ Obsidian 只读跳转 / ⑪ 备份与恢复 轮着来）—— 那是**竞态签名**，不是确定性缺陷。
> 根因：`T` 类里那几个「找元素 / 点」的原语**只查一次就断言**，抢不到时间片就报
> 「匹配到 0 个」「元素是 0×0」。本笔把它们全部换成**等就绪判据**（存在 ∧ 可见 ∧ 尺寸非零），
> 超时才报错并说清等了多久。**钉子先红后绿：改前 6/6 红、改后 10 passed。**
> ★ **但「改前会挂」的端到端对照没复现**（§四），所以这笔的收益建立在**机制**上，不是建立在对照上 —— 如实留档。
> 底座 `3540f4c`（087 那笔）。门禁以 `gates/last.json` 为准。

## 一、病：三类消息，每趟换一条

主控三趟全量门禁的实测（原样摘录）：

```
[FAIL] ⑪ 备份与恢复：…
       · 设置页有「set-backup」这一节（可展开） —— 匹配到 0 个
       · 界面上有这个动作：restore-backup —— 匹配到 0 个，可见 0 个
       · 点得到：modal-ok —— 元素是 0×0，点不到
```

跑 A 挂 ⑮、跑 C 挂 ⑪ —— **失败项身份会变**。同一天 `T-G186`（卡 091）只把浏览器层改成**内部串行**，
那是**结构性规避**；本卡治的是根。

## 二、根：五处原语 + 一处局部 press

| 位置 | 改前（只查一次） | 改后（等就绪判据） |
|---|---|---|
| `view()` | `mark()` 一次，拿不到就抛 | `waitFor(mark().ok)`，超时才抛，抛的话说清等了多久 |
| `press()` | `rectOf()` 一次，拿不到/尺寸 0 就报 | `waitFor(rectOf() 且 w>0 && h>0)`，超时才报 |
| `pressAction()` | `mark()` 一次 | 同上（并把 `readyMs` 透给 `press`） |
| `drag()` | `rectOf()` + `eval()` 一次 | `waitFor(两端都找到 ∧ 尺寸非零 ∧ 都在视口内)` |
| `openSetting()` | `mark()` 一次 | `waitFor(mark().ok)` |
| flow ⑭ 的局部 `press` | `mark()` 一次（★ 工人漏了，**主控补**） | `waitFor(mark().ok)` |

判据一律是 **存在 ∧ 可见 ∧ 尺寸非零**（`mark()` 自带 `getClientRects()` 过滤可见）；
轮询步长沿用既有 `waitFor` 的 120ms；**没有引入任何固定 `sleep`**（卡里明令禁止「等更久」顶替「等就绪」）。

**没动**：`tools/tf_browser.mjs` · `src/**` · 流数与断言项数（仍 **26 流 / 362 项**）· `scripts/run_gates.py`（091 的串行没碰）。

## 三、钉子先红后绿

`tests/test_ui_flow_check.py` 追加两条（不需要浏览器就能跑）：

1. 那五处原语 + flow ⑭ 的局部 press：正文里**必须有 `waitFor(`**、**不许出现 `sleep(`**；
2. 行为流**不许变少**（`--list` 恰好 26 条 —— 删流就是把覆盖丢掉）。

把**改前**源码（`git show HEAD:tools/ui_flow_check.mjs`）喂给同一批判据：

```
  view         waitFor=没有 → 判据 ★ 红
  press        waitFor=没有 → 判据 ★ 红
  pressAction  waitFor=没有 → 判据 ★ 红
  drag         waitFor=没有 → 判据 ★ 红
  openSetting  waitFor=没有 → 判据 ★ 红
  flow ⑭ press  waitFor=没有 → 判据 ★ 红
⇒ 改前红了 6 条（>0 即证明这批钉子真能拦住退回）
```

改后：`python -X utf8 -m pytest tests/test_ui_flow_check.py -q --no-cov` → **10 passed**。

## 四、端到端验收（★ 一半没拿到）

**负载怎么造的**：`gates/diag/flake091_under_load.py --daemon 28`（脚本由工人补 `--daemon` 分支），
起 **28 个 burn 子进程**，PID 清单落 `gates/diag/.load_pids`，跑完由工人 `taskkill` 清掉。

**改后两趟（全过）**：

```
node tools/ui_flow_check.mjs --port 8541 > gates/diag/.ui_run1.txt   # 退出码 0
行为流层通过 ✅ 26 条流 / 362 项断言（替换掉了 26 条人工确认项）  [耗时] 371.6s
node tools/ui_flow_check.mjs --port 8541 > gates/diag/.ui_run2.txt   # 退出码 0
行为流层通过 ✅ 26 条流 / 362 项断言（替换掉了 26 条人工确认项）  [耗时] 379.7s
```

**改前两趟（★ 也全过 —— 对照没复现）**：

```
git stash push tools/ui_flow_check.mjs -m "card092-baseline"
node tools/ui_flow_check.mjs --port 8541 > gates/diag/.ui_before.txt    # 退出码 0，379.9s
node tools/ui_flow_check.mjs --port 8541 > gates/diag/.ui_before2.txt   # 退出码 0，379.8s
git stash pop
```

⇒ 这台负载器（**只烧 CPU**）**复现不了那道竞态**：真机门的争用还牵涉磁盘 IO、浏览器内部资源，
以及「17 道门并行」这个只有全量门禁才有的环境。
**所以本笔的收益建立在机制上**（把「只查一次就断言」换成「等就绪判据」，正是那三类失败消息的来源），
**不是建立在「改前红、改后绿」的对照上**。这条对照**没拿到，如实留档**，不假装做到。

## 五、这一轮踩到的坑（外包侧，全是真事）

1. **工人死在「刚写完验收、还没自报」那一刻**。codearts 派活日志最后一条事件停在 `16:06:56`，
   整段没有 `result` 事件、`.meta.json` 也没落盘（跑了 66 分钟）。
   ⇒ 教训：**验收产物必须落盘**（`.ui_run*.txt` / `.ui_before*.txt` 就是这么把它 6 条证据救回来的）；
   派活器的「判决」只是提示，**不是唯一证据源**。
2. **负载器是离体进程**。它起的是 detached burn 子进程；这次工人收工时自己清了，
   但**工人被掐 / 被超时打断时，负载会留在机器上继续烧 CPU**。
   ⇒ 待办（未做）：派活器收工时按 PID 清单兜底清理。
3. **两池并行 + 满载 = 崩**。2026-10-01 16:09 起 CodeBuddy（卡 093）时，node 连崩两次
   （退出码 `3765269347` / `3221226505`），CodeBuddy **零产出**；同一时段 `bash` fork 报
   `cygheap read copy failed / Resource temporarily unavailable`。
   ⇒ 口径：**并行可以，前提是机器上没在跑真机门/负载**；外包要串行排在门禁之后。
4. **前置④「工作树必须干净」把「验收类卡」挡死**。验收卡要验的**就是**树里那堆未提交改动。
   ⇒ infra 加 `--allow-dirty`（**不是关检查**，而是把结论从「不派活」换成「放行但逐条念出来」），
   提交 `59bd4a3`（infra 仓）。
5. **封存指纹含未跟踪文件**（这条最容易踩）。`staged_tree()` 是
   `git add -A` 到临时索引（**减去 `gates/**`**）再 `git write-tree`
   ⇒ **封存之后再新增任何文件，都会让「最终提交树」≠「封存树」**。
   所以台账 / changelog / CHECKPOINT / 这类复盘文档**必须在跑门禁之前就位**。
   本笔的教训：我本想把这份复盘塞进同一笔，只能改成**后续一笔**。

## 六、数字

- 改动：`tools/ui_flow_check.mjs` **+47 / −21**；`tests/test_ui_flow_check.py` **+42**
- 流数与断言项数**不变**：**26 流 / 362 项**
- 台账：`done 315 / partial 1 / todo 0 / deferred 2`（共 **318**，**豁免 0**）—— 数字取自 `tools/sync_counts.py` 实测

## 七、证据在哪

- 工人原始输出（UTF-16）：`.wt/par2/gates/diag/.ui_run1.txt` · `.ui_run2.txt` · `.ui_before.txt` · `.ui_before2.txt`
- 派活日志：`infra/pool/logs/card-092-20261001-150023.jsonl`（744 行 / 212 事件）
- 本笔封存：`gates/last.json`（`ok` / `rev` / `sealed_at` / `tree_scope` / `not_run` / `reused`）
