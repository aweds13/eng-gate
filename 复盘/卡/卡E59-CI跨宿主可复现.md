# 卡 E59 —— 让 CI 真的能在另一台机器上复现：编码、防窗、云门禁脚本的可移植性

> 台账号 T-AG516 · 分区 E · 批号 B-20261052（与 F8、G6 同笔落地）
> 依据：云门禁 B-20261051 连跑三趟，每一趟的红都不是「代码逻辑错」，
> 而是「只在 Windows 中文 locale + 本机私有状态 + 无 TTY 的云机上才现形」。

## 要解决的问题

云机第一趟 21 门 6 红，逐条追下来是五类**宿主依赖**，没有一条是业务逻辑：

1. **`subprocess.run(text=True)` 不写 `encoding=`**：云机 stdout 是 cp936，
   git 一输出中文就 `UnicodeDecodeError`，`r.stdout` 变 `None`，随后
   `.strip()` 抛 `AttributeError: 'NoneType' object has no attribute 'strip'`。
   本机因为默认编码恰好是 UTF-8，永远不出问题 —— 这是**只在别人机器上才炸**的缺陷。
   全仓 30 个文件 / 58 处同型，AST 扫出 **23 处真缺**。
2. **有 `encoding=` 但缺 `errors=`**：`errors` 缺省是 `strict`，
   遇到无法解码的字节同样抛 `UnicodeDecodeError`。又扫出 **23 处**。
3. **`subprocess.run` 没带防窗旗**：Windows 上每起一个子进程就闪一个黑框；
   `tests/test_no_window.py` 用「行内容指纹」锁住每一处调用，
   于是任何改动行号/参数都会让它红 —— 它咬得准，但也因此极脆。
4. **`scripts/cloud/run_gate.sh` 把开发机路径与一台失效的默认云机写死**：
   `HOST="${CLOUD_HOST:-administrator@203.0.113.12}"` 意味着**没配就去连一台死机器**，
   失败现场看起来像网络问题、不像配置问题；`D:/docs/...` 这类盘点路径也散在注释里。
5. **`scripts/run_gates.py` 不写 `host`**：云机跑完回传的 `last.json` 没有
   「这是哪台机器跑的」凭证，落地链的「必须是云机跑的」永远判不过。
6. **本机私有状态被写进 `.git/info/exclude` 而不是入库的 `.gitignore`**：
   `.wt/` 就是活例子 —— 本机有那行、云机没有，于是云机上 20 条 `.wt/...` 引用
   全被算成死指针（`docs` 门 152 → 172）。同类还有 `gates/review/`（93 个产物）
   与 `tools/settings.toml`（面板改并发度时写出来的本机参数）。

## 判据（五条）

1. **全仓 `subprocess.run(...)` 必须显式给 `encoding=` 与 `errors=`**，
   由钉子 `tests/test_subprocess_encoding.py` 用 AST 判：`text=True` / `universal_newlines=True`
   且缺 `encoding=` ⇒ 红；给了 `encoding=` 但缺 `errors=` ⇒ 红。
   例外必须在 `EXEMPT` 里逐条写理由，且理由本身被钉住（过期豁免会红）。
2. **每处 `subprocess.run` 都带防窗旗**（`NO_WINDOW` / `creationflags`），
   `tests/test_no_window.py` 的 `EXEMPT` 里不许留过期条目；
   因改动导致指纹漂移时，补旗而不是删用例。
3. **`scripts/cloud/run_gate.sh` 不含任何开发机绝对路径，也不给云机默认值**：
   缺 `CLOUD_HOST` ⇒ `exit 9`（fail fast，与缺 `TF_PROJECTS_TOML` 的 `exit 2` 并列：
   都是「配置没给、不是代码坏」）；缺 `TF_PROJECTS_TOML` ⇒ `exit 2`。
   由 `tests/test_ci_portability.py` 扫 `scripts/cloud/**` + `scripts/run_gates.py`，
   禁硬编码盘符 / IP 字面量，白名单每条写理由**且白名单本身被钉住**。
4. **云机回传的 `last.json` 必须带非空 `host`**（`socket.gethostname()`），
   且它**不进 `payload_env_fields()`**（`tests/test_gates_reuse_line.py` 精锁那个键集）。
   `run_gate.sh` 读完回传后校验 `host` 非空，空则明说「证明不了是云机跑的」。
5. **可复现性清单成文**：`docs/subsystems/ci/云门禁-可复现性清单.md` 逐条写出
   「换个宿主会怎么坏 / 判据在哪 / 怎么自查」，每条都指到真被测试咬住的位置。
6. **本机私有状态一律进入库的 `.gitignore`，不进 `.git/info/exclude`**：
   `git check-ignore -v <路径>` 必须命中 `.gitignore`（不是 `info/exclude`）——
   后者不随树分发，云机上没有，这正是 B-20261051 那 20 条假死指针的成因。
   本轮要落的三条：`.wt/`、`gates/review/`、`tools/settings.toml`(+`.tmp`)。

## 交付

- `tests/test_subprocess_encoding.py`（AST 钉子，634 行）
- `tests/test_ci_portability.py`（新建）
- `docs/subsystems/ci/云门禁-可复现性清单.md`（新建）
- `scripts/cloud/run_gate.sh`（去默认 IP、去开发机路径、`exit 9`、host 校验）
- `scripts/run_gates.py`（`host` 字段 + 4 处防窗旗 + 7 处 encoding/errors 清扫）
- `tests/test_no_window.py`（过期豁免清理）
- 16 个文件的 `encoding=`/`errors=` 补齐：`tools/pool/landing.py`、`tools/gate_pool.py`、
  `tools/wb_*.py`、`scripts/audit_progress.py`、`scripts/check_docs.py` 等（逐条见 diff）
- `tools/sync_worker_skills.py`、`tools/check_mapping.py`、`tools/replay_worker_edits.py`（连带）
- `.gitignore`（`.wt/` / `gates/review/` / `tools/settings.toml` 三条私有状态规则）
- `tests/conftest.py`（摘掉宿主 `DSH_SESSION_ID` 指纹）与 `tests/test_host_fingerprint_moat.py`

## 验收

```
python -X utf8 -m pytest tests/test_subprocess_encoding.py tests/test_ci_portability.py \
    tests/test_no_window.py tests/test_gates_reuse_line.py -q     # 期望全绿
python -X utf8 -m pytest tests/test_subprocess_encoding.py -q --tb=no | tail -2
python -X utf8 - <<'PY'
import pathlib, subprocess
t = pathlib.Path("scripts/cloud/run_gate.sh").read_text(encoding="utf-8", newline="")
assert "203.0.113.12" not in t and "D:/" not in t, "run_gate.sh 还有硬编码"
for rel in (".wt/x", "gates/review/x.json", "tools/settings.toml"):
    r = subprocess.run(["git", "check-ignore", "-v", rel], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert ".gitignore" in r.stdout, (rel, r.stdout)
print("OK")
PY
```

## 不许做

- 不许把 `tests/test_subprocess_encoding.py` 的 `EXEMPT` 当成垃圾桶：
  每条都要写「为什么这里不能给 encoding」，且测试会咬过期条目。
- 不许给 `run_gate.sh` 加回任何默认云机地址 —— 宁可 `exit 9`。
- 不许把 `host` 塞进 `payload_env_fields()`（复用台账的键集是精确锁的）。
- 不许为了消一条 `test_no_window` 红而删掉那条用例：补旗，别删判据。
- 不许把私有状态的忽略规则只写进 `.git/info/exclude`：它不随树分发，云机上等于没有。
- 不许 `read_text`/`write_text` 改 `scripts/run_gates.py` 与 `scripts/cloud/run_gate.sh`：
  前者入库 blob 里是双重 CR，后者是 CRLF，文本模式会静默归一 —— 用字节级读写。
