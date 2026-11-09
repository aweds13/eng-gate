# pika 技能包升级规程（唯一权威版）

> **一句话判据**：手上有「比当前已装更新的 pika 包」（`pika文件_Pro.zip` 或其中的
> `pika_math_learning_toolkit-*.zip`），要把技能装进 `C:/Users/example/.dsh/skills/`、
> 要把资料回填进 `D:/repo/`，就照这份走。**别的 pika 文档一律不再作为操作依据。**
>
> 最后复核：2026-11-08 00:05（本机实测，命令与读数逐条附在文中；§3 步骤 2 的备份脚本已原样实跑）
> 复核时状态：2.1.7 已装完、三方全 CLEAN、**无待覆盖文件**（`--only skills` 会删 0 条）
> 结构：§3 共 **8 步**；§6 共 **19 条坑**；§8 共 **10 条「不知道」**；附录 A 共 **7 组矛盾**（不写本文行数与字节数 —— 自指的量一改就错）
> 本文替代：`复盘/pika迁移-回填方案.md`、`复盘/pika迁移-新旧比对.md`、
> `D:/repo/_tools/pika-迁移/对应表.md`、`D:/repo/_tools/pika-迁移/宿主与环境变量.md`
> 的**操作部分**（那四份仍作历史证据保留，见附录 A）。

---

## §0 适用与不适用

### 适用（满足任意一条就走这套）

1. 拿到新的 `pika文件_Pro*.zip`，要把 7 个 skill 升到新版本。
2. pika 包里的 vault / 开源资源 / 代码与数据 要回填到 `D:/repo/`。
3. 要判断「本机那 74 个内容不同的文件，哪些是包修好的、哪些是我自己改的」。
4. 要复核 pika 的路径解析链（环境变量 / 配置 JSON / 自定位）现在指向哪。

### 不适用

| 情况 | 该走哪 |
|---|---|
| 只是问「某篇笔记在哪、讲什么」 | `obsidian-vault-notes` 技能，不涉及升级 |
| 只是想装一个全新 skill（不是 pika 的） | 手工放 `~/.dsh/skills/<name>/SKILL.md` |
| 只是想改 pika 的技能代码 | 那会变成「本机补丁」，先读 §4.4 判据再决定 |
| 要动 `Library/` 下我自己的书、`_observer-tools/`、`知识库/` 下非 pika 目录 | **永远不动**，不在本规程范围 |
| 要处理 `D:/downloads/pika文件_Pro.zip` 本身（改名/删除/解压到别处） | 本规程只以 `'r'` 只读打开它，不改不删 |

### 不变量（任何情况下都不许破）

- 外层包 `D:/downloads/pika文件_Pro.zip` **只读**。实测 sha256 = `4a0783365a9f30df…`，全程不许变。
- 三个「入党申请」相关 Markdown 文件（`program/OpenMAIC/` 下，untracked）**不碰**。
- 不 `git add`、不改已跟踪文档、不删任何文件（删除只发生在迁移器 verify 通过的条目上，且逐条打印绝对路径与原因）。

---

## §1 三条铁律

### 铁律一：先备份，且备份要三核

备份不是「拷一份」，是「拷完能证明拷全了」。三核缺一不可：

1. **文件数**：源侧与备份侧数量一致（`nul` 除外，见 §6.1）。
2. **字节数**：两侧总字节一致。
3. **sha256**：逐文件写进 `MANIFEST.json`，事后能对账。

任一核不上 ⇒ **打印「不要继续替换」并停**。历史事故里 74 个文件被覆盖，
当时唯一「找不到任何副本」的那个 `workspace.json` 之所以没副本，是因为
**它所在的整棵 `笔记共享vault/.obsidian/` 从来没被 `git add` 过**（实测
`git ls-files '知识库/pika文件_Pro/笔记共享vault/.obsidian'` → 0 条），而备份又还没做。
两者叠加才是「不可恢复」的真正原因 —— 不是某一条 `.gitignore` 规则。
（后来从回收站救回，见 §6.9。）

### 铁律二：只增不覆盖 —— 覆盖只发生在「能证明旧版没被改过」的文件上

顺序**不能反**：`验证 → 备份 → 删除 → 写入`。四条理由：

- verify 必须先跑：它同时证明「新版存在且内容正确」**和**「旧版现场 == 勘察记录」。
  后一条不成立，说明这个文件被我改过，**不许覆盖**。
- backup 必须在 delete 之前：不然删了就没得备。
- delete 必须在 place 之前：不先清空位，就会留下「旧版有、新版已删」的残留文件。
- 每一个删除动作都必须先打印**绝对路径 + 原因 + 新版来源**，人看过再 `--execute`。

反面教材：`_tools/pika-迁移/_已执行/apply_skills.py` 走的是
「先 `shutil.rmtree` 整个技能目录，再从 zip 解压」——那会把本机补丁一起删掉，
**不要复用**。

### 铁律三：vault 内容写内层，`.obsidian/` 写外层例外 —— 一份都不许错位

| 对象 | 谁是目标 | 依据（实测） |
|---|---|---|
| vault **笔记内容**（Markdown / 图片 / `.stego_backups`） | `D:/repo/知识库/pika文件_Pro/笔记共享vault/` | zip 里的 `__vault__/` 与之 1127 对 1127，是同一个东西 |
| `.obsidian/`（Obsidian 配置） | **`D:/repo/知识库/.obsidian/`，且永不覆盖** | 见下 |

为什么 `.obsidian/` 是例外：

- Obsidian 注册表 `%APPDATA%/obsidian/obsidian.json` 只有**一个**库：
  `{"vaults":{"bcdcbb444ed9fb91":{"path":"D:/repo\\知识库","open":true}}}`
  ⇒ 我实际打开的是**外层** `知识库`。
- 外层 `.obsidian/` 的 `workspace.json` mtime 是 **2026-11-05 10:22:23**（我 11-05 还在用）；
  内层那份 mtime 是 **2026-10-31 19:53:11** —— 正是事故解压的时间，等于包内原样。
- 外层 `appearance.json`（221 B）里有我的字体与 CSS snippet
  （`Microsoft YaHei UI,GenYoGothic2 PJP N` / `enabledCssSnippets:["bold-use-real-pjp-b"]`）；
  内层（130 B）是 `Comic Sans MS` + `MV Boli,Arial Black` + 无 snippet。
  **谁把内层写进外层，我的字体和 snippet 就没了。**

⇒ 迁移器把 `知识库/.obsidian` 列为「待裁决、本脚本不删」，这是**正确行为，不要绕过它**。

---

## §2 前置检查（逐条给命令与期望读数）

全部在 `D:/repo` 下跑。任一条不符 ⇒ 先解决再往下。

### 2.1 Python 与编码

```bash
python -X utf8 -c "import sys; print(sys.version.split()[0], sys.executable)"
```

期望：`3.14.6 C:/Users/example\miniconda3\python.exe`
失败：Python < 3.11 会缺 `Path.unlink(missing_ok=)` 等；换 conda 环境。
`-X utf8` **每次都要带**，否则中文路径在某些宿主下会 `UnicodeEncodeError`。

### 2.2 外层包完整性与指纹

```bash
python -X utf8 -c "
import zipfile, os
p = r'D:/downloads/pika文件_Pro.zip'
z = zipfile.ZipFile(p)
print('entries', len(z.namelist()))
print('size', os.path.getsize(p))
print('testzip', z.testzip())
"
```

期望（实测）：
```
entries 2411
size 1451498774
testzip None
```

再核 sha256（约 5 秒）：

```bash
python -X utf8 -c "
import hashlib
h = hashlib.sha256()
with open(r'D:/downloads/pika文件_Pro.zip','rb') as f:
    for b in iter(lambda: f.read(1<<20), b''): h.update(b)
print(h.hexdigest())
"
```

期望：`4a0783365a9f30df7a491c2ac9d978366c43859c618c1f47e0fd06dc6c785a07`

失败处理：
- `testzip` 返回非 `None` ⇒ 包坏了，**停**。重新拿包。
- sha256 不符但 testzip OK ⇒ 换过包了（正常情况：新版本到了）。**记下新指纹**，
  并在报告里写明「本次换包」；`b3_fullhash.json` 需要重算（见 §3.3）。

### 2.3 内层三个包在不在、条目数对不对

```bash
python -X utf8 -c "
import io, zipfile
z = zipfile.ZipFile(r'D:/downloads/pika文件_Pro.zip')
tops = [n for n in z.namelist() if n.endswith('/')]
print('dir entries', len(tops))
for m in ['pika文件_Pro/笔记共享vault.zip',
          'pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip',
          'pika文件_Pro/pika资料共享/代码与数据/grid-covering-lab-source.zip']:
    f = zipfile.ZipFile(io.BytesIO(z.read(m)))
    print(m.split('/')[-1], len(f.namelist()), sum(i.file_size for i in f.infolist()))
"
```

期望（2026-11-07 实测 2.1.7 包，三列 = 名字 / `namelist()` 条数 / `file_size` 合计）：
```
dir entries 0
笔记共享vault.zip 1164 245602915
pika_math_learning_toolkit-2.1.7.zip 488 7190171
grid-covering-lab-source.zip 48 192845
```
（vault 内层 1164 条目含 **37 个目录条目**，解压后文件 **1127**。
换版本时这三个数字都会变 —— **对不上不等于出错，只说明「包换了」**，重算清单即可。

★ 新版包名带版本号，换版本时**这三个键名要跟着改**；键名写错会抛
`KeyError: "There is no item named '…' in the archive"`（见 §6.4）。

### 2.4 7 个 skill 已装齐全

```bash
for s in compute-fleet-manager manage-personal-knowledge math-coach \
         math-research-solve math-science-computation obsidian-vault-notes pdf-problem-search; do
  printf "%-28s %s\n" "$s" "$(test -f "C:/Users/example/.dsh/skills/$s/SKILL.md" && echo OK || echo MISSING)"
done
```

期望：7 行全 `OK`。
失败：`MISSING` ⇒ 该 skill 没装过，走「新增」路径（`place` 直接写），
但 `suite_doctor.py` 会因此 exit 1（见 §6.13）。

### 2.5 三个环境变量（这是真相所在）

```bash
powershell -NoProfile -Command "
[Environment]::GetEnvironmentVariable('OBSIDIAN_LOCAL_KB_ROOT','User')
[Environment]::GetEnvironmentVariable('OBSIDIAN_VAULT_NOTES_CONFIG','User')
[Environment]::GetEnvironmentVariable('OBSIDIAN_LOCAL_KB_DB','User')
"
```

期望（2026-11-07 实测 = 实际值）：
```
C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb
C:/Users/example\AppData\Roaming\pika_math_learning_toolkit\obsidian-vault-notes.json
C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3
```

再确认指向都存在：

```bash
python -X utf8 -c "
import os
for k in ['OBSIDIAN_LOCAL_KB_ROOT','OBSIDIAN_VAULT_NOTES_CONFIG','OBSIDIAN_LOCAL_KB_DB']:
    v = os.environ.get(k)
    print(k, '=', v, '| exists', os.path.exists(v) if v else None)
"
```

期望：三条 `exists True`。
（`OBSIDIAN_LOCAL_KB_ROOT` 是**目录**；`isfile` 为 False 是正常的，别当失败。）

★ 另外 8 个相关变量**本机全未设**，都是「设了才会改变行为」的：
`OBSIDIAN_VAULT_ROOT`、`OBSIDIAN_LOCAL_KB_DATA_ROOT`、`PDF_PROBLEM_SEARCH_ROOT`、
`PERSONAL_KNOWLEDGE_ROOT`、`MPK_CONFIG_PATH`、`MPK_STATE_DIR`、`MPK_SKILLS_ROOT`、`CODEX_HOME`。

### 2.6 配置文件存在且没指死路径

```bash
python -X utf8 -c "
import json, pathlib
p = pathlib.Path(r'C:/Users/example/AppData/Roaming/pika_math_learning_toolkit/obsidian-vault-notes.json')
d = json.loads(p.read_text(encoding='utf-8'))
print('size', p.stat().st_size)
for k, v in d.items(): print(' ', k, '=', v)
for k in ('vault_root','kb_root','db_path'):
    print(k, 'exists =', pathlib.Path(d[k]).exists())
"
```

期望（实测 260 B）：
```
size 260
  schema_version = 1
  vault_root = D:/repo\知识库
  kb_root = C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb
  db_path = C:/Users/example\AppData\Local\obsidian-vault-notes\vault.sqlite3
vault_root exists = True
kb_root exists = True
db_path exists = True
```

失败：任一 `exists = False` ⇒ 那条路径被搬走了。**不要**手工改 JSON 里的路径，
先看 §5：路径应当由环境变量给，JSON 只是兜底。

### 2.7 vault 的 Markdown 篇数与索引数

```bash
python -X utf8 -c "
from pathlib import Path
r = Path(r'D:/repo/知识库')
print('md', sum(1 for _ in r.rglob('*.md')))
"
```

期望：`md 697`

再跑官方自检：

```bash
cd "C:/Users/example/.dsh/skills/obsidian-vault-notes/scripts"
python -X utf8 setup_local.py check
```

期望（exit 0；`python -X utf8` 下是**缩进 2 空格的 pretty JSON**，下面按字段列出）：
```
{
  "db_exists": true,
  "status_method": "stored_file_metadata",
  "indexed_at_utc": "2026-10-03T13:54:29Z",
  "schema_version": 3,
  "schema_mismatch": false,
  "vault_markdown_count": 697,
  "indexed_note_count": 683,
  "newer_markdown_count": 3,
  "missing_indexed_count": 28,
  "index_stale": true,
  "reindex_hint": "Index appears stale; run the refresh command before relying on broad retrieval."
}
{"status": "healthy", "config": "C:/Users/example\\AppData\\Roaming\\pika_math_learning_toolkit\\obsidian-vault-notes.json", "db_path": "C:/Users/example\\AppData\\Local\\obsidian-vault-notes\\vault.sqlite3"}
```

★ 注意 `db_path` 这里是**活库**（10-03），但运行时实际用的是 env 指的**死库**（09-13）——
`check` 只校验配置里的 `db_path`，不校验 env。**这是本机唯一的路径隐患，见 §5.4。**
★ `index_stale: true` + `reindex_hint` 是**正常**的（697 篇里 3 篇比索引新、28 篇没入索引），
不是升级失败。想刷新跑 `--build-index`，但那是**改索引**的动作，要单独决定。

失败：`RuntimeError("Configured Vault directory is missing.")` ⇒ `vault_root` 指错。
`RuntimeError("Configured bundled index module is missing or does not match this install.")`
⇒ `kb_root` 不是**当前这份安装**的 `obsidian_local_kb`（旧宿主遗留，见 §6.12）。

### 2.8 磁盘空间

```bash
df -h /d /c
```

期望（2026-11-07 23:1x 实测）：
```
Filesystem      Size  Used Avail Use% Mounted on
D:              243G  160G   83G  67% /d
C:              205G  178G   28G  87% /c
```
判据：D: 至少 **20 GB** 可用；C: 至少 **5 GB** 可用。
★ **C: 已经很紧（87% 已用，只剩 28G）**，而一次完整备份要 **约 256 MB**（落在 D: 上，
不占 C:），所以备份本身没问题；但**不要在 C: 上再复制一份 pika 包**。
D: 的 83G 是安全的。

### 2.9 仓状态（只记录，不要求干净）

```bash
cd "D:/repo"
git status --porcelain | wc -l
git log --oneline -1
```

期望（实测）：`53` 和 `ef04af7 chore(observer): 把 _observer-tools 重建的两份文件纳入 git`

★ **不要**为了「干净」去 `git add -A` 或 `git checkout .` —— 那会吞掉未跟踪的
`Tool/`、`.mpk/`、`知识库/.trash/` 与好几篇新笔记。脏就脏着。

### 2.10 `nul` 怪文件（预期存在，不是错误）

```bash
python -X utf8 -c "
import os
p = 'C:/Users/example/.dsh/skills/nul'
print('isfile', os.path.isfile(p), '| isdir', os.path.isdir(p), '| exists', os.path.exists(p))
print('size', os.stat(p).st_size)
"
```

期望：`isfile False | isdir False | exists True` + `size 0`

这是 Windows 保留设备名残留（2026-10-20 创建）。**不要试图删它，也不要试图 copy 它**
（两者都会炸，见 §6.1）。备份脚本按名字跳过即可。

---

## §3 标准流程（8 步）

> 每步都给了「命令 / 期望输出 / 失败怎么办 / 回滚」。
> 工具：`program/engineering/tools/pika_migrate.py`（1108 行，默认 dry-run）。
> 它**不做**：前置检查、pycache 清理、终态报告 —— 这三件由本规程的步骤补。

### 步骤 1／8：冻结现场

**目的**：留一份「动手前长什么样」的读数，出事后能证明「哪些是这次改的」。

```bash
cd "D:/repo"
mkdir -p "_tools/pika-迁移/_runs/$(date +%Y%m%dT%H%M%S)"
RUN="_tools/pika-迁移/_runs/$(date +%Y%m%dT%H%M%S)"
{
  echo "== git =="
  git log --oneline -1
  git status --porcelain | wc -l
  echo "== env =="
  powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('OBSIDIAN_LOCAL_KB_DB','User')"
  echo "== counts =="
  python -X utf8 -c "from pathlib import Path; print('md', sum(1 for _ in Path(r'D:/repo/知识库').rglob('*.md')))"
  echo "== zip =="
  python -X utf8 -c "import os; print('size', os.path.getsize(r'D:/downloads/pika文件_Pro.zip'))"
} | tee "$RUN/before.txt"
```

**期望**：`before.txt` 里 `md 697`、`size 1451498774`、git 头 `ef04af7`。

**失败怎么办**：`tee` 没写进去 ⇒ 目录不存在，先 `mkdir -p`。

**回滚**：本步只读，无需回滚。

### 步骤 2／8：备份（铁律一）

**目的**：一份能对账的备份，装的是 **`vault` 目录 + 整个 `skills` 目录**。

```bash
cd "D:/repo"
python -X utf8 - <<'PY'
import hashlib, json, shutil, time
from pathlib import Path

TS = time.strftime('%Y%m%dT%H%M%S')
MIG = Path('D:/repo/_tools/pika-迁移')
DEST = MIG / f'_backup_{TS}'
SRC = [('vault',  Path('D:/repo/知识库/pika文件_Pro')),
       ('skills', Path('C:/Users/example/.dsh/skills'))]
SKIP_NAMES = {'nul'}            # Windows 保留名，复制会 [WinError 87]
DEST.mkdir(parents=True, exist_ok=False)   # 已存在就炸，绝不覆盖上次备份

man = {'created_at': TS, 'sources': [], 'files': [], 'skipped': []}
total = 0
for tag, src in SRC:
    n = bad = 0
    dst = DEST / tag
    for f in src.rglob('*'):
        rel = f.relative_to(src)
        if any(p.lower() in SKIP_NAMES for p in rel.parts):
            man['skipped'].append({'tag': tag, 'rel': rel.as_posix(), 'reason': 'reserved_name'})
            continue
        if f.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True); continue
        if not f.is_file():
            continue
        try:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst / rel)
            man['files'].append({'tag': tag, 'rel': rel.as_posix(),
                                 'size': f.stat().st_size,
                                 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()})
            n += 1; total += f.stat().st_size
        except OSError as e:
            bad += 1
            man['skipped'].append({'tag': tag, 'rel': rel.as_posix(),
                                   'reason': f'{type(e).__name__}: {e}'})
    man['sources'].append({'tag': tag, 'src': str(src), 'files': n, 'failed': bad})
    print(f'{tag}: {n} files copied, {bad} failed', flush=True)
man['total_bytes'] = total
(DEST / 'MANIFEST.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
print('DEST =', DEST)
print('files =', len(man['files']), 'skipped =', len(man['skipped']), 'bytes =', total)
PY
```

**期望**（**2026-11-08 00:05 把这段原文原样跑了一遍**的实测输出，不是推算）：
```
vault: 1137 files copied, 0 failed
skills: 837 files copied, 0 failed     ← 含 41 个 .pyc，这是正常的
DEST = D:/repo\_tools\pika-迁移\_backup_20261108T000555
files = 1974 skipped = 1 bytes = 263285554
```
盘上复核（三核全过，实测）：
```
manifest files 1974 | skipped 1 | bytes 263285554
sources [('vault', 1137, 0), ('skills', 837, 0)]
actual files on disk (incl MANIFEST) 1975      ← 1974 + MANIFEST.json
actual bytes (excl MANIFEST) 263285554 | match: True
du -sh → 256M
```
（2026-11-04 那次是 `1943 文件 / 262305645 B`；差额 = 后来重新生成的 41 个 `.pyc`
+ `_observer-tools` 重建的 2 个文件。**文件数会变，`vault 1137 / skills 837` 这个结构不会变。**）
★ `skipped = 1` 恒成立：那条是 `skills/nul`（Windows 保留名），记进 `skipped` 而**不是** `failed`。

**失败怎么办**：
- `[WinError 87] 参数错误` ⇒ 你的 `SKIP_NAMES` 没生效，检查 `rel.parts` 里是不是 `nul`（§6.1）。
- `exist_ok=False` 抛 `FileExistsError` ⇒ 同一秒跑了两次，换个秒再跑；**不要**改成 `exist_ok=True`。
- `failed > 0` ⇒ **停**，不要往下走。

**回滚**：备份目录直接留着（实测 256 MB）。确认升级成功后可删旧的那份，
但**至少留最近一份**（§7.1）。

### 步骤 3／8：三方比对，出新清单

**目的**：把「zip 里有什么 / 盘上有什么 / 内容同不同」算成一张可审的表。
现有清单是 `_tools/pika-迁移/inventory/b3_fullhash.json`（3771 行，带双侧 sha256）。
**包换了就必须重算**；包没换可以直接用。

先确认清单还有效（跑一次全量 dry-run 的 verify 即可，45 秒）：

```bash
cd "D:/repo/engineering"
python -X utf8 tools/pika_migrate.py
```

**期望**（2026-11-07 实测，已装完的干净态）：
```
[① verify] 验证完成，用时 45.8s
  进删除清单 : 1 条 / 7.9 KB
  内容已相同 : 3697 条
  新版独有   : 281 条
  无映射根   : 22 条
  验证失败   : 73 条
[统计] 会删 1 / 验证失败 73 / 跳过已相同 3697 / 无映射根 22 / 待裁决 5
dry-run 结束：**没有删除、没有写入任何东西**。
```

**怎么读这组数**（详见 §4）：
- `会删 1` = 那条 `一致几乎处处有界…md`（zip 8118 / 盘 8117），是**留哪份的裁决题**，不是机器错。
- `验证失败 73` = 71 个 skill 文件 + 2 个 vault 文件，全部是「11-04 已经改成新版了，
  和事故前记录对不上」⇒ **这正是升级已完成的表现**，不是错。
- `新版独有 281` = `old_missing`，即盘上没有、包里有的文件（含 `compute-fleet-manager` 16 个）。

若包换了（sha256 变了），必须重算清单：

```bash
cd "D:/repo/engineering"
# 前置：先把新包解到 _extracted/（三个内层包 + vault 两层剥壳）
python -X utf8 - <<'PY'
import io, zipfile
from pathlib import Path
OUT = zipfile.ZipFile(r'D:/downloads/pika文件_Pro.zip')
DEST = Path(r'D:/repo/_tools/pika-迁移/_extracted')
DEST.mkdir(parents=True, exist_ok=True)
for member, out in [
    ('pika文件_Pro/笔记共享vault.zip', DEST/'笔记共享vault'/'__source.zip'),
    ('pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-<VER>.zip',
     DEST/'pika_math_learning_toolkit-<VER>.zip'),
    ('pika文件_Pro/pika资料共享/代码与数据/grid-covering-lab-source.zip',
     DEST/'grid-covering-lab-source.zip'),
]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(OUT.read(member))
    print('wrote', out, out.stat().st_size)
PY
```

（`<VER>` 换成新版本号。第二步重算 `b3_fullhash.json` 用的是
`_tools/pika-迁移/inventory/_scripts/p*.py` 那批一次性脚本，按 §8.1 处理 —— 那套脚本
没有参数化，换版本要改常量。）

**失败怎么办**：
- `验证失败` 数**暴涨**（比如从 73 变成 3771）⇒ 清单与现场全对不上，几乎一定是
  「`b3_fullhash.json` 的 `old_sha` 记的是别的时点」。**停**，先重算清单。
- `FileNotFoundError: b3_fullhash.json` ⇒ 清单丢了，必须重算。

**回滚**：本步只读，无需回滚。

### 步骤 4／8：分类 dry-run，逐类看

**目的**：全量一次看不完，按类看。六类：`library` / `tool` / `aitools` / `vault` / `skills` / `gridlab`。

```bash
cd "D:/repo/engineering"
for c in library tool aitools vault skills gridlab; do
  echo "########## $c ##########"
  python -X utf8 tools/pika_migrate.py --only "$c" 2>&1 | grep -E "进删除清单|内容已相同|新版独有|无映射根|验证失败|会删|待裁决"
done
```

**期望**（2026-11-07 实测）：
```
########## library ##########   进删除 0 / same 2288 / 独有 281 / 无根 22 / 失败 0
########## tool    ##########   进删除 0 / same 34   / 独有 281 / 无根 22 / 失败 0
########## aitools ##########   进删除 0 / same 0    / 独有 281 / 无根 22 / 失败 0
########## vault   ##########   进删除 1 / same 1076 / 失败 2   ← 两条裁决题
########## skills  ##########   进删除 0 / same 251  / 失败 71  ← 已升级完的表现
########## gridlab ##########   进删除 0 / same 48   / 失败 0   ← 完全对齐
```

★ `新版独有 281` 在每一类里都会出现 —— 因为 `old_missing` 条目没有类别归属，
它不参与 `--only` 过滤。**这不是 bug**，别去找它。

**失败怎么办**：
- 某类 `验证失败` 里有**没见过的路径** ⇒ 逐条看原因，按 §4.4 判「本机改过」还是「清单过时」。
- `待裁决` 数变了 ⇒ 跑 `--explain-arbitration` 看新的那条。

**回滚**：本步只读，无需回滚。

### 步骤 5／8：裁决与回填（**唯一需要人点头的一步**）

**目的**：机器只能告诉你「不一样」，不能替你决定「要哪份」。

```bash
cd "D:/repo/engineering"
python -X utf8 tools/pika_migrate.py --explain-arbitration
```

**期望**（2026-11-07 实测 5 条）：
```
1. [vault] 目录  D:/repo\知识库\.obsidian
   用户当前实际在用的 Obsidian 配置（字体 + CSS snippet + 10-30 的 workspace），新版 zip 里那份是旧快照
2. [vault] 目录  D:/repo\知识库\Codex Skills
   3 个 0 字节 SKILL.md 空壳之一：旧安装器留下的定位标记，删了 mpk 的 infer_vault_root 会变
3. [vault] 目录  D:/repo\知识库\pika文件_Pro\_observer-tools
   只在 D 盘有、新版没有：用户自建的观察器工具（4 文件 27 KB）
4. [vault] 8.2 KB  …\笔记共享vault\math\模长总和为1…md.bak-before-merge-20261104
   磁盘上有、新版包里没有
5. [vault] 9.8 KB  …\笔记共享vault\math\用概率计算含参数积分的极限.md
   磁盘上有、新版包里没有
```

**已定案的裁决（照抄，不要再议）**：

| # | 对象 | 决定 | 理由 |
|---|---|---|---|
| 1 | `知识库/.obsidian` | **保留外层，永不覆盖** | 铁律三；外层 11-05 还在写，内层是包内快照 |
| 2 | `知识库/Codex Skills` 空壳 | **保留空目录，不删** | 见 §6.16 —— 它是 mpk `infer_vault_root()` 的判据 |
| 3 | `_observer-tools/` | **保留**（现在 6 文件） | 包里没有 receiver，只有发送端；这是本机自建的唯一接收端 |
| 4 | `模长…md.bak-before-merge-20261104` | **保留** | 合并前的旧稿，8.2 KB，是我要留的底 |
| 5 | `D:/repo/知识库/pika文件_Pro/笔记共享vault/math/用概率计算含参数积分的极限.md` | **保留** | 与 zip 全部 math 笔记最高相似度 0.322 ⇒ 包内无对应版本，是本机独有作品 |

**回填动作**（配置侧，见 §5）：本步**只记录**要改什么，真正改在 §5.4。
本机现状：**唯一待定的是 `OBSIDIAN_LOCAL_KB_DB` 指死库**，改不改要人点头。

**失败怎么办**：
- 裁决项里出现**没见过的第 6 条** ⇒ 先查它是谁造的（`stat` 看 mtime、`git log` 看有没有跟踪），
  再决定。**不要默认「包里没有的就删」** —— 事故就是这么来的。

**回滚**：本步只读。

### 步骤 6／8：执行（先删后放）

**目的**：真动手。两个旗 + 一个清单，缺一不可。

```bash
cd "D:/repo/engineering"
# ① 先出一份可审的清单（dry-run 只在这个类别**非空**时才写 _plans/plan_<stamp>.json）
python -X utf8 tools/pika_migrate.py --only skills
# ② 人看 plan 里的每一条
python -X utf8 -c "
import json, glob, os
p = max(glob.glob(r'D:/repo/_tools/pika-迁移/_plans/plan_*.json'), key=os.path.getmtime)
d = json.load(open(p, encoding='utf-8'))
print('plan', p)
print('count(field)', d.get('count'), '| items', len(d.get('items', [])))
for it in d['items']:
    print(f\"  [{it['category']}] {it['size']:>9}  {it['old_abs']}\")
    print(f\"      原因：新版 {it['new_locator']} 存在且 sha256 相同（{it['new_sha'][:12]}…）\")
"
# ③ 真跑（三个参数全给）
python -X utf8 tools/pika_migrate.py --execute --i-understand-delete \
  --plan "D:/repo/_tools/pika-迁移/_plans/plan_<stamp>.json"
```

**期望**：`[删] <绝对路径>` 每条都带「原因：新版 … 存在且 sha256 相同（…）」；
写入用 `.pika-tmp` + `os.replace` 原子替换；exit 0。

★ **三个必知的边界**（源码实测）：

1. **清单为空时不写 plan 文件**（L1005 `if not args.execute and rep.manifest:`）。
   只打印 `[统计] 会删 0 …`，**没有「清单已写出」那一行**。
   「会删 0」= 已经是目标状态，**不是脚本坏了**；此时**不要**去 `--execute`。
2. plan 顶层**没有 `deletes` 键**，只有 `items`。实测 `plan_20261107_215441.json`
   顶层 = `['schema','created','knowledge_root','only','mode','count','bytes','items']`，
   `items[0]` = `['old_abs','new_locator','new_sha','old_sha','size','category','zip_path','origin']`。
   写成 `deletes` 的一律是猜的，`KeyError` 会当场暴露。
3. **`--execute --plan <file>` 不重新推导**该删谁（L961-972 打印
   `已从清单读入 N 条，跳过现场验证`）⇒ 清单一旦生成，**现场再变也拦不住**。
   所以上面第 ② 步的人工审阅是**唯一闸门**，别跳。

**失败怎么办**（退出码表）：

| 码 | 含义 | 处置 |
|---|---|---|
| 2 | 缺旗 / 清单不存在 / `--skip-backup` 与 `--execute` 同给 | 补齐参数，别用 `--skip-backup` |
| 3 | 备份核对不通过（一个文件都没删） | 看 §7.1，重备份 |
| 4 | 删除阶段中止（place 未执行） | 删除时复算 sha256 不符即 break —— 现场被改过，回到步骤 4 |
| 5 | 写入阶段有失败 | 看报错路径；`--only <类>` 重跑一次 |

**回滚**：见 §7.2（`restore_accident.py` 或直接从 `_backup_*/` 拷回）。

### 步骤 7／8：自检（**必须在清 pycache 之前**）

**目的**：证明装完还能跑。

```bash
# 7.1 七个包都齐、都能被 doctor 认出来（exit 0 才算过）
cd "C:/Users/example/.dsh/skills/manage-personal-knowledge/scripts"
python -X utf8 suite_doctor.py

# 7.2 七个包的术语表
cd "C:/Users/example/.dsh/skills"
for s in compute-fleet-manager manage-personal-knowledge math-coach \
         math-research-solve math-science-computation obsidian-vault-notes pdf-problem-search; do
  printf "%-28s " "$s"
  ( cd "$s/scripts" && python -X utf8 validate_terminology.py --skill-root "../" )
done

# 7.3 vault 侧
cd "C:/Users/example/.dsh/skills/obsidian-vault-notes/scripts"
python -X utf8 setup_local.py check
cd "C:/Users/example/.dsh/skills/manage-personal-knowledge/scripts"   # ← 换目录，不是 ../
python -X utf8 manage_kb.py status
```

★ **两个「看似能跑其实跑错」的写法**（2026-11-08 实测，都试过）：

| 写法 | 结果 | 正确写法 |
|---|---|---|
| `cd "$s"` 再 `C:/Users/example/.dsh/skills/obsidian-vault-notes/scripts/validate_terminology.py --skill-root "../"` | 7 个全 `ok:false` / `terminology_asset_missing`（`--skill-root "../"` 指到了整个 `skills/` 根，不是单个 skill） | **`cd "$s/scripts"`** 再 `--skill-root "../"` ⇒ 7 个全 `ok:true` |
| 在 `obsidian-vault-notes/scripts` 下跑 `C:/Users/example/.dsh/skills/manage-personal-knowledge/scripts/manage_kb.py` | `can't open file '…\obsidian-vault-notes\manage-personal-knowledge\scripts\manage_kb.py'`（`..` 只退一层） | **`cd` 到 `manage-personal-knowledge/scripts`** 再 `python manage_kb.py status` |

**期望**：
- `suite_doctor.py`：`"status": "installed"`、`"supported": true`（python 3.14.6）、
  7 个 skill 全 `true`、exit 0。
  `optional_capabilities`：`pdf_text_extraction available(pdftotext)`、`mathematica available_command`、
  `sagemath not_detected`、`primecount not_detected` —— **后两个 not_detected 是正常的**。
- `validate_terminology.py`：7 个全 `{"ok": true, "code": "terminology_valid"}`。
  ★ **`--skill-root "../"` 必填**，不给会报参数错（§6.8）。
- `setup_local.py check`：见 §2.7 那组数。
- `manage_kb.py status`：`healthy`、`docs 2422 / pages 59301 / coverage 96.28%`。

**pytest（可选，但要知道基线）**：各包有**既有红**，不是升级引入的。基线（2026-11-04 实测）：

| 包 | 本次 | 老版对照 |
|---|---|---|
| manage-personal-knowledge | 2 failed | 3 failed |
| obsidian-vault-notes | 7 failed + 2 subfailed | 9 + 2 |
| math-coach | 1 failed | 1 |
| math-research-solve | 2 failed | 19 |
| 其余 | 0 | 0 |

⇒ **红数不比基线多就不算回归**。要比就同时跑备份里的老版（`_backup_*/skills/<包>`）。

**失败怎么办**：
- `"status": "missing_skill_payload"` + exit 1 ⇒ 少装了包（§6.13）。
- `RuntimeError: Configured bundled index module is missing or does not match this install.`
  ⇒ `kb_root` 指到别处（§6.12）。
- 术语校验 `ok: false` ⇒ 该包文件不全，重跑步骤 6 的 `--only skills`。

**回滚**：此时还没清 pycache，回滚代价最小 —— 直接走 §7.2。

### 步骤 8／8：清 pycache + 终态复核 + 写报告

**★ 顺序铁律：清理必须是最后一次「跑代码」之后。** 跑任何 skill 脚本都会重新生成 `.pyc`。

```bash
# 8.1 清（先数，再删，删完再数）
cd "C:/Users/example/.dsh/skills"
echo "before: $(find . -type d -name __pycache__ | wc -l) dirs, $(find . -name '*.pyc' | wc -l) pyc"
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
echo "after:  $(find . -type d -name __pycache__ | wc -l) dirs, $(find . -name '*.pyc' | wc -l) pyc"

# 8.2 终态三方复核（skills 侧应 467/467 全同；vault 侧应 only_zip=0）
python -X utf8 - <<'PY'
import hashlib, io, zipfile
from pathlib import Path
OUT = zipfile.ZipFile(r'D:/downloads/pika文件_Pro.zip')
tk  = zipfile.ZipFile(io.BytesIO(OUT.read('pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip')))
vz  = zipfile.ZipFile(io.BytesIO(OUT.read('pika文件_Pro/笔记共享vault.zip')))
SK, VA = Path(r'C:/Users/example/.dsh/skills'), Path(r'D:/repo/知识库/pika文件_Pro/笔记共享vault')
def sha(b): return hashlib.sha256(b).hexdigest()
skip = lambda n: '__pycache__' in n or n.endswith('.pyc') or '.pytest_cache' in n
tot = [0]*5
for s in ['compute-fleet-manager','manage-personal-knowledge','math-coach','math-research-solve',
          'math-science-computation','obsidian-vault-notes','pdf-problem-search']:
    z = {n[len(f'payload/{s}/'):] for n in tk.namelist() if n.startswith(f'payload/{s}/') and not n.endswith('/') and not skip(n)}
    d = {p.relative_to(SK/s).as_posix() for p in (SK/s).rglob('*') if p.is_file() and not skip(p.as_posix())}
    same = sum(sha(tk.read(f'payload/{s}/{r}')) == sha((SK/s/r).read_bytes()) for r in z & d)
    diff = len(z & d) - same
    print(f'{s:<28}{len(z):>5}{len(d):>6}{same:>6}{diff:>6}{len(z-d):>8}{len(d-z):>9}')
    for i, v in enumerate([len(z), len(d), same, diff, len(z-d)]): tot[i] += v
print(f'{"TOTAL":<28}{tot[0]:>5}{tot[1]:>6}{tot[2]:>6}{tot[3]:>6}{tot[4]:>8}')
pre = '笔记共享vault/笔记共享vault/'
z = {n[len(pre):] for n in vz.namelist() if n.startswith(pre) and not n.endswith('/')}
d = {p.relative_to(VA).as_posix() for p in VA.rglob('*') if p.is_file()}
same = sum(sha(vz.read(pre+r)) == sha((VA/r).read_bytes()) for r in z & d)
print(f'[vault] zip={len(z)} local={len(d)} same={same} diff={len(z&d)-same} '
      f'only_zip={len(z-d)} only_local={len(d-z)}')
PY

# 8.3 外层包指纹没变（证明全程只读）
python -X utf8 -c "
import hashlib
h = hashlib.sha256()
with open(r'D:/downloads/pika文件_Pro.zip','rb') as f:
    for b in iter(lambda: f.read(1<<20), b''): h.update(b)
print(h.hexdigest())
"
```

**期望（2026-11-07 实测终态）**：
```
before: 6 dirs, 41 pyc     ← 若你刚从步骤 7 过来，这里一定不是 0
after:  0 dirs, 0 pyc

compute-fleet-manager          16    16    16     0       0        0
manage-personal-knowledge      57    57    57     0       0        0
math-coach                     97    97    97     0       0        0
math-research-solve           115   115   115     0       0        0
math-science-computation       59    59    59     0       0        0
obsidian-vault-notes           81    81    81     0       0        0
pdf-problem-search             42    42    42     0       0        0
TOTAL                         467   467   467     0       0        0
[vault] zip=1127 local=1129 same=1125 diff=2 only_zip=0 only_local=2

4a0783365a9f30df7a491c2ac9d978366c43859c618c1f47e0fd06dc6c785a07
```

**怎么读终态**：
- `TOTAL 467/467/467 diff 0 only 0` ⇒ skills 侧**完全对齐**。
- `[vault] only_zip=0` ⇒ **没有任何「包里有、盘上没有」的缺口**，回填是空操作。
- `diff=2` + `only_local=2` 是**两处有意保留**：`一致几乎处处有界…md`（留本机版，8117）
  与 `模长总和为1…md`（zip 主体 + 旧稿代码附录，14806）；`only_local` 是那条 `.bak` 与
  `D:/repo/知识库/pika文件_Pro/笔记共享vault/math/用概率计算含参数积分的极限.md`。**全都对。**

**失败怎么办**：
- `after` 不是 0 ⇒ 上一条命令里又跑了 Python，重跑 8.1。
- `TOTAL diff` 非 0 ⇒ 步骤 6 没写完，重跑 `--only skills`。
- vault `only_zip > 0` ⇒ 有包内文件没落盘，重跑 `--only vault`。
- 末尾 sha256 变了 ⇒ **有人写过外层包**，立刻查（本规程全程不该动它）。

**回滚**：见 §7。

### 写报告（步骤 8 的收尾）

把下面各项写进 `D:/repo/_tools/pika-迁移/_runs/<stamp>/after.md`：

1. 步骤 1 的 `before.txt` 与本次 `after` 读数（md 数 / env / git 头 / zip 指纹）。
2. 备份目录与三核读数（文件数 / 字节数 / MANIFEST 条数）。
3. 步骤 3–4 的五组统计（会删 / 失败 / 已相同 / 无根 / 待裁决）。
4. 步骤 5 的 5 条裁决与最终处置。
5. 步骤 7 的 4 个自检结论 + pytest 红数与基线对照。
6. 步骤 8 的终态表。
7. 本次仍是「不知道」的条目（照 §8 更新）。

---

## §4 比对口径（三方：zip payload / 已装 / vault）

### 4.1 三方各是什么

| 方 | 路径 | 规模（实测） |
|---|---|---|
| **zip payload** | `pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip` 内的 `payload/<skill>/` | 467 文件 / 7043846 B（7 个 skill） |
| **已装** | `C:/Users/example/.dsh/skills/<skill>/` | 467 文件（排 pycache 后） |
| **vault** | `D:/repo/知识库/pika文件_Pro/笔记共享vault/` | 1129 文件（含 2 个本机独有） |
| **（第四方）外层散文件** | `pika文件_Pro/pika资料共享/{开源资源,pika的presentations,代码与数据}/` | 2408 文件 |

★ `payload/` 之外的 **21 个文件（146325 B）不属于任何 skill，不要往 skills 目录装**：
`package-manifest.json` / `install.py` / `checksums.sha256` / `SOURCE_VERSIONS.json` /
RELEASE_NOTES.md / START_HERE.md / PORTABLE_ADAPTATIONS.json / PRIVACY_REPORT.md /
TEST_MATRIX.md / AGENTS.md / CLAUDE.md / GEMINI.md / AGENT_INSTALL.md /
INSTALL_PROMPT.md / INSTALL_TEST_RECEIPT.json / INSTALL_WINDOWS.cmd / install.sh + tests/ 4 个。

### 4.2 五类判定（唯一口径）

对每一条（`origin` + `zip_path` 唯一键），逐字节 sha256 比完只有五种结果：

| 判定 | 条件 | 动作 |
|---|---|---|
| **SAME** | 双侧 sha256 相同 | 跳过。**不删不写** |
| **正常升级** | 双侧都有、sha 不同、且**盘上 sha == 勘察记录 `old_sha`** | 先删后放（迁移器的 `会删`） |
| **本机独有（被改过）** | 双侧都有、sha 不同、且**盘上 sha ≠ `old_sha`** | **不动**，进「待裁决」或「验证失败」 |
| **包新增** | 包里有序、盘上没有 | 直接写（`old_missing`，归入「新版独有」） |
| **盘上独有** | 盘上有、包里没有 | **保留**（`only_local`），除非能证明是垃圾 |

**判据只有一条**：`现场 sha256 vs 勘察记录 old_sha`。
相等 = 我没动过 ⇒ 可以升级；不等 = 我动过 ⇒ **永远不覆盖**。

### 4.3 三种「看起来像错、其实是对」的读数

| 读数 | 为什么对 |
|---|---|
| `验证失败 73`（71 skills + 2 vault） | 这 73 条已经被 2026-11-04 的升级写成新版了，和「事故前」记录当然不等 |
| `新版独有 281` 在每一类里都出现 | `old_missing` 条目没有类别归属，不参与 `--only` 过滤 |
| `会删 1` 那条是 vault 笔记 | 它是「留哪份」的裁决题，机器只负责报「包里有更新版」 |

### 4.4 怎么判「本机补丁」（最容易判错的地方）

判据顺序，**不许跳步**：

1. **包里的版本已经是「修好后」的吗？** 看 PORTABLE_ADAPTATIONS.json：
   `source_versions_unchanged: true`、`installed_sources_modified: false`、
   `changes[]` 28 条（每条 `path` + `before_sha256` + `after_sha256`）。
   ⇒ **这 28 条是打包方做的，不是我的补丁，不要「恢复」它们。**
2. **本机这行在坏环境下真的更好吗？** 必须在**两个引擎**上各跑一次
   （Windows PowerShell 5.1 与 pwsh 7）。只在 pwsh 7 上过不算数。
3. **有没有调用方？** 全仓 grep 一次。没有调用方的「补丁」＝待清理的死代码。

**已结案的唯一一例**（详见 §6.5）：`test_dsh_rational_identity.ps1:19` 的
`-AsHashtable` **不是补丁，是坏行**。PS 5.1 直接抛 `NamedParameterNotFound`；
zip 原版删掉它之后，PS 5.1 上 `PASS 10 generic cases`。**结论：不保留，用 zip 原版。**

### 4.5 「包已修好」的四个可验证标志

拿到新包时，先花 2 分钟确认这四件事，能省掉后面一堆疑问：

1. `suite_doctor.py` 的 `required` 是 **7 项**（不只是 4 项）。
2. `obsidian-vault-notes/scripts/_common.py` 的 `resolve_kb_root()` 是 **4 候选**
   （`env → kb_root → BUNDLED → LEGACY`），没有 `VAULT_KB_ROOT`。
3. `pdf-problem-search/scripts/pdf_problem_search/paths.py` 有 `infer_knowledge_root()`
   （读 `knowledge_root` 键），`resolve_project_root()` 有 `sibling_project` 候选。
4. `math-coach` 的 `test_dsh_rational_identity.ps1` 里**没有** `-AsHashtable`。

四条全中 ⇒ 这是「已修好」的包，直接按 §3 走。

---

## §5 个性化路径回填

### 5.1 一句话原则

> **路径的真相在环境变量，不在文件里。skill 代码里不写本机路径。**

实测支撑：全树 grep `jelly_ware` → **0 命中**；`D:/docs` → **0 命中**。
真代码级只剩两条与 pika 无关的系统工具默认位（新旧完全一致）：
`manage-personal-knowledge/scripts/manage_personal_knowledge/ocr.py:20`
`DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")`
与 `…/text.py:227,232` `Path(os.environ.get("ProgramFiles", r"C:\Program Files"))`。

⇒ **不存在「旧版写死路径、新版要补回」的情况。所谓「回填」其实是在配环境，
不是在改代码。** 这一条把 90% 的「回填」工作量直接消掉。

### 5.2 解析链（必须记住顺序）

`obsidian-vault-notes/scripts/_common.py`（126 行，2.1.7 现状；**下面是带行号的摘录，不是可运行代码**）：

```text
13: BUNDLED_KB_ROOT = SCRIPTS_ROOT / "obsidian_local_kb"
89: LEGACY_KB_ROOT  = Path.home() / "Documents" / "obsidian_local_kb"

92: def resolve_kb_root() -> Path:
93:     env_root = os.environ.get("OBSIDIAN_LOCAL_KB_ROOT")
94:     return resolve_existing_path([
95:         Path(env_root) if env_root else None,
96:         configured_path(LOCAL_CONFIG, "kb_root"),
97:         BUNDLED_KB_ROOT,
98:         LEGACY_KB_ROOT,
99:     ])

104: def resolve_note_db_path(kb_root: Path) -> Path:
105:     env_db = os.environ.get("OBSIDIAN_LOCAL_KB_DB")
106:     state_default = platform_state_root() / SKILL_NAME / "vault.sqlite3"
107:     return resolve_existing_path([
108:         Path(env_db) if env_db else None,
109:         configured_path(LOCAL_CONFIG, "db_path"),
110:         kb_root / "data" / "vault.sqlite3",
111:         state_default,
112:         LEGACY_KB_ROOT / "data" / "vault.sqlite3",
113:     ])
```

`resolve_existing_path()` 取**第一个存在的**。⇒ 只要 env 那条存在，后面全被跳过。

★ 两条易错：
- `resolve_note_db_path(kb_root)` **必须传参**，不传抛
  `TypeError: resolve_note_db_path() missing 1 required positional argument: 'kb_root'`。
- 2.1.7 已删除 `VAULT_KB_ROOT`（从 5 候选变 4 候选）。旧文档里提到它有 5 个候选，
  那是 2.1.3 的事。

### 5.3 复核命令（改任何东西之前先跑一次）

```bash
cd "C:/Users/example/.dsh/skills/obsidian-vault-notes/scripts"
python -X utf8 - <<'PY'
import os, sqlite3, sys
sys.path.insert(0, '.')
import _common as c
print('env OBSIDIAN_LOCAL_KB_ROOT =', os.environ.get('OBSIDIAN_LOCAL_KB_ROOT'))
print('env OBSIDIAN_LOCAL_KB_DB   =', os.environ.get('OBSIDIAN_LOCAL_KB_DB'))
print('LOCAL_CONFIG        =', c.LOCAL_CONFIG)
print('BUNDLED_KB_ROOT     =', c.BUNDLED_KB_ROOT)
print('LEGACY_KB_ROOT      =', c.LEGACY_KB_ROOT)
kb = c.resolve_kb_root()
print('resolve_kb_root()   =', kb, '| exists', kb.exists())
db = c.resolve_note_db_path(kb)
print('resolve_note_db_path=', db, '| size', os.path.getsize(db) if os.path.isfile(db) else '-')
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
for k, v in con.execute('select key,value from index_meta').fetchall():
    print('   index_meta', k, '=', v)
print('   sections', con.execute('select count(*) from sections').fetchone()[0],
      '| fts', con.execute('select count(*) from section_fts').fetchone()[0])
PY
```

**2026-11-07 实测输出**：
```
env OBSIDIAN_LOCAL_KB_ROOT = C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb
env OBSIDIAN_LOCAL_KB_DB   = C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3
LOCAL_CONFIG        = {'schema_version': 1, 'vault_root': 'D:/repo\\知识库',
                       'kb_root': 'C:/Users/example\\.dsh\\skills\\obsidian-vault-notes\\scripts\\obsidian_local_kb',
                       'db_path': 'C:/Users/example\\AppData\\Local\\obsidian-vault-notes\\vault.sqlite3'}
BUNDLED_KB_ROOT     = C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb
LEGACY_KB_ROOT      = C:/Users/example\Documents\obsidian_local_kb
resolve_kb_root()   = C:/Users/example\.dsh\skills\obsidian-vault-notes\scripts\obsidian_local_kb | exists True
resolve_note_db_path= C:/Users/example\AppData\Local\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3 | size 23764992
   index_meta schema_version = 3
   index_meta indexed_at_utc = 2026-09-13T13:21:44Z
   index_meta note_count = 685
   sections 3365 | fts 4354        ← 两个数不一致 = 旧格式残留
```

### 5.4 唯一的待定项：`OBSIDIAN_LOCAL_KB_DB` 指着一个废弃库

| | env 指的那颗 | 配置 A `db_path` 指的那颗 |
|---|---|---|
| 路径 | `…\pika_math_learning_toolkit\obsidian-vault-notes\vault.sqlite3` | `…\obsidian-vault-notes\vault.sqlite3` |
| 大小 | 23764992 B | 23449600 B |
| `indexed_at_utc` | **2026-09-13T13:21:44Z** | **2026-10-03T13:54:29Z** |
| `note_count` | 685 | 683 |
| `sections` / `section_fts` | 3365 / **4354（不一致）** | 3129 / 3129 ✅ |

`resolve_note_db_path()` 里 env 排第一且存在 ⇒ **实际用的是 09-13 那颗废弃库**，
`check` 报的 `indexed_at_utc 2026-10-03` 是**配置里的那张纸**，不是运行时真相。

**两种改法（方向相反，都要人点头，选一个并写进报告）**：

- **甲：把 env 指向活库**（改动最小）
  ```bash
  powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable(
    'OBSIDIAN_LOCAL_KB_DB',
    'C:/Users/example\AppData\Local\obsidian-vault-notes\vault.sqlite3','User')"
  ```
  改完**必须新开 shell / 新开会话**才生效（User 域变量不会被已运行进程继承）。

- **乙：删掉三个用户级 env，让技能回归自定位**（更彻底，风险更高）
  三个 env 是 2026-10 手工设的，不是官方安装器设的。删掉后走
  `BUNDLED_KB_ROOT` 自定位 + `%APPDATA%\obsidian-vault-notes\config.json`。
  **代价**：`setup_local.py check` 里有 `kb_root != KB_ROOT.resolve()` 的硬比较；
  一旦有第二个宿主装过 pika，两边会互相打架。
  风险等级：中。**不建议在升级当天做，单独开一次。**

**没说清楚的一律按「甲」记成待办，不擅自改。**

### 5.5 三个 JSON 的现状（不要瞎猜哪份生效）

| 路径 | 大小 | mtime | 关键字段 | 生效？ |
|---|---|---|---|---|
| `%APPDATA%\pika_math_learning_toolkit\obsidian-vault-notes.json` | **260** | 2026-10-03 21:54 | `db_path` = 活库 | ✅ **生效**（被 `OBSIDIAN_VAULT_NOTES_CONFIG` 指定） |
| `%APPDATA%\obsidian-vault-notes\config.json` | **288** | 2026-11-01 09:39 | `kb_root` 已修好（不再指 Hermes）；`db_path` = 死库 | ❌ 被 env 压过 |
| 同名 `.bak-20261024-102212` | 313 | 2026-10-24 | `kb_root` 指 `D:\Hermes Agent CN Desktop\…`（已不存在） | ❌ 备份 |
| 同名 `.bak-20261101T093941` | 313 | 2026-09-12 | 同上（内容逐字节相同） | ❌ 备份 |
| `%APPDATA%\manage-personal-knowledge\obsidian-vault-notes.json` | 313 | 2026-09-12 18:54 | `kb_root` 指 Hermes 死路径 | ❌ mpk companion |
| `%APPDATA%\manage-personal-knowledge\config.json` | 474 | 2026-10-24 10:24 | `knowledge_root: D:/repo`、`knowledge_root_id: KBROOT-442OME7QWTER5T5W7OO7RGNPB4`、`schema_version: 2` | ✅ **生效**（mpk 与 pdf 读它） |
| `%APPDATA%\pika_math_learning_toolkit\config.json` | 266 | 2026-09-12 17:48 | schema **v1** 旧副本，无 `knowledge_root_id` / `registry` | ❌ 孤儿 |

★ **不要**去「统一」这 7 份。第 2 行那份 288 B 的已经被 2026-11-01 手工修好过
（旧文档说它 313 B 且指死路径，那是过时读数）；第 6 行那三处
（`config.json` / `D:/repo/.mpk/root.json` / `D:/repo/.mpk/resources.jsonl`）的
`knowledge_root_id` **必须一致**，改一个就断。

### 5.6 pdf-problem-search 的路径链（2.1.7 换了来源，别按旧文档改）

2.1.7 新增 `infer_knowledge_root()`：`PERSONAL_KNOWLEDGE_ROOT` →
`MPK_CONFIG_PATH` → `%APPDATA%\manage-personal-knowledge\config.json` 的
**`knowledge_root`** 键。`resolve_project_root()` 候选顺序：
env `OBSIDIAN_LOCAL_KB_ROOT` → `pdf_search_project` → `knowledge_project` →
**`sibling_project`**（`<skills>/obsidian-vault-notes/scripts/obsidian_local_kb`，
**本机实际走这条**）→ legacy。

**实测**：`infer_knowledge_root()` = `D:/repo` ✅；
`infer_vault_root()` 新旧都返回 `None`（本机没有 `Obsidian Vault`+`Codex Skills` 那个形状）。
★ **不要**为 pdf 去设 `OBSIDIAN_VAULT_ROOT` —— 新版不认它。

---

## §6 已知坑（每条带实测证据与报错原文）

### 6.1 `skills/nul` 让 `copytree` 与 `copy2` 双双重炸

**证据**（2026-11-07 复现）：
```
copytree FAILED: Error | [('C:/Users/example/.dsh/skills\\nul',
  'C:/Users/example\\AppData\\Local\\Temp\\nulprobe_xxx\\skills\\nul', '[WinError 87] 参数错误。')]
copy2 FAILED: OSError | [WinError 87] 参数错误。
isfile False | isdir False | exists True
stat ok size= 0
relpath ValueError: path is on mount '\\\\.\\nul', start on 'C:'
```
**性质**：`C:/Users/example/.dsh/skills/nul` 是 Windows 保留设备名（2026-10-20 创建，0 B）。
`os.path.isfile`/`isdir` **都是 False**，但 `os.stat` 成功、`os.path.exists` 为 True。
**处置**：备份脚本按 `SKIP_NAMES = {'nul','con','prn','aux','com1'..,'lpt9'}` 跳过；
**不要删它**（删不掉，`del` 也会撞设备名）。

### 6.2 长路径只剩 21 字符余量

**证据**（实测）：
```
外层 zip 最长成员名            194 字符
vault 剥两层后最长相对路径     237 字符
  …/math/图片_math/DALL·E 2024-03-14 17.01.55 - Create an image that adds an element of a math genius to…
vault 目标前缀 D:/repo\知识库\pika文件_Pro\笔记共享vault\  = 42 字符
⇒ 最长绝对路径 239 字符（< 260 MAX_PATH，本机不触发）
Library\开源资源\ 最长 199；skills 前缀 26
```
**风险**：现在安全，但**余量只有 21 字符**。若把仓库根换到更深的位置（比如
`D:/docs\xxx\yyy\jelly_ware`），立刻越界，Windows 会抛 `[WinError 3] 系统找不到指定的路径`
或 `[Errno 36] File name too long`。
**处置**：换根前先算一遍最长路径；必须换就开 `LongPathsEnabled` 或用 `\\?\` 前缀。

### 6.3 vault 包是「两层套娃」，`_extracted` 里那份是三层（历史产物）

**证据**：`pika文件_Pro/笔记共享vault.zip` 的条目名形如
`笔记共享vault/笔记共享vault/<真实内容>`；深度分布 `{3:571, 4:473, 5:69, 6:6, 7:8}`。
剥两层的判据 = `n.split('/')[2:]`。
而 `_tools/pika-迁移/_extracted/笔记共享vault/笔记共享vault/笔记共享vault/` 是**三层**，
是早期一次性脚本的产物。
**坑**：照着 `_extracted` 的层数写代码，会把内容写到
`…/笔记共享vault/笔记共享vault/` 下面去，vault 里凭空多一层空壳目录（历史上真发生过，
后来手工删了）。**以 zip 条目数为准，不以 `_extracted` 为准。**

### 6.4 外层条目名必须带 `pika文件_Pro/` 前缀

**证据**：`zipfile.ZipFile.read('笔记共享vault.zip')` 抛
```
KeyError: "There is no item named '笔记共享vault.zip' in the archive"
```
必须写 `read('pika文件_Pro/笔记共享vault.zip')`。
三个内层包的**准确键名**：
```
pika文件_Pro/笔记共享vault.zip
pika文件_Pro/pika资料共享/AI工具/pika_math_learning_toolkit-2.1.7.zip
pika文件_Pro/pika资料共享/代码与数据/grid-covering-lab-source.zip
```

### 6.5 `-AsHashtable` 那条「补丁」是坏行，不是补丁（已结案）

**证据**（两向实测，2026-11-04；2026-11-07 复验当前文件已与 zip 一致）：
```
zip    : 1471 B sha 8fd2e07c63fd50f8
已装   : 1471 B sha 8fd2e07c63fd50f8   identical = True
zip  contains AsHashtable: False
inst contains AsHashtable: False
zip CRLF=0  inst CRLF=0
第 19 行两边都是：$result = & $checker -Json $payload | ConvertFrom-Json
```
**历史报错原文**（带 `-AsHashtable` 的旧版在 PS 5.1 上）：
```
ConvertFrom-Json : 找不到与参数名称“AsHashtable”匹配的参数。
所在位置 C:/Users/example\.dsh\skills\math-coach\scripts\tests\test_dsh_rational_identity.ps1:19 字符: 56
FullyQualifiedErrorId : NamedParameterNotFound,Microsoft.PowerShell.Commands.ConvertFromJsonCommand
```
**根因**：Windows PowerShell **5.1.26100.8655** 的 `ConvertFrom-Json` **没有**
`-AsHashtable`（那是 7.x 才有的）；`pwsh 7.6.7` 有。带该参数时 PS 5.1 直接挂；
zip 原版（不带）在 PS 5.1 上 `PASS 10 generic cases`。
**结论**：那行是上一版遗留的**坏行**，2.1.7 恰好删掉。**不保留、不「恢复」。**
处置动作：`live.write_bytes(zip_bytes)`（1484 B → 1471 B）。
**教训**：本机补丁必须先证明「在坏环境下真的更好」，否则它可能只是「在好环境下不报错」。

### 6.6 跑自检会重新生成 `.pyc` —— 清理必须放最后

**证据**：2026-11-04 清完 18 个 `.pyc` 后，13:09 那次自检又生成 18 个；
2026-11-05 21:55–22:38 期间跑脚本，现在盘上是 **6 个 `__pycache__` 目录 / 41 个 `.pyc`**。
**处置**：`find . -type d -name __pycache__ -prune -exec rm -rf {} +` 只能是
**最后一次跑 Python 之后**的动作（§3 步骤 8）。
**另一条**：官方 `install.py` 的 `python_environment()` 里特意设了
`PYTHONDONTWRITEBYTECODE=1` ⇒ **技能目录里本来就不该有 `.pyc`**。有就是被绕过官方入口跑出来的。

**现场复现（2026-11-08 01:3x，写这份规程时自己踩的）**：只跑了 §3 步骤 7.2 那一轮
`validate_terminology.py`（7 个包各一次），`__pycache__` 从 **6 → 8 个目录**、
`.pyc` 从 **41 → 43 个**，新增的正是：

```
compute-fleet-manager/scripts/__pycache__/skill_dev_public_output.cpython-314.pyc
math-science-computation/scripts/__pycache__/computation_output.cpython-314.pyc
```

⇒ **连「只读的校验脚本」都会写盘**。这就是为什么步骤 8 的清必须排在步骤 7 之后，
而不是「跑完就清」。已把那 2 个删掉、并把因此变空的两个目录 `rmdir` 掉（回到 6/41）。

### 6.7 备份不等于「所有东西都能还原」

**证据**：2026-11-04 的备份 `_backup_20261104T112422`（1943 文件）里，
3 个 0 字节 SKILL.md 只命中 1 个 —— 因为另外两个在备份**之后**才被删。
**结论**：删任何文件前，先确认「这东西在备份里」。删完再想还原，只剩两条路：`git show HEAD:<path>`
（**仅限被跟踪的文件**）或回收站。
★ **「不在 `.gitignore` 里」不等于「在版本库里」** —— 这两件事完全不同，见 §6.9 的实测。

### 6.8 `validate_terminology.py` 的 `--skill-root` 必填，且**必须从 `scripts/` 里跑**

**证据 1（缺参数）**：不给 `--skill-root` 报
`error: the following arguments are required: --skill-root`。

**证据 2（`--skill-root` 的相对基准是「当前工作目录」）**：`--skill-root "../"` 是相对**当前目录**解析的，
所以从哪一层跑决定了它指向哪。2026-11-08 两向实测（同一批 7 个包，只改 `cd` 深度）：

```
# ❌ cd "$s"  → --skill-root "../" 指到整个 skills/ 根
compute-fleet-manager      {"ok": false, "code": "terminology_asset_missing", ...}
manage-personal-knowledge  {"ok": false, "status": "error", "code": "operation_failed", ...}
math-coach                 {"ok": false, "code": "terminology_asset_missing", "message": "Missing SKILL.md"}
math-research-solve        {"ok":false,"status":"blocked","code":"terminology_contract_invalid", ...}
math-science-computation   {"ok":false,"code":"terminology_asset_missing", ...}
obsidian-vault-notes       {"ok": false, "code": "terminology_asset_missing", "message": "Missing SKILL.md"}
pdf-problem-search         {"ok": false, "code": "terminology_asset_missing", "message": "Missing SKILL.md"}

# ✅ cd "$s/scripts" → --skill-root "../" 正好是单个 skill 根
compute-fleet-manager      {"ok": true, "code": "terminology_valid", "term_count": 3}
manage-personal-knowledge  {"ok": true, "code": "terminology_valid", "term_count": 5}
math-coach                 {"ok": true, "code": "terminology_valid", "term_count": 4}
math-research-solve        {"ok":true,"code":"terminology_valid","status":"terminology_valid",
                            "version":"v3.2.8","term_count":45,"documented_command_count":24,
                            "registry_sha256":"351ca4043e39cae2d1c4f99e17b26f4fb5c2bf40a8bf1230f770a758bda495eb"}
math-science-computation   {"ok":true,"code":"terminology_valid","term_count":9}
obsidian-vault-notes       {"ok": true, "code": "terminology_valid", "term_count": 3}
pdf-problem-search         {"ok": true, "code": "terminology_valid", "term_count": 2}
```

★ **这个坑最毒的地方**：错的那版**不报「路径不对」**，而是报 `Missing SKILL.md` /
`terminology_asset_missing` —— 看着像「文件被升级弄丢了」，实际是 cwd 差一层。
**看到成片 `terminology_asset_missing` 先检查 `cd` 深度，别急着重装。**

**正确用法**：
```bash
cd "C:/Users/example/.dsh/skills/<skill>/scripts"     # ← 必须进 scripts/
python -X utf8 validate_terminology.py --skill-root "../"
```
`term_count` 实测：3 / 5 / 4 / 45 / 9 / 3 / 2（按上面顺序）。

### 6.9 「只读探针」漏打桩一个写盘阶段 = 355 个文件被写

**事故原文**（2026-10-31 19:53）：验证 `--execute --plan` 分支时，探针只打桩了
`delete()` 与 `backup()`，**漏了 `place()`**，于是 place 以 `dry_run=False` 真跑，
写入 **355 个文件（74 覆盖 + 281 新建）**。删除数 0（delete 被强制 dry_run）。
影响：skills 216 / library 87 / vault 51 / aitools 1。
净损失：**1 个文件** —— `知识库/pika文件_Pro/笔记共享vault/.obsidian/workspace.json`
（7697 B）。**它为什么没副本（2026-11-07 逐条实测，纠正旧文档的说法）**：

```
$ git check-ignore -v "知识库/pika文件_Pro/笔记共享vault/.obsidian/workspace.json"
  → NOT ignored          ← 它不在任何 .gitignore 规则里
$ git ls-files "知识库/pika文件_Pro/笔记共享vault/.obsidian"  | wc -l
  → 0                    ← 整棵内层 .obsidian 从没被 git add 过
```

⇒ 旧文档（`复盘/pika迁移-回填方案.md` §7）说它「被 `.gitignore:21` 忽略」是**错的**：
`.gitignore:21` 那条是 `知识库/.obsidian/workspace.json`（**外层**，另一棵树）。
内层这份没副本的真实原因是**整目录 untracked**。而当时备份也还没做 —— 两件事叠加。

**事后**：`restore_accident.py` 还原 73 条（71 来自 2.1.4 zip `payload/`、2 来自 git HEAD）；
剩下那 1 条后来从回收站救回（7697 B / sha `c3b4564498a3`）。
**教训**：① 只读探针若要驱动真实 `main()`，必须把**所有**写盘阶段一起打桩，
或者干脆不调 `main()`、只测纯函数；② **真相在 `git ls-files`，不在 `.gitignore`** ——
「没被忽略」和「被跟踪」是两回事，判断「这份有没有副本」必须查前者。

### 6.10 用 2.1.4 的 zip 当「旧版真相」，不要用磁盘

**原因**：2026-10-31 事故把 71 个 skill 文件写成了新版；磁盘已经不是旧版了。
**权威旧版只有一个**：`知识库/pika文件_Pro/AI工具/pika_math_learning_toolkit-2.1.4.zip`
（1367591 B，sha `7ad8f0ee86ea…`）。`restore_accident.py` 正是从它取 `payload/`，
实测 71/71 sha256 与记录相符。

### 6.11 `.obsidian` 不能当 knowledge-root

**历史 bug**：知识库根的子孙里含 `.obsidian` 时，library 候选会被剪成 0；
当年的修法是把 `D:/docs\知识库\Library` 物理搬到 `D:/docs\Library`。
**现状**：`D:/repo` 下共 **5 个** `.obsidian`：
`知识库/.obsidian`、`知识库/pika文件_Pro/笔记共享vault/.obsidian`、
`研究项目/工作材料/_备份_含备注版_20260916/.obsidian`、`研究项目/工作材料/_纯净版/.obsidian`、
`课程与学习/my_python project/.obsidian`。
⇒ 只有 `知识库/.obsidian` 是「真在用」的那个；**别的都别碰**。

### 6.12 `setup_local.py check` 的 `kb_root != KB_ROOT` 是硬比较

**原文**（`setup_local.py:138`）：
```python
if kb_root != KB_ROOT.resolve() or not (kb_root / "obsidian_local_kb" / "__main__.py").is_file():
    raise RuntimeError("Configured bundled index module is missing or does not match this install.")
```
`KB_ROOT` 是**当前这个文件自己**的 `scripts/obsidian_local_kb`。
⇒ 装过两份 pika（历史上有 DSH 一份 + Hermes 一份）时，env 只能指一份，
另一份的 `check` 必失败。**这不是坏了，是设计如此**。
**处置**：DSH 是唯一宿主之后，env 指 DSH 这份即正确；不要去「同时满足两份」。

### 6.13 少装第 7 个 skill ⇒ `suite_doctor` exit 1

**原文**：`suite_doctor.py` 的 `required` 从 4 项扩到 **7 项**
（新增 `math-coach`(L27)、`math-research-solve`(L28)、`compute-fleet-manager`(L29)）。
缺任何一个 ⇒ `"status": "missing_skill_payload"`、**exit 1**。
**处置**：`compute-fleet-manager` 是 2.1.7 新增的第 7 个（16 文件 / 135666 B）。
`package-manifest.json` 的 `transaction = all-payloads` 要求 7 个一起换，
只装 6 个违背包自己的事务约定。**必须装齐 7 个。**

### 6.14 官方 `install.py` 不给 `--target-root` 会装错地方

**原文**（`install.py:221-229`）：不给 `--target-root` 时落
`os.environ.get("CODEX_HOME", ~/.codex)/"skills"`。本机 `CODEX_HOME` 未设
⇒ 会装到 `C:/Users/example\.codex\skills`，**DSH 根本看不到**。
**正确**：
```bash
python -X utf8 install.py --target-root "C:/Users/example/.dsh/skills" --dry-run
```
（先 `--dry-run` 看预览，再去掉它。）
★ 另注：`_tools/pika-迁移/_已执行/apply_skills.py` 里 `DEST` 指的是
`D:\Hermes Agent CN Desktop\data\hermes-home\skills` —— **那个宿主已下线，不要复用该脚本**。

### 6.15 「新版」不是「旧版超集」：6 个文件新版反而更小

**证据**（附录 A 全表口径）：74 个 DIFF 里至少 6 个新版更小 ——
`manage-personal-knowledge/scripts/suite_doctor.py` 2703→2534、
`obsidian-vault-notes/scripts/_common.py` 4093←4189、
`pdf-problem-search/scripts/pdf_problem_search/paths.py` 8598←7456、
`math-coach/scripts/tests/test_dsh_rational_identity.ps1` 1471←1483、
`migration_check.py` 10208←10209、`mrs_metrics.py` 11230→1650。
**结论**：**不能**假设「旧的 ⊂ 新的」，也**不能**用「新版更大所以更好」当判据。
只认 sha256 与行为实测。

### 6.16 `知识库/Codex Skills` 与 `pika文件_Pro/Codex Skills` 是两个空壳，不能删

**现状**：两个目录都在，都是**空的**（0 文件）；3 个 0 字节的 SKILL.md 已于 2026-11-04 删除。
**为什么不能删**：`_common.py` 里 `INFERRED_VAULT_ROOT` 的判据是
`(parent / "Codex Skills").exists()` —— 删了它，mpk 的 `infer_vault_root()` 结果会变。
**处置**：**保留空目录**。迁移器的待裁决第 2 条描述「3 个 0 字节 SKILL.md」已过时，
但**结论（保留）仍然对**。

### 6.17 回收站里那份「原件」不许删

**证据**：`D:/$Recycle.Bin/S-1-5-21-2275053455-3505615624-493918824-1001/$IFO3P23`
（70 B，2026-10-30 23:36 本地时间），`$RFO3P23/` 顶层只有 `pika文件_Pro`。
原始路径 `D:/downloads\pika文件_Pro (2)`，1460747606 B / 3531 文件。
已验证：`pika资料共享/` 2408 文件里 2407 个在 zip 内有对应、CRC32 **2407/2407 一致**；
与 `Library` 的 sha256 **2373/2373 identical**。
**结论**：内容可还原，但**删不可逆**，且 D: 还有 83 GB 可用。**留着。**需要取用时只读 `$RFO3P23`，不要清空回收站。

### 6.18 三个 skill 是「停用」不是「卸载」

**证据**：`C:/Users/example/.dsh/skills-manager/state.json`（1663 B）的
`disabledSkills.dsh` 里有 `math-coach`、`math-research-solve`、`math-science-computation`
（日志 `dsh-skills-manager.log` 有 `policy-disable` 2026-10-24T14:15:42/44/47Z）。
**含义**：文件在，但会话里不加载。**升级照常换文件**，换完停用标记照旧生效。
想启用要改 `state.json`（那是另一个决定，不在本规程里）。

### 6.19 「没被 `.gitignore` 忽略」≠「在版本库里」

**证据**（2026-11-07 逐条实测）：

```
知识库/pika文件_Pro/笔记共享vault/.obsidian/workspace.json
  git check-ignore -v  → 无声（NOT ignored）
  git ls-files         → 0 条（untracked）
知识库/.obsidian/workspace.json
  git check-ignore -v  → .gitignore:21:知识库/.obsidian/workspace.json   ← 这才是第 21 行
  git ls-files         → 0 条
知识库/.obsidian/app.json … graph.json（共 7 个）
  git ls-files         → 7 条（tracked）
```

**坑**：`git check-ignore` 对「untracked 且没被忽略」的路径**不输出任何东西**，
很容易被当成「它在库里」。旧文档就是据此把 2026-10-31 丢的那个 `workspace.json`
说成「被 `.gitignore:21` 忽略」—— 实际第 21 行管的是**外层**另一棵树，
内层那份是**整目录 untracked**。
**处置**：判「能不能从 git 救」只用
`git ls-files --error-unmatch "<path>"`；判「为什么没进 git」才用 `check-ignore`。

---

## §7 回滚与应急

### 7.1 备份在哪、怎么核

| 位置 | 内容 | 实测体积 |
|---|---|---|
| `_tools/pika-迁移/_backup_<stamp>/` | `vault/`（= `知识库/pika文件_Pro` 全量）+ `skills/`（= 整个 `.dsh/skills`）+ `MANIFEST.json`（逐文件 sha256） | 最近一份 `_backup_20261108T000555`：**256 MB / 1974 文件 / 263285554 B**（另 1 条 `nul` 记进 `skipped`） |
| `_tools/pika-迁移/_backup_20261104T112516/` | 11-04 那次（**1944 文件 / 262713439 B**，含 `MANIFEST.json` 407794 B） | 255 MB |
| `_tools/pika-迁移/_backup_20261104T112422/` | 同批但**没有 `MANIFEST.json`** ⇒ 不能当「有清单的备份」用，只作冗余 | 255 MB |
| `_tools/pika-迁移/_snapshot_recycle_20261030/` | 回收站保底抽取：`笔记/` 741 个 Markdown 文件与 .bak、`pika资料共享-文本与代码/` 45 文件、`_pre-accident-workspace.json`、`MANIFEST.json` | **9.0 MB** / 797 文件 |
| `D:/$Recycle.Bin/.../$RFO3P23/` | 整个 `pika文件_Pro` 事故前快照（3531 文件） | 1.36 GB（在回收站里） |
| `git`（`D:/repo`） | `知识库` 下 731 个被跟踪文件 | — |

★ 11-04 的备份是 **1943/1944 文件**，11-08 是 **1974** —— 差额来自
① 后来重新生成的 **41 个 `.pyc`**（11-04 那次刻意排除了 pycache）、② `_observer-tools` 重建的 2 个文件。
两次都在 `vault/` 与 `skills/` 两个 tag 下，**结构一致**。
★ `_backup_20261104T112422` 没有 `MANIFEST.json` ⇒ 三核里的「sha256 对账」做不了，
**恢复时优先用带 MANIFEST 的那份**。

核对备份：
```bash
python -X utf8 -c "
import json, pathlib
p = pathlib.Path(r'D:/repo/_tools/pika-迁移/_backup_<stamp>/MANIFEST.json')
d = json.loads(p.read_text(encoding='utf-8'))
print('files', len(d['files']), 'skipped', len(d['skipped']), 'bytes', d['total_bytes'])
print('sources', d['sources'])
"
```
与步骤 2 的打印逐个对。

### 7.2 从备份还原（最常用）

```bash
# 只还原一个文件
cp -p "_tools/pika-迁移/_backup_<stamp>/skills/math-coach/scripts/foo.py" \
      "C:/Users/example/.dsh/skills/math-coach/scripts/foo.py"

# 只还原一个目录（先看清单，别一把梭）
python -X utf8 -c "
import json
d = json.load(open(r'D:/repo/_tools/pika-迁移/_backup_<stamp>/MANIFEST.json', encoding='utf-8'))
for r in d['files']:
    if r['rel'].startswith('math-coach/'): print(r['tag'], r['rel'], r['size'])
"
```

★ 还原前先算 sha256 与 `MANIFEST.json` 对该条，**不符的不写**（同 `restore_accident.py` 的规矩）。

### 7.3 事故还原专用脚本

```bash
cd "D:/repo"
python -X utf8 "_tools/pika-迁移/restore_accident.py"            # 只打印（默认）
python -X utf8 "_tools/pika-迁移/restore_accident.py" --execute  # 真写
```

**2026-11-07 实测输出**：
```
[统计]
  可还原      : 73 条 / 1.3 MB
  已写回      : 0 条（dry-run）
  恢复不了    : 1 条
  校验/写入失败: 0 条
```
取源优先级：① `pika_math_learning_toolkit-2.1.4.zip!payload/`（71 条）
② `git -C <ROOT> show HEAD:<相对路径>`（2 条 vault 笔记）③ 无源则明说跳过。
每条都要求「取回内容的 sha256 == `b3_fullhash.json` 记录的 `old_sha`」，不符不写。
退出码：`0` 无失败 / `5` 有失败。

★ **注意**：这个脚本还原的是「**事故前**」状态。如果 11-04 的裁定（合并那篇笔记、
恢复 workspace）是**有意**的，跑它会把裁定也一起回退。**只在真出事时用，且先 dry-run 读 73 条清单。**

### 7.4 从 git 还原

```bash
cd "D:/repo"
git status --porcelain -- "知识库/pika文件_Pro/笔记共享vault/math/<笔记>.md"
git show "HEAD:知识库/pika文件_Pro/笔记共享vault/math/<笔记>.md" > /tmp/head.md
# 核对 sha256 后再写回
```

**限制**：只有**被跟踪**的文件能这样救。下面这些**不在版本库里**，只能靠备份或回收站：

| 路径 | `check-ignore` | `ls-files` | 结论 |
|---|---|---|---|
| `知识库/.trash/` | NOT ignored | 0 | untracked |
| `知识库/pika文件_Pro/笔记共享vault/.obsidian/` 整目录 | NOT ignored | **0** | untracked（2026-10-31 事故丢的就是这里） |
| `…/math/模长总和为1…md.bak-before-merge-20261104` | NOT ignored（`*.bak` 规则不匹配这个后缀） | 0 | untracked |
| `知识库/.obsidian/workspace.json`（外层） | **IGNORED**（`.gitignore:21`） | 0 | 忽略 |
| `知识库/.obsidian/app.json` / `appearance.json` / `graph.json` 等 7 个 | not ignored | **7** | **tracked**（能救） |

⇒ 判断「这份能不能从 git 救」**只查一个命令**：

```bash
git -C "D:/repo" ls-files --error-unmatch "<相对路径>" 2>/dev/null && echo TRACKED || echo "NOT IN GIT"
```

**不要**用 `git check-ignore` 下结论 —— 它对「untracked 且没被忽略」的路径一声不吭，
容易误读成「在库里」。这正是 2026-10-31 那次 `workspace.json` 丢掉时被误判的原因。

### 7.5 从回收站还原

```bash
# 只读查看（不要用资源管理器「清空回收站」）
ls "D:/\$Recycle.Bin/S-1-5-21-2275053455-3505615624-493918824-1001/\$RFO3P23/"
```
`$IFO3P23`（70 B）是元数据，`$RFO3P23`（`R` = 真内容）里才是文件。
**复制出来用，不要移动或删除。** 已抽取的 797 文件在
`_tools/pika-迁移/_snapshot_recycle_20261030/`，多数场景直接从那里拿更快。

### 7.6 应急判据：什么时候该停

出现下面任意一条，**立刻停手、不要在同一个会话里继续**：

1. 备份三核有一条不上。
2. `pika_migrate.py` 退出码 3 或 4。
3. 终态复核里 `TOTAL diff > 0` 且重跑 `--only skills` 也修不掉。
4. 外层 zip 的 sha256 变了（说明有人写过它）。
5. `suite_doctor.py` 报 `missing_skill_payload` 且重装也修不掉。
6. 有人（包括你自己）开始想「先删了再说，反正包里还有」。

---

## §8 「不知道」清单

> 这一节必须诚实。下面每一条都是**真不知道**，不要编。

1. **换版本后 `b3_fullhash.json` 怎么自动重算** —— `inventory/_scripts/p1…p40` 那批
   一次性脚本是硬编码 2.1.7 的，没有参数化。换版本要改常量或重写。
   现有清单只能保证对 2.1.7 正确。
2. **旧 toolkit 的 `install.py` 到底有没有在本机真跑过** —— 只有
   `%LOCALAPPDATA%/pika_math_learning_toolkit/INSTALL_REPORT.json`
   （`status: installed`、`target_root: D:\Hermes Agent CN Desktop\…`、
   `checksums_verified: 289`、`timestamp_utc 2026-09-12T09:48:24Z`）这一份间接证据，
   没有运行日志。
3. **`_observer-tools` 的 `hermes_observer.py` / `test_e2e.py` 当初是怎么丢的** ——
   `git log --all` 只有 `cde23b0 init`，它们从未被跟踪过。2026-11-04 已按 README 契约重建
   （9776 B / 11001 B，`E2E: 25/25 PASS`），但「原版长什么样」无法知道。
4. **vault 在 git 最后提交 `924c087`（2026-09-14 18:42）之后改了多少** ——
   只做过 11 篇三方抽样（`D:/repo/_tools/pika-迁移/inventory/three_way_notes.md`：磁盘==zip **11/11**，
   其中 9 篇 git≠磁盘但磁盘=zip）。全量没做。
5. **`知识库/Jelly文件_Pro`（271 文件 / 293115084 B）是什么** —— 与 pika 无关，
   不在 zip 里，也没查到来源说明。本规程**不动它**。
6. **`OBSIDIAN_LOCAL_KB_DB` 该不该改**（§5.4 的甲/乙）—— 是「改 env 指活库」还是
   「删三个 env 回归自定位」，取决于以后还要不要第二个宿主。**需要人定。**
7. **`知识库/.mpk/root.json` 为什么不存在** —— `D:/repo/.mpk/` 有
   `root.json` 和 `resources.jsonl`，但 `知识库/.mpk/` 没有。不影响运行，原因不明。
8. **`代码与数据` 何时、为什么从 `D:/repo/代码与数据` 搬到
   `Tool/代码与数据`** —— 只确认了「现在在 Tool 下」，搬迁时间与动因无记录。
9. **换新版本包后 PORTABLE_ADAPTATIONS.json 的 28 条会变成几条** ——
   2.1.7 是 28 条；下一个版本会不会增减、增减哪些，只能拿到包再看。
10. **`pika文件_Pro.zip` 与早期诊断里那份 `$RL9HQVI.zip`（1549 MB / 2412 条目）
    是不是同一副本** —— 那份已不在盘上，无法比对。

---

## 附录 A：旧文档去留判定

> **只判定，不删任何文件。** 删除由主控执行。判定分四档：
> **保留**（仍有独立价值）/ **合并进规程**（内容已被本文吸收，原文只作证据）/
> **标记过时**（读数或结论已失效，照它做会错）/ **不在范围**（与 pika 无关）。

### A.1 `program/engineering/` 下（本规程**未改动**其中任何已跟踪文件）

★ 逐条验过的 git 身份（`git ls-files --error-unmatch`）：

```
docs/research/pika-2.1.7-迁移实测.md          TRACKED
复盘/pika迁移-回填方案.md                     TRACKED
复盘/pika迁移-新旧比对.md                     TRACKED
复盘/卡/卡B3-pika新旧比对与回填方案.md        TRACKED
tools/pika_migrate.py                         TRACKED
.tmp/skill_upgrade.py                         UNTRACKED（.gitignore:121 忽略 `.tmp/`）
docs/runbooks/pika-升级规程.md（本文）        TRACKED（本次入库）
```

| 文件 | 行/字节 | 判定 | 理由 |
|---|---|---|---|
| `docs/research/pika-2.1.7-迁移实测.md` | 255 / 18973 | **合并进规程** | 是本文 §3 步骤 7/8、§6.5、§6.7、§7.3 的**一手证据来源**，读数是唯一的（自检、pytest 基线、两向 PS 实测）。操作流程已被本文覆盖，原文保留作证据。★ 保留它的同时要记住：它 §2.4 的「保留补丁」结论**已被它自己推翻**，只读最终处置。 |
| `复盘/pika迁移-回填方案.md` | 605 / 37363 | **标记过时**（部分合并） | ① 文首「6 个已装，缺 compute-fleet-manager」已过时（现在 7 个都装了）；② §1.4 说 `%APPDATA%\obsidian-vault-notes\config.json` 是「313 B、kb_root 指死路径」——实测已 **288 B、2026-11-01 修好**；③ §5 B5「3 个 0 字节 SKILL.md 保留」与实测文档「已删」直接矛盾；④ §3.1「改 env 指向活库」与 `D:/repo/_tools/pika-迁移/宿主与环境变量.md`「删 env 回归自定位」**方向相反**。**仍有价值的部分**：§2.1–§2.5 的结构差异逐行比对、§7 事故记录、§4 六类条数 —— 这些已并入本文 §4/§5/§7。 |
| `复盘/pika迁移-新旧比对.md` | 787 / 51547 | **合并进规程**（附表保留） | §1–§2 的账目、附录 A 的 74 条 DIFF 全表、附录 B 的 303 条独有全表**无法复现**（需要 274763 文件的 `d_index.json`），必须保留。但 §3.1 有一处**明确错误**：说 obsidian-vault-notes 的 SKILL.md「无 `version:` 行」——实测有（`version: v1.13.5`，第 4 行）。§6.3 的三条建议与实测文档的最终裁定**不一致**（见 A.3）。 |
| `复盘/卡/卡B3-pika新旧比对与回填方案.md` | 51 / 6575 | **保留** | 是**判据来源**（用户 m08232 原话 + 7 条硬判据），不是操作文档。本文 §1 铁律二直接引用它的「删除前必须已验证新版存在且内容正确（顺序不能反）」。 |
| `tools/pika_migrate.py` | 1108 / 47030 | **保留**（工具） | 仍是唯一能跑 verify/backup/delete/place 的实现。本文 §3 步骤 3–6 就是调它。**已知缺口**（本文已补）：无前置检查、不清 pycache、不写终态报告、路径硬编码。 |
| `.tmp/skill_upgrade.py` / `.tmp/pika_backup2.py` / `.tmp/merge_note2.py` | — | **保留**（工具，但**随时可能没了**） | `.gitignore:121` 忽略整个 `.tmp/`，这些脚本**不在版本库里、`.tmp/` 被清就永久丢失**。本文 §3 步骤 2 已把备份脚本内联进规程，**不再依赖它们存在**。`skill_upgrade.py` 的 `--dry-run` 仍可用；其 `EXPECTED` 表是 2.1.7 专用的。★ 想长期留就挪到 `_tools/pika-迁移/`（那里有 D: 盘实体、不进 git 但不会随手清掉）。 |

### A.2 `_tools/pika-迁移/` 下（**均未被 git 跟踪**）

| 文件 | 行/字节 | 判定 | 理由 |
|---|---|---|---|
| `D:/repo/_tools/pika-迁移/对应表.md` | 153 / 7656 | **标记过时** | ① 结论表写「新版 = `D:/downloads\pika文件_Pro (2)\pika文件_Pro`」——**该目录 2026-10-30 15:36:05Z 已进回收站**；② 写「技能包是 2.1.4 / 339 条目 / 6 个」——现在是 2.1.7 / 488 条目 / 7 个；③ 写「旧版在 `D:\Hermes Agent CN Desktop\data\hermes-home\skills\`」——**该宿主已下线，pika 一个都不在了**；④ 5 个更新目标里的 `D:/repo\代码与数据\` 已不存在。**仍有价值**：§五的规范摘录（原件/索引/工具状态三分、稳定资源 ID `KB-...`、任务文件夹、两个 validator）是**跨版本不变的规矩**，已并入本文 §5.1 精神层面。 |
| `D:/repo/_tools/pika-迁移/宿主与环境变量.md` | 180 / 7390 | **标记过时**（核心结论已并入） | ① 「三个用户级 env 是上一个会话手工设的」这个定性仍然成立；② 但「想彻底消除 = 删掉三个 env」这个方案与 `复盘/pika迁移-回填方案.md` §3.1 **方向相反**，本文 §5.4 把两者并列成「甲/乙」并注明要人点头；③ 里面的 `setup_local.py check` 死结分析（`kb_root != KB_ROOT`）仍准确，已并入 §6.12。 |
| `D:/repo/_tools/pika-迁移/inventory/勘察报告.md` | 680 / 60205 | **保留**（证据） | 60205 B 的原始勘察：`root_map.json` 5 对根、sha256 分层抽样 243/243、git 记录 7 个已删文件、13 项不知道。这是**唯一**记录「勘察时本机长什么样」的文件，删了就无法回溯。★ 其中 §3.6「6 个 pika」、§3.8「3 个 0 字节 SKILL.md」等读数已过时，**读结论前先看日期（2026-10-30）**。 |
| `D:/repo/_tools/pika-迁移/inventory/three_way_notes.md` | 26 / 2139 | **保留**（证据） | 11 篇笔记三方比对，是「磁盘==zip 11/11」的唯一出处，本文 §8.4 引用它。 |
| `D:/repo/_tools/pika-迁移/inventory/zip_tree.md` | 208 / 7993 | **保留**（证据） | 四层压缩包的深度聚合表（2411 / 1164 / 488 / 48 条目、33 种扩展名分布）无法从别处得到。 |
| `inventory/b3_fullhash.json` | 1783882 B / 3771 行 | **保留**（数据） | 迁移器 `verify()` 的唯一判据来源。**丢了迁移器就废了**。 |
| `inventory/old_candidates.json` | 1950786 B / 4074 行 | **保留**（数据） | 同上（`build_rows()` 的一半）。 |
| `inventory/d_index.json` | 63817062 B / 274763 文件 | **保留**（数据） | 全盘 sha256 索引，支撑「303 个新版独有全是真新增」这个结论。**61 MB，但删了结论不可复核。** |
| `restore_accident.py` | 200 / 7593 | **保留**（工具） | 事故还原的唯一路径，§7.3 直接调它。 |
| `backup_pika.py` | 89 / 2671 | **标记过时** | `TARGETS` 里第 3 项 `代码与数据` **本机已不存在**，会走「源不存在，跳过」；且 `shutil.copytree(dirs_exist_ok=True)` 没有 `nul` 保护、没有 sha256 对账。**改用本文 §3 步骤 2 的内联脚本**（逐文件 + 三核 + `SKIP_NAMES`）。 |
| `install_to_dsh.py` | 3969 B | **标记过时** | `ZIP` 硬编码 `D:/downloads/pika文件_Pro (2)/…2.1.4.zip`（**路径已死**）；`SKILLS` 只有 6 个，缺 `compute-fleet-manager`。 |
| `map_dirs.py` | 3528 B | **标记过时** | `NEW = D:/downloads/pika文件_Pro (2)`（已死）。脚本本身只读、无害，但结论不能用。 |
| `_已执行/apply_skills.py` | — | **标记过时（反面教材）** | 「先 `shutil.rmtree` 再解压」= 会删掉本机补丁；`DEST` 是已下线的 Hermes 宿主。本文 §1 铁律二明确禁止复用。 |
| `_已执行/apply_data.py` | — | **标记过时（仍有参考价值）** | 5 个目标路径里有一个已不存在；但它的「**绝对不能动**」清单（`Library\` 下自己的书、`_observer-tools\`、`Codex Skills\`）仍然对，已并入本文 §0「不适用」与 §1 铁律三。 |
| `setup_postgres.py` | 7290 B | **不在范围** | 是给 OpenMAIC 装 PostgreSQL 的，与 pika 无关。 |
| `_plans/` 7 个旧 plan | — | **保留**（审计痕迹） | `plan_20261031_194409…204605` 是事故前后那批，属于证据链。新跑出来的 `plan_20261107_*` 是本文步骤 6 的产物。 |

### A.3 互相矛盾的原文（逐条引出，本文的裁定在右）

**A.3 的矛盾共 7 组**：1 vault 那两处 DIFF 留哪份｜2 本机补丁要不要保留｜3 三个 env 留着还是删掉｜4 3 个 0 字节 SKILL.md 留还是删｜5 新版包 6 个还是 7 个 skill｜6 生效的是哪份配置｜7 事故丢的 workspace.json 为什么没副本。**每一组都引了双方原文，并给了本文裁定与实测依据。**
**矛盾 1：vault 那两处 DIFF 到底留哪份**

- `复盘/pika迁移-新旧比对.md` §6.3 原文：
  > 「`一致几乎处处有界…md` 8118/8117 1 处空格 **用新版或跳过**；
  > `模长总和为1…md` 13497/8431 15 处 +82/−32 真扩写 **用新版**。」
- `docs/research/pika-2.1.7-迁移实测.md` §4.2 原文（最终裁定）：
  > 差异1「`local == git HEAD True`、`zip == git HEAD False` ⇒ **保留本地版**」
  > 差异2「以 zip 为主体 + 旧稿代码作附录 … **13497 → 14806 B / 193 行**」

**本文裁定**：以**实测文档**为准（它更晚、且有 git 作证）。
终态读数是 `vault diff=2, only_local=2, only_zip=0` —— 这 2 处差异是**有意保留**的。

**矛盾 2：本机补丁要不要保留**

- `docs/research/pika-2.1.7-迁移实测.md` §2.4 **前半**原文：
  > 「本机补丁只有 1 处值得保留：`math-coach/scripts/tests/test_dsh_rational_identity.ps1:19`
  > 的 `-AsHashtable`（Windows PowerShell 5.1 不支持该参数，pwsh 7 支持）」
- 同文 §2.4 **后半**（自我推翻）原文：
  > 「zip 原版（无 `-AsHashtable`）PS5.1 **PASS 10 generic cases**；已装补丁 PS5.1 挂。
  > …已装那行是上一版遗留的坏行，2.1.7 恰好删掉。」

**本文裁定**：**不保留**。`-AsHashtable` 是坏行（§6.5，2026-11-07 复验现行文件已与 zip 一致）。
任务书里「只有 1 处补丁值得保留」这句**已不成立**。

**矛盾 3：三个环境变量是「留着」还是「删掉」**

- `复盘/pika迁移-回填方案.md` §3.1 原文：
  > 「`OBSIDIAN_LOCAL_KB_DB` 与活配置 A 的 `db_path` 不一致 … **建议改 env 指向活库**」
- `D:/repo/_tools/pika-迁移/宿主与环境变量.md` 原文：
  > 「**想彻底消除（还没做）** = 删掉那三个用户级 env 让技能回归自定位
  > （`BUNDLED_KB_ROOT`），配置放每个宿主各自位置」

**本文裁定**：两个方向都记录，列成 §5.4 的「甲/乙」，**要人点头**，不擅自改。
理由：它决定「以后还能不能有第二个宿主」，不是纯技术选择。

**矛盾 4：3 个 0 字节 SKILL.md 留还是删**

- `复盘/pika迁移-回填方案.md` §5 B5 原文：
  > 「3 个 0 字节 SKILL.md … ⇒ **保留**」
- `docs/research/pika-2.1.7-迁移实测.md` 原文：
  > 「3 个 0 字节 SKILL.md … 已清理（删除）」+ 本次复验：`知识库/Codex Skills/` 与
  > `知识库/pika文件_Pro/Codex Skills/` 都已是**空目录**

**本文裁定**：**文件已删（事实）**，**空目录保留**（§6.16）。两条原文各对一半。

**矛盾 5：新版包是 6 个还是 7 个 skill**

- `D:/repo/_tools/pika-迁移/对应表.md`：> 「`pika_math_learning_toolkit-2.1.4.zip`（339 个条目）、包内技能 **6 个**」
- `复盘/pika迁移-回填方案.md` 文首：> 「**6 个已装，缺 compute-fleet-manager**」
- `复盘/pika迁移-新旧比对.md` §0：> 「skills **7 个**（不是 6 个也不是 6–7 个）」

**本文裁定**：**2.1.7 是 7 个，必须装齐**（§6.13）。说 6 个的都是 2.1.4 口径。

**矛盾 6：生效的是哪份 obsidian-vault-notes 配置**

- `复盘/pika迁移-新旧比对.md` §5.3：> 「`SKILL_NAME` = `obsidian-vault-notes` ⇒ **生效的是 (5)**
  （`%APPDATA%\obsidian-vault-notes\config.json`，313 B，kb_root 指死路径）」
- 2026-11-07 实测：该文件 **288 B、mtime 2026-11-01 09:39、kb_root 已指向活路径**；
  而实际生效的是 `OBSIDIAN_VAULT_NOTES_CONFIG` 指定的
  `%APPDATA%\pika_math_learning_toolkit\obsidian-vault-notes.json`（260 B）。

**本文裁定**：以**实测**为准（§5.5 表）。旧结论「无 env 时生效哪份」仍然成立，
但本机**有** env，所以「生效的是 (5)」这句是错的。

**矛盾 7：事故丢的那个 `workspace.json` 为什么没有副本**

- `复盘/pika迁移-回填方案.md` §7 原文：
  > 「净损失 **1 个文件** `notes/.obsidian/workspace.json`
  > （7697 B，**被 `.gitignore:21` 忽略**，无副本）」
- 2026-11-07 实测：
  ```
  git check-ignore -v "知识库/pika文件_Pro/笔记共享vault/.obsidian/workspace.json"
    → 无声（NOT ignored）
  git ls-files "知识库/pika文件_Pro/笔记共享vault/.obsidian" → 0 条
  ```
  而 `.gitignore:21` 的真实内容是 `知识库/.obsidian/workspace.json`（**外层**那棵树）。

**本文裁定**：旧文档这两处都不准确 —— ① 路径写成 `notes/.obsidian/workspace.json`，
`notes/` 这层目录**不存在**（真实路径是 `笔记共享vault/.obsidian/workspace.json`）；
② 「被 `.gitignore:21` 忽略」是误判，真实原因是**整目录 untracked**。
详见 §6.9 与 §6.19。

### A.4 判定统计

按 **A.1 + A.2 两张表的行数**统计（`.tmp/` 那 3 个脚本算 1 行；`_plans/` 7 个 plan 算 1 行）：

| 判定 | 行数 | 文件 |
|---|---:|---|
| **保留** | 11 | `复盘/卡/卡B3-pika新旧比对与回填方案.md`、`tools/pika_migrate.py`、`.tmp/{skill_upgrade,pika_backup2,merge_note2}.py`、`D:/repo/_tools/pika-迁移/inventory/勘察报告.md`、`D:/repo/_tools/pika-迁移/inventory/three_way_notes.md`、`D:/repo/_tools/pika-迁移/inventory/zip_tree.md`、`inventory/b3_fullhash.json`、`inventory/old_candidates.json`、`inventory/d_index.json`、`restore_accident.py`、`_plans/` 旧 plan |
| **合并进规程** | 2 | `docs/research/pika-2.1.7-迁移实测.md`、`复盘/pika迁移-新旧比对.md` |
| **标记过时** | 8 | `复盘/pika迁移-回填方案.md`、`D:/repo/_tools/pika-迁移/对应表.md`、`D:/repo/_tools/pika-迁移/宿主与环境变量.md`、`backup_pika.py`、`install_to_dsh.py`、`map_dirs.py`、`_已执行/apply_skills.py`、`_已执行/apply_data.py` |
| **不在范围** | 1 | `setup_postgres.py` |
| **合计** | **22** | 与 A.1（6 行）+ A.2（16 行）逐行对得上 |

★ 关键：**没有一份被判定「可删」**。8 份「标记过时」里，`复盘/pika迁移-回填方案.md` 与
`复盘/pika迁移-新旧比对.md` 仍带着**不可复现的证据**（事故前后 sha、74 条 DIFF 全表），
`D:/repo/_tools/pika-迁移/对应表.md` 与 `D:/repo/_tools/pika-迁移/宿主与环境变量.md` 带着**跨版本不变的规范摘录**。
本规程的立场是「**新规程覆盖操作，旧文档降级为证据**」，不是「删了旧的好看」。
实际删除与否由主控决定，本文只给判定。

★ 深坑提醒：`program/engineering/.wt/A320n/`、`.wt/A359/`、`.wt/A365/`、`.wt/A366/`
与 `.tmp/mywork_bak/`、`.tmp/trunk-bg009-20261104/` 里都有**同名的副本**。
那是工作树与备份，**不是权威**。改文档只改主树，不要去改副本（也不要去删它们）。

---

## 附录 B：本次复核读数汇总（2026-11-07 起，2026-11-08 00:05 补步骤 2 实跑）

| 项 | 读数 |
|---|---|
| 外层包 | 1451498774 B / 2411 条目 / `testzip()` → `None`（ALL OK）/ sha256 `4a0783365a9f30df…` |
| 7 skill 版本 | 包与已装**逐个相同**：v1.0.6 / v1.11.5 / v1.13.0 / v3.2.8 / v1.12.0 / v1.13.5 / v1.12.3 |
| skills 全树 | zip 467 / 已装 467 / **same 467 / diff 0 / onlyZip 0 / onlyInst 0** |
| vault | zip 1127 / 盘 1129 / same 1125 / **diff 2** / **only_zip 0** / only_local 2 |
| HKCU\Environment | 三个 pika 变量都在，指向都存在；`OBSIDIAN_LOCAL_KB_DB` 指**废弃库**（23764992 B / 09-13） |
| 两份 `.obsidian` | 外层 15 文件（多 `snippets/bold-use-real-pjp-b.css` 3087 B）、内层 14 文件；**only_outer 1 / only_vault 0 / both 14 / same 11 / diff 3** |
| pycache | **6 dirs / 41 pyc / 0 `.pytest_cache`**（全部 mtime 2026-11-05 21:55–22:38，是重新生成的，非迁移残留。★ 写本文时跑一轮 §3 步骤 7.2 就变成 8 dirs / 43 pyc，删回 6/41 —— 见 §6.6） |
| `-AsHashtable` | zip 里 **不存在**；已装也**不存在**；两文件 1471 B / sha `8fd2e07c63fd50f8` **逐字节相同** |
| 迁移器全量 dry-run | 会删 1 / 验证失败 73 / 已相同 3697 / 无映射根 22 / 待裁决 5（45.8s） |
| 自检 | `suite_doctor` exit 0 / 7 包全 true；`validate_terminology` 7/7 ok（**必须 `cd <skill>/scripts`**，见 §6.8）；`setup_local check` healthy(697/683/stale)；`manage_kb status` docs 2422 / pages 59301 / coverage 96.28% |
| `restore_accident.py` dry-run | 可还原 73 / 恢复不了 1 / 失败 0 |
| 备份 | `_backup_20261104T112422` 255M/1943（无 MANIFEST）；`_backup_20261104T112516` 255M/1944（有）；`_backup_20261108T000555` **256M/1974**（本文步骤 2 原文实跑；有 MANIFEST）；`_snapshot_recycle_20261030` 9.0M/797 |
| 仓 | HEAD `ef04af7`、脏 53 行、`知识库` 被跟踪 731 文件 |
| 盘 | D: 83G 可用（67% 已用）/ C: 28G 可用（87% 已用，偏紧） |
| 最长路径 | vault 绝对路径 **239** / 260（余量 21）；Library 199；skills 26 |
