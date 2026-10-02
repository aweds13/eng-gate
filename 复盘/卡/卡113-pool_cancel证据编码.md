# 卡 113 —— `pool_cancel` 的**证据别是乱码**（taskkill 输出按系统区域编码解）（T-G210）

**树**：`.wt/tkill`（★ 开局就在这棵树里；`git rev-parse --short HEAD` 必须是主控给你的 base）
**base**：以派活时主控给的为准
**号池**：CodeBuddy ｜ **模型**：`deepseek-v4.1-flash` ｜ **提交**：★ **你不要 commit**（主控复核后提交）

---

## 来路（主控的真机演练，零花费）

卡 111（T-G208）落地后，主控补做了它**没做的那半 —— 真机 cancel 演练**（靶子是主控自己起的 `python -c sleep`，
所以不花一分钱额度）：
**功能全对** —— 真起了靶子、登记租约、补 pid → `pool_cancel` 核对映像名（`python.exe`）→ 真杀 → 写 `.cancel.txt`
→ 放租约；**反例**（靶子映像名是 `PING.EXE`）也**拒绝动手**、靶子还活着、租约没动。

**但写出来的"证据"是乱码**：

```
结果：taskkill /F /T /PID 19788 | �ɹ�: ����ֹ PID 19788 (���� PID 22396 �ӽ���)�Ľ��̡�
```

根因：`tools/pool_mcp.py::_kill` 把 `taskkill` 的输出按 **UTF-8** 解，而它吐的是**系统区域编码**（这台 cp936）——
**T-G96 已经踩过、`tools/wb_dispatch.py::kill_tree` 已经修过**的同一条坑（新代码重犯）。
★ 教训一句话：**证据文件本身读不出来，等于没留证据。**

## 你要做的（★ 只动"解码"这一处，别顺手重构）

1. `tools/pool_mcp.py`：
   - 加一个模块级小函数（名字你定，例如 `_console_encoding()`）：返回 `locale.getencoding()`；
     **没有那个属性时**退回 `locale.getpreferredencoding(False)`；再退回 `"utf-8"`。
   - `_image_name()` 与 `_kill()` 里那两处 `subprocess.run(..., encoding="utf-8", errors="replace")`
     改成用它，`errors="replace"` **保持不变**。
   - 注释里点明两件事：**为什么不能用 `getpreferredencoding(False)`**（本仓一律 `python -X utf8` ⇒
     它会回 `utf-8`，等于没修 —— 这是 T-G96 的原话）与**出处**（`tools/wb_dispatch.py::kill_tree`）。
2. 钉子（加到 `tests/test_pool_mcp_write.py` 里），**两条**：
   - ① **结构性**：桩住 `pool_mcp.subprocess.run`，断言 `_kill` 与 `_image_name` 传下去的
     `encoding` **等于 `locale.getencoding()`**（★ **动态比较**，换台机器也成立）、`errors` 仍是 `"replace"`。
   - ② **行为性**：桩返回一段**非 ASCII 的系统编码文本**（例如 `stdout="成功: 已终止 PID 1"`）⇒
     `_kill` 的回话里**不许出现**替换字符 `\ufffd`；再桩一段**坏字节** ⇒ 只能是 `replace` 掉、**不许抛**。
3. **复跑主控那次演练**：`python -X utf8 gates/diag/_drill_cancel.py`
   （那是主控 scratch、可读；★ **不许改它一个字**）—— 把输出贴进回报，重点看 `.cancel.txt` 里那句是不是**人话**。

## 禁区

- 只许改 **`tools/pool_mcp.py`** + **`tests/test_pool_mcp_write.py`**；
  **不许**碰 `tools/pool/**`、`tools/wb_dispatch.py`、`tools/wb_brief.py`、`gates/diag/**`、
  `scripts/**`、`src/**`、`docs/**`、`复盘/**`
- **不要** commit / push / 打 tag；不动 `.git` 里任何东西
- 不许装依赖 / 联网；★ **不许**自己去杀任何别的进程（演练脚本杀的是它自己起的靶子）

## 回报（≤9 行）

```
1) 改了哪几行（改前 / 改后）
2) 两条钉子的原样输出（结构性 + 行为性）
3) ★ _drill_cancel.py 复跑的原样输出（重点：.cancel.txt 里那句是人话；反例仍拒绝动手）
4) pytest + ruff 原样结论（既有 tests/test_pool_mcp_write.py 与 tests/test_pool_mcp.py 都要过）
5) ★ 没做到 / 不确定的：<如实写，没有就写"无">
6) ★ 你判断"该改但不属于本卡"的地方
```
