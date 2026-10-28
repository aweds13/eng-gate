# 卡 E64 —— 同一个提交，两把尺子量出两个 sha（短 sha 前缀比较）

> 台账号 **T-AG522** ｜ 分区 **E**（CI / 门禁） ｜ 树 `.wt/E64`
> 依据：卡 E63 落地 `63746025` 后 `wb_verify --tree .` 在**干净树**上报
> `FAIL 门禁：rev=77dc71cb≠77dc71cb` —— 两个值肉眼一模一样，判据却说不一样。

## 要解决的问题

`tools/wb_verify.py` 的 rev 判据写的是：

```python
rev_short = rev[:len(parent)] if parent else rev
rev_ok = bool(rev) and parent.startswith(rev)
```

- `rev` 来自门禁产物 `gates/last.json`，长 **10** 位（`scripts/run_gates.py` 记 `rev[:10]`）；
- `parent` 来自 `git rev-parse --short HEAD^`，长 **8** 位（`tools/wb_verify.py:167`）；
- 于是 `"77dc71cb".startswith("77dc71cb77")` **恒为 False** —— 只要门禁记录 10 位、
  `--short` 给 8 位，**每一笔落地都会被判「rev != 父提交」**。

这不是「读数不好看」，它让一条本来成立的判据**永远说假话**：真的「一次门禁跑完提交两笔」
和正常的落地，读出来一模一样的 FAIL ⇒ 判据失去分辨力（与卡 E63 同一病根：判不出来的时候
说了话，但说的是错话）。

## 判据（3 条）

1. **任一方向的前缀都算同一次提交**：`rev` 是 `parent` 的前缀、或 `parent` 是 `rev` 的前缀，
   都判 `rev_ok`。两侧都短于 **7** 位时判不成立（太短没分辨率，宁可红）。
2. **反向钉子**：真不同的提交（换一个 sha 的首位字符）必须判红；空 `rev`、空 `parent` 也判红。
3. **绿对照**：`tests/test_wb_verify_rev.py` 里用「10 位 rev + 8 位 parent」「8 位 rev + 40 位 parent」
   两组正例 + 两组反例，全部走**真函数**（不复制实现）。

## 交付

- `tools/wb_verify.py` 的 `check_gates()` 里修 rev 判据（唯一一处）。
- `tests/test_wb_verify_rev.py`（新建，纯 LF 或与仓内一致的行尾），4~6 条用例。
- `docs/subsystems/ci/测试流程.md` 里如提到 `wb_verify` 的 rev 口径，跟上（若无则不动）。

## 验收

```bash
python -X utf8 -m pytest tests/test_wb_verify_rev.py -q -o addopts= --no-cov
python -X utf8 tools/wb_verify.py --tree .        # 本笔之前应只剩这一条 FAIL，落地后 FAIL=0
python -X utf8 scripts/run_gates.py               # 云机跑（m12391）
```

## 不许做

- 不许放宽成「前 6 位相同就算」或「不看 rev」—— 那会把真缺陷一起放过去。
- 不许改 `scripts/run_gates.py` 记录 rev 的长度（那是产物的既定口径，改它等于改所有旧产物）。
- 不许顺手改并发指纹（`co_tenants`）：那是另一张卡（E65）的事，混在一笔里落地就分不清是谁的红。
