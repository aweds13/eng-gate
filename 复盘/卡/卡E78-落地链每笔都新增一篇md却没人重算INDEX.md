# 卡 E78 —— 落地链每笔都新增一篇 md，`docs/INDEX.md` 却没人重算（T-AG581）

> 台账号 `T-AG581` ｜ 分区 E（门禁与可信度）｜ 树 `.wt/E78` ｜ 层 判据层
> 基准提交 `0046e1d2`（主树 HEAD，E77 刚落）。
> 前情：卡 E76 把「落地链自己改的东西自己验证」这条判据立在**现算 README** 上，E77 又把它补成三条腿 + 独立 checker。**本卡是同一个病的第二个面** —— E76 落地时自己记进缺口、明说「另开卡」，现在开。

## 要解决的问题（已实测，不是推测）

`scripts/gen_doc_index.py` 的 `collect()`（`:133`）用 `base.rglob("*.md")` 扫 `docs/`，`docs/INDEX.md` 里有一张**按目录计篇数的表**：

```
| `docs/changelog.d/` | 282 | 0 | 282 |
```

而落地链每笔**自动新增一篇** `docs/changelog.d/{task}.md`（`tools/pool/landing.py:93 RESET_FRAGMENTS` / `:2406` 附近的自动补片段）：

```python
for frag in (f"docs/changelog.d/{a.task}.md", f"docs/traceability.d/{a.task}.toml",
             f"复盘/交接.d/{a.task}.md"):
```

⇒ **每落一张卡，`docs/INDEX.md` 的篇数就过期一次。** 而落地链里**零调用** `gen_doc_index.py`：

```
grep -rn "gen_doc_index" tools/ ⇒ 零命中
grep -rn "gen_doc_index" tools/pool/landing.py gates/diag/_land_any.py ⇒ 零命中
```

今天没红，是因为**我（主控）在每张卡收活时手工跑了一次 `gen_doc_index.py`**，而且它跑在门禁**之前**（门禁在 ④、翻账在 ⑤′）—— 和 E76 修的那个洞**一模一样**：判据只在「下一次有人跑门禁」时才说话，而那时已经错了。

**这与 E76 的缺陷同构到逐字**（E76 是 `docs/subsystems/pool/README.md`，本卡是 `docs/INDEX.md`），所以修法应当**复用 E76/E77 已经立好的三条腿**，而不是再发明一套。

## 判据（5 条，逐条可执行）

1. **落地链必须重算 `docs/INDEX.md`**：`tools/pool/landing.py` 第 ⑤′.5 步（E76 落的 `recount_derived()`）**必须一并覆盖** `docs/INDEX.md`，不只是 README。断言：造一个「翻账会让 INDEX 篇数过期」的场景，跑落地链 ⇒ INDEX 与现算一致。
2. **`scripts/check_derived_docs.py` 覆盖第二个目标**：它今天是「跑 `gen_pool_readme.py` + `--check`」的单目标壳，必须扩成**多目标**（README + INDEX），且**仍然不含任何现算口径**（判决权全在两个生成器里）。断言：删掉 INDEX 那一支 ⇒ 判据 1 的钉子红。
3. **`--check` 仍能抓到过期**：`scripts/gen_doc_index.py --check` 遇到过期必须退非零并**逐行点名**（既有行为，本卡不许削弱）。断言：手工把 INDEX 的篇数改错一个数 ⇒ `--check` 退 1 并点名。
4. **`--commit-only` 也被覆盖**：E76/E77 的三条腿里腿② 在提交之后、前置腿在开跑前 —— 断言 `--commit-only` 落地后 INDEX 与现算一致（或 loud failure，不许静默）。
5. **不许削弱既有判据**：`tests/test_gen_doc_index_fresh.py` 与 `tests/test_pool_readme_counts.py` 的钉子**一个字不动**；两个生成器的现算口径**一个字节不动**。

## 交付

1. `scripts/check_derived_docs.py` 扩成多目标（README + INDEX）。★ **它还是只当调用方**：不出现 `rglob` / 篇数口径 / `render_docs` 之类的现算逻辑（E77 的 `M4` 变异钉的正是这条）。
2. `tools/pool/landing.py` 的 `RECOUNT_DOCS` / `recount_derived()` 相应扩展（若你判断实现上更该由 checker 一处统管，也可以 —— 但**判据 1 必须真被覆盖**）。
3. **本笔必须把 `docs/INDEX.md` 重算到与现算一致**（现场证据，不是顺手改）。
4. 新测试（并进 `tests/test_pool_landing.py`，**不许在卡规格里点名新文件名**），5 条判据每条至少一条钉子。
5. `gates/diag/_rev_E78.py`：≥5 条变异，逐条真改坏、跑、证明某条钉子变红、再还原。★ 其中必须有一条是**「把 INDEX 那一支删掉 ⇒ 判据 1/2 的钉子红」**（证明它不是装饰）。

## 验收（跑完逐条报末行原文）

```bash
cd .wt/E78
python -X utf8 -m pytest tests/test_pool_landing.py tests/test_gen_doc_index_fresh.py tests/test_pool_readme_counts.py -q -o addopts= --no-cov
python -X utf8 scripts/gen_doc_index.py --check
python -X utf8 scripts/check_derived_docs.py --check
python -X utf8 -m ruff check scripts/check_derived_docs.py tools/pool/landing.py
python -X utf8 gates/diag/_rev_E78.py
```

## 不许做

- **不许**改 `scripts/gen_doc_index.py` 与 `scripts/gen_pool_readme.py` 的现算口径（前者是卡 F9 的交付物，后者是卡 F11 的）。
- **不许**把 `复盘/INDEX.md` 也塞进来：`gen_doc_index.py --check` 对它明确打 `[SKIP]`（归 `scripts/retro/retro_index.py` 全量生成，接管会丢主题分区与逐篇结论）—— 本卡只治 `docs/INDEX.md`。
- **不许**把「重算失败」做成静默跳过。
- **不许**碰六份 `PROTECTED_FILES`。

## 缺口（如实写在卡里）

1. `复盘/INDEX.md` 由 `scripts/retro/retro_index.py` 全量生成（769 篇 / 14 主题），落地链**不管它**；它会不会因新增 `复盘/交接.d/*.md` 而过期，本卡**不查**（若你顺手查了，把读数写进回执）。
2. 本卡只补 `docs/INDEX.md` 这一个目标；别的派生件（若还有）本卡**不普查**。
3. 只在本机 win32 验过。
