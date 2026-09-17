# 复盘 · check_layers 脚本修复与验证（含环境修复）

> 阶段：接《docs一致性修复记录》。上一轮改了 `scripts/check_layers.py`，本轮**验证它真的有效**。
> 结果：脚本修复 3 处缺陷 + 新增自测；质量门四项全绿；顺带修好了阻断 pytest 的环境问题。
> 性质：**工程复盘**（怎么发现问题、怎么验证、得出什么教训）。

---

## 一、本轮做了什么（按时间顺序）

| 步骤 | 动作 | 结果 |
|---|---|---|
| 1 | 跑 `check_layers.py` 验收 | PASS ✅（但需要证明它"真能抓出问题"） |
| 2 | 发现 pytest 跑不了（7 个 collection error） | 判定为**环境问题**（非本次改动造成） |
| 3 | 对脚本做**正负样例测试** | 抓出 **3 个脚本缺陷** |
| 4 | 逐个修复缺陷 | 见下 §二 |
| 5 | 新增 `scripts/test_check_layers.py`（自测脚本） | 1 正样例 + 3 负样例 + 1 豁免用例，全过 |
| 6 | 修好环境（重装 editable 包） | pytest 恢复正常 |
| 7 | 跑完整质量门 | pytest 44 passed / ruff 0 / mypy 0 / 五层 PASS |

---

## 二、脚本缺陷修复（均由自测抓出）

### 缺陷 1：正则不支持中文文件名（最严重·静默漏检）

**原代码**：
```python
pattern = re.compile(r"`(\.{0,2}/?[A-Za-z0-9_\-/]+\.md)`")
```
**问题**：字符集 `[A-Za-z0-9_\-/]` 只含**英文、数字、下划线、横线、斜杠**——**中文文件名字符不在内**。

**后果**：本库大量中文文档名（如 `复盘/MVP结构梳理-框架与交叉.md`）引用**完全无法被匹配**，等于"检查器对中文路径视而不见"——**断链不会被发现**。

**修复**：
```python
pattern = re.compile(r"`([^\s`]*?\.md)`")   # 非空白、非反引号的任意字符（含中文）
```

**验证**：
| 测试串 | 修复前 | 修复后 |
|---|---|---|
| `` `contracts/nonexistent-file.md` `` | 匹配 ✅ | 匹配 ✅ |
| `` `contracts/绝不存在的文件.md` `` | **不匹配** ❌ | 匹配 ✅ |

---

### 缺陷 2：`rglob` 传入含路径分隔符的串 → 脚本崩溃

**原代码**：
```python
if "/" not in rel:
    candidates += [p.resolve() for p in docs_root.rglob(rel)]
```
**问题**：正则放宽后，`rel` 可能含反斜杠（Windows 路径 或 匹配到含分隔符的串），此时 `rglob("a\\b.md")` 抛异常：
```
NotImplementedError: Non-relative patterns are unsupported
```
**后果**：脚本**直接崩溃**（不是报错，是挂掉）。

**修复**：同时检查两种分隔符
```python
if "/" not in rel and "\\" not in rel:
    candidates += [p.resolve() for p in docs_root.rglob(rel)]
```

---

### 缺陷 3：绝对路径未豁免 → 误报断链

**问题**：`taste/README.md` 里引用了**项目外**的绝对路径：
```
D:/docs\知识库\Jelly文件_Pro\vibe-coding-1\TASTE.md
```
它确实不存在于项目内，但**这不是断链**——是"项目外参考"（已在文档中标注）。

**后果**：脚本误报，把"合理引用"当成"断裂"，制造噪声。

**修复**：豁免 URL 与绝对路径
```python
if rel.startswith(("http", "/")) or re.match(r"^[A-Za-z]:[\\/]", rel):
    continue   # 项目外引用，不属本检查范围
```

---

### 附带：ruff 报告的 4 个问题

- 行超长 ×3（`line-length=100`）
- `N806`：函数内局部变量用大写 `KNOWN_MISSING` → 改小写 `known_missing`

---

## 三、新增：脚本自测 `scripts/test_check_layers.py`

**为什么要自测？**
护栏脚本（检查别人的工具）**自己错了没人知道**——最糟的情况是"永远输出 PASS"，给人虚假安全感（这正是本次扩展前的状态）。

**自测内容**（1 正 + 3 负 + 1 豁免）：

| 用例 | 做法 | 期望 |
|---|---|---|
| **正样例** | 干净仓库直接跑 | PASS |
| **负样例1** | 往 `conventions.md` 插一条无 N 标注的规则 | FAIL 且报"未标注来源 N" |
| **负样例2** | 往 `README.md` 插一条指向不存在文件的引用 | FAIL 且报"引用断裂" |
| **负样例3** | 往 `flows.md` 插一条引用不存在的 SR | FAIL 且报"不存在的 SR" |
| **豁免用例** | 确认 `DESIGN.md` 被豁免 | 不报断链 |

**实现要点**：临时注入 → 跑检查 → **还原原文件**（用 `try/finally` 保证还原）。全程用 Python 写文件（避免 PowerShell 追加内容时的 GBK 编码坑）。

**结果**：
```
[正样例] 干净仓库 → exit=0
[负样例1] 约定层缺 N 标注 → exit=1
[负样例2] 断链引用 → exit=1
[负样例3] 契约层引用未知 SR → exit=1
SELF-TEST PASS ✅ （1 正样例 + 3 负样例 + 1 豁免用例）
```

> **关键**：第一次跑自测时，**负样例2 失败了**（没抓出断链）——正是这个失败暴露了"缺陷1：中文路径不匹配"。**自测的价值在这里体现。**

---

## 四、环境修复（pytest 能跑了）

### 问题：pytest 报 7 个 `ModuleNotFoundError: No module named 'timeflow'`

### 根因（已确证）

安装的 editable 路径指示文件指向**旧路径**：
```
C:/Users/example\miniconda3\Lib\site-packages\__editable__.timeflow-0.1.0.pth
   内容：D:/docs\engineering\src          ← 项目迁移前的旧路径，已不存在
```
> 项目从 `D:/docs\engineering\` 迁移到了 `D:/repo/engineering\`，但 Python 的"安装记录"还指着老地方。

### 修复命令

```bash
python -m pip install -e ".[dev]" --no-build-isolation -i https://pypi.tuna.tsinghua.edu.cn/simple
```

- 第一次不加 `--no-build-isolation` → 失败（构建隔离环境拉不到 `setuptools>=68`）
- 加 `--no-build-isolation`（用本地已有的 setuptools 82.0.1）→ **成功**

### 验证

```bash
python -c "import timeflow; print(timeflow.__file__)"
# → D:/repo/engineering\src\timeflow\__init__.py   ✅
```

> 注意：环境修复**不在 Git 里**（改的是 Python 安装状态，不是仓库文件），所以没有产生新提交。

---

## 五、最终验收（全部真实执行）

| # | 检查 | 命令 | 结果 |
|---|---|---|---|
| 1 | pytest | `python -m pytest` | ✅ **44 passed**, 1 warning, 1.29s |
| 2 | ruff | `ruff check src/ tests/ scripts/` | ✅ All checks passed |
| 3 | mypy | `mypy src/`（strict） | ✅ no issues in 29 source files |
| 4 | 五层对齐 | `check_layers.py` | ✅ LAYER CHECKS: PASS |
| 5 | 脚本自测 | `test_check_layers.py` | ✅ SELF-TEST PASS |

---

## 六、教训（可复用）

1. **护栏脚本必须自测** —— 它是"错的没人知道"的东西。必须用**负样例**证明它真能抓出问题；只测"正常通过"毫无意义。
2. **负样例要覆盖真实场景的多样性** —— 本次"中文文件名"这个漏洞，只有负样例才暴露得出来（正样例永远通过）。
3. **正则的字符集是常见陷阱** —— `[A-Za-z0-9_]` 这类写法默认排除一切非 ASCII，中文环境必踩。
4. **文件引用检查要区分"相对/绝对/待建"** —— 三类语义不同，不能一刀切当断链。
5. **项目迁移后要重装 editable 包** —— `.pth` 文件记的是绝对路径，迁移即失效。
6. **测试要能安全还原** —— 注入式测试必须 `try/finally` 还原，否则污染仓库（本次用 git 校验了无残留）。

---

## 七、本次未处理（明确遗留）

| 项 | 说明 |
|---|---|
| `scripts/` 无 pytest 集成 | 自测脚本是独立可执行，未纳入 `pytest` 收集（`testpaths=["tests"]`）。可选：移入 `tests/` 或改配置 |
| `DESIGN.md` / `LEARN.md` | 仍待建（SR-NF9 要求） |
| 上轮仓库提交 | 代码修复已提交 `a20a461`；环境修复不入库 |
