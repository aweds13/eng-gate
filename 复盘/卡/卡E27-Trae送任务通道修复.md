# 卡 E27 —— Trae 送任务通道修复：选择器、提交键、并发上限

> 台账号 T-AG481 ｜ 树：`.wt/E27` ｜ 分区：E（CI 子系统）
> 依据：2026-10-25 实测（Trae CN 新版 solo-lite 面板）

## 现在疼在哪（都是实测，不是猜）

`tools/trae_pool.mjs` 送任务**静默失效**：`send` 退回 `[trae] 找不到输入框（面板没渲染出来？）`，
**退出码 0** ⇒ 调用方以为发出去了，实际什么都没发生。三次实测撞到三处：

1. **选择器全过时**：面板已改成 `div.chat-input-v2-input-box-editable`（输入框）、
   `button.chat-input-v2-send-button`（发送键）、`div.taskItem` + `span.taskText`（任务项）、
   `span.task-list-new-task-text`（新建任务）。旧选择器一个都不匹配。
2. **提交键点不动**：发送键空输入时带 `disabled` 属性，`button.click()` 与
   `pointerdown/mousedown/pointerup/mouseup/click` 整套序列**全部无效**；
   只有输入框 `focus()` 后派发 `keydown/keypress/keyup`（`key:'Enter'`）才会真发出。
3. **并发上限静默**：面板右上弹「您已达到 10 个云端并行任务上限」，
   但送任务脚本不认这个信号 ⇒ 又回到「以为发了」。

## 要做成什么样

- 选择器集中在文件头一个 `SELECTORS` 常量，按上面四个实测值；
- 提交走 `submit(ws)`：`focus()` → `execCommand('insertText')` → Enter 键序；
  若发送键仍是 `disabled` ⇒ 直接报错退非零（不许静默成功）；
- 送任务前先探并发上限：面板文本含「并行任务上限」⇒ 报 `[trae] 并发已满（10）` 退 3；
- 切任务读正文：`switchTask(title)` 点 `div.taskItem` 后**轮询等待**正文变化（最多 10 s），
  等不到就报「切过去了但读不到正文」，不返回旧任务内容；
- `list` 输出带 `running` 标记（任务项内含 spinner 类名）。

## 判据（四条）

1. `node tools/trae_pool.mjs --help` 列出 `list/send/switch/status` 四个子命令，退 0。
2. `SELECTORS` 常量里四个选择器与实测值**逐字相符**（`tests/test_trae_pool_selectors.py` 断言）。
3. 找不到输入框 / 发送键仍 disabled / 并发已满 —— 三种情况都**退非零**且有明确一行原因。
4. 静态检查：文件里不再出现旧的 `button.click()` 提交路径（用 Enter 键序替代）。

## 不许做

- 不许把 Trae 通道接进 `wb_dispatch.py`（卡 218 已裁定不接）。
- 不许在脚本里自动关别人的任务/窗口。
- 不许改主仓 `AGENTS.md` 之外的技能文档（口径由 G 区管）。

## 验收

```
node tools/trae_pool.mjs --help                              # 退 0，四个子命令
python -X utf8 -m pytest tests/test_trae_pool_selectors.py -q -o addopts=   # 全绿
node tools/trae_pool.mjs send --prompt '' --port 9333        # 退非零 + 一行原因
```
