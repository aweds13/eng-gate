# 卡 133 —— `Gates:` trailer 的**真伪判据**（治 GLM **三.2**）（T-G230）

**树**：`.wt/gatestruth` ｜ **base**：主控派活时的主树 HEAD ｜ **提交**：★ **不要 commit** ｜ **模型**：默认
**成员号**：任务 `B-FIX4` 的 **M-2**（干完要交成送申请，见最后）

## 来路（外部审查 GLM-5.3 的 **三.2** 与 **2.4**，原文要点）

- **2.4**：「集成器把 `Gates: 全量门禁绿 + seal` **写死**进提交信息，而同脚本有 `--no-gate` 与
  `--commit-only` 两个模式 ⇒ `--no-gate` 路径产出的提交**自带一条假的门禁结论**（工具自己伪造）。」
  ★ **生成端**已经由主控在 scratch 里改了（按实际模式写），但——
- **三.2**：「**`Gates:` trailer 真伪无机器判据**：`audit_progress` **只查 trailer 存在性，不查真伪**。」
  ★ 本卡就补**复核端**：**内容必须与 `gates/last.json` 的实际结论对得上**。

## 要做什么（都在复核侧）

1. **`tools/wb_review.py`**（复核器，已经有 6 档：audit / trailer / 门禁是否为这笔记跑的 / 越界 / 干净 / 卡域）
   新增（或强化现有那一档）：**把提交信息的 `Gates:` 行与 `gates/last.json` 对账**：
   - 读提交信息的 `Gates:` 行；读 `gates/last.json` 的 `ok` / `rev` / （若有的）门数与未跟踪清单字段；
   - **判据**（照这个写，别自己发明方向）：
     (a) `last.json.ok == true` **且** `last.json.rev == 本提交的父提交` ⇒ trailer 必须声称**跑过全量门禁**
       （至少含"门禁绿/seal"这类字样），否则 ⇒ **拒**（声称与事实不符）；
     (b) `last.json.ok == false`，**或** `rev` 不是本提交的父提交 ⇒ trailer **不许**声称"全量门禁绿 + seal"，
       否则 ⇒ **拒**（这就是"伪造门禁结论"的机器版）；
     (c) ★ **`--no-gate` / `--commit-only` 形态**：trailer 写的是"**没跑门禁**"（或"复用已绿的那一趟"）⇒
       **放行，但必须在输出里如实标一行**「这一笔**没有**本轮门禁结论（`--no-gate` 形态）」，
       并在 `--json` 里给字段 —— **不许**把它当成"门禁绿"混过去；
   - ★ 报错必须**点名**：同一个提交里 `Gates:` 行原文 + `last.json` 的实际 `ok`/`rev`（"为什么说你假"）。
2. ★ **别把这条做成第二份真源**：`audit_progress.py` 只管"trailer 在不在"（**保留**），
   真伪归**复核器**（本卡）；在 `wb_review.py` 的注释里写清这个分工。

## 验收（照这个报）

- ★ **反例钉子**（放进 `tests/test_wb_review.py`；每条要"故意坏掉会红"）：
  ① **伪造"门禁绿"**：`last.json.ok=false`（或 `rev` 对不上）+ trailer 写 `Gates: 全量门禁绿 + seal` ⇒ **拒**，
     输出里**同时**出现 trailer 原文与 `last.json` 的读数；
  ② **真绿**：`ok=true` + `rev` = 父提交 + trailer 说绿 ⇒ **过**；
  ③ **`--no-gate` 形态**：`ok=false`（或没有本轮门禁）而 trailer 写"没跑门禁" ⇒ **放行**，
     且输出/`--json` 里有"**没有本轮门禁结论**"这一行；
  ④ **`--commit-only` 形态**：trailer 写"复用已绿的那一趟" ⇒ 放行并标注；
  ⑤ **`Task:` 仍恰好一个**（别把这条判据做成把 trailer 检查整段替换掉）。
- 贴：`python -X utf8 -m pytest tests/test_wb_review.py --no-cov` 尾行；`ruff check tools tests` 尾行；
  ★ 一条**真读数**：在**真仓库**对**本批之前的某一笔真提交**跑一次（例如 `bd711a0`），
  贴它对 `Gates:` 那一档的原样输出（应当**过**，因为它就是真跑的门禁）。
- ★ 不许跑全量门禁、不许 commit/tag、不许动主树与别的树、**不许**改 `scripts/audit_progress.py`
  （那条"存在性"判据保留 —— 分工不同）。

## 交成送申请（**最后一步，别忘**）

```
python -X utf8 tools/wb_task.py claim B-FIX4 M-2 --claim success --files "tools/wb_review.py,tests/test_wb_review.py" --why "<一句话：真伪怎么对账、三种形态各自怎么处置>" --evidence "<pytest 尾行 / ruff 尾行 / 五条钉子读数 / 真仓库对 bd711a0 的原样输出>"
```

## 禁区

白名单 = `tools/wb_review.py`、`tests/test_wb_review.py`。
不改 `scripts/audit_progress.py`、不改 `gates/**` 的产物、不提交。

## 回报格式（六项）

1. 改了哪些文件 + 一句话；2. 三种形态的处置（真绿 / 伪造 / 没跑门禁）；3. 报错文本样例（贴一段）；
4. 五条钉子读数 + 真仓库那一次的原样输出；5. **没做到 / 不确定**；6. 该改但不属本卡的地方。
