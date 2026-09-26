# 修 `--detach`（前置检查顺序 + 子进程 argv 少了脚本）（T-G92）

> 外包卡 003。主控在 `复盘/长跑保命-T-G91.md` §5 记过一条观察：`--detach` 的前置检查
> 其实跑在**子进程**里。这一张卡把它改对、补齐"没过也要留痕"—— 并在真机证据里又逮到
> **第二个洞**：扔出去的子进程 argv 少了**脚本路径**，`--detach` 其实**从来没真跑起来过**。

## 1. 现象①：前置检查顺序错（检查在子进程里）

`tools/wb_dispatch.py` 的 `main()` 里，`--detach` 分支排在四道前置检查**之前**：

```python
    if args.detach and not args.detach_done:      # ← 前置检查之前
        detach_log = ...
        pid = spawn_detached(detached_argv(sys.argv[1:]), detach_log)
        print(f"[扔 ] 已扔出去单独跑（pid {pid}）…")
        return 0                                  # ← 父进程就此退 0
    problems, log = preflight(...)                # ← 检查其实在**子进程**里才做
```

三个后果：

1. **父进程退 0 不表示检查过了** —— 它只表示"我把活扔出去了"；
2. 前置检查没过时，子进程退 2 但**不写判决** `wb-<卡>.verdict.txt` → 过夜之后
   `python -X utf8 tools/wb_dispatch.py --card <卡> --status` 只会说「判决：还没有」，
   **分不清"没跑"和"跑挂了"**；
3. `detached_argv()` 不给子进程补 `--no-preflight`：父进程已经查过登录了（`auth_ok()`
   是真发一条 CLI 请求，十几秒），子进程还要再查一遍。

## 2. 现象②：扔出去的子进程 argv 少了**脚本路径**（真机证据 (b) 逮到）

`detached_argv()` 旧返回是 `[python, "-X", "utf8", *args, "--detach-done"]` —— 少了**脚本自己**。
子进程实际执行的是 `python -X utf8 --card 900 …`，python 把 `--card` 当成**自己的**选项：

```
Unknown option: --card
usage: C:/Users/example\miniconda3\python.exe [option] ... [-c cmd | -m mod | file | -] [arg] ...
```

**所以 T-G91 的 `--detach` 从来没真扔出去过** —— 父进程打印「已扔出去」并退 0，子进程却当场
报错退出。T-G91 的真机探针只验了 `spawn_detached()`（用一条自造的 `python -c` 命令），
**没走 detach 这条 argv 拼装路**，所以这个洞一直没被逮到。这正是"证据 (b) 要看子进程真输出"
的意义所在。

## 3. 根因

两处都是"`--detach` 这条路没被端到端跑过"：
- ① 顺序错：前置检查的本意是"派活之前把该查的查完"，detach 那条路把它推到了检查之前；
- ② argv 拼错：`sys.argv[1:]` 丢掉的是**脚本名**（`sys.argv[0]`），解释器后面直接接参数，
  子进程根本起不来。

## 4. 修法（只动 `detached_argv()` 与 `main()` 里 `--detach` 那几行）

- `main()`：把 `--detach` 分支挪到 `problems` 判断**之后**。没过 → 打印每条原因、
  写 `wb-<卡>.verdict.txt`（「前置检查没过 → 没派活」+ `'；'.join(problems)`）、退 2，
  **绝不 detach（不留孤儿进程）**；过了 → 打印「前置检查全过 → 扔出去单独跑（pid …）」+
  `--status` 提示 + dispatch.log 路径，退出码仍 0。
- `detached_argv()`：返回值形如 `python -X utf8 <脚本自己> <原参数> --no-preflight --detach-done`
  —— ① 把**脚本自己**放在解释器后面（`str(Path(__file__).resolve())`），子进程才跑得起来；
  ② 去掉 `--detach` 与输入里已有的 `--no-preflight`，补**恰好一个** `--no-preflight`。

**其它行为一个字没改**：看门狗 / 心跳 / 回合上限（写卡 240、只读 80）/ 续跑（`--resume` /
`--retry`）/ 铁律进系统提示 / 模型默认值 / `--autocompact 1m` / 超时默认 7200，都没动。
`--detach` 的语义（扔出去跑）不变；子进程仍会跑规格 / 工作区 / log 三道检查（只是不再查登录）。

## 5. 反证（先红后绿）

命令（`$env:PYTHONPATH="$PWD\tools\sandbox_shim"`）：

```
python -X utf8 -m pytest tests/test_wb_dispatch.py -q --no-cov
```

**先红**（改实现前，两步各自红）：

```
# ① 顺序洞：4 failed / 38 passed（共 42 条）
FAILED test_detached_argv_strips_the_flag_and_marks_the_child
FAILED test_detached_argv_adds_no_preflight_exactly_once
FAILED test_detach_throws_the_work_out_and_returns_immediately
FAILED test_detach_runs_preflight_in_the_parent_and_refuses_before_throwing
E       assert 0 == 1     # detached_argv 里 --no-preflight 出现 0 次（要 1 次）
E       assert 0 == 2     # 缺规格的 --detach 退了 0（要退 2）
[扔 ] 已扔出去单独跑（pid 4242）…     # 旧写法：检查都没过也照扔（这就是那个洞）

# ② 脚本路径洞：1 failed / 42 passed（共 43 条）
E   AssertionError: 解释器后面必须是脚本自己
E   assert '--card' == 'D:/repo/engineering\\tools\\wb_dispatch.py'
```

**再绿**：`43 passed`（退出码 0）。

新增/适配的用例（`tests/test_wb_dispatch.py`，共 +3 适配 2）：

- `test_detach_runs_preflight_in_the_parent_and_refuses_before_throwing` —— 缺规格 → 退 2、
  `spawn_detached` **一次都没被调**、`wb-900.verdict.txt` 存在且含「前置检查没过 / 没派活 / 卡规格文件不存在」；
- `test_detached_argv_adds_no_preflight_exactly_once` —— 输入里已有 `--no-preflight` 也去重，仍只留一个；
- `test_detached_argv_keeps_the_script_so_the_child_actually_runs` —— 解释器后面是**脚本自己**；
- `test_detach_throws_the_work_out_and_returns_immediately`（改用沙盒 fixture）—— 检查全过才扔、
  打印「前置检查全过」、`--no-preflight` 恰好一次；
- `test_detached_argv_strips_the_flag_and_marks_the_child` —— 顺带补一条 `--no-preflight` 断言。

### 真机证据（跑在提交后：工作区干净才过得了"工作区干净"那道检查）

```
# (a) 前置检查没过：立刻退 2、不 detach、并留下 verdict
python -X utf8 tools/wb_dispatch.py --card 900 --spec 没有这张卡.md --detach --execute --no-preflight
python -X utf8 tools/wb_dispatch.py --card 900 --status

# (b) 检查过了再扔：--detach 但不加 --execute（子进程只干跑，不真派活、不花钱）
python -X utf8 tools/wb_dispatch.py --card 900 --spec 复盘/外包卡-003-修detach前置检查.md --detach --no-preflight
Get-Content gates\diag\wb-900.dispatch.log
```

结果见主控回报（§6）。★ (b) 的第一次运行**就是**逮到现象②的那一次（`Unknown option: --card`）。

## 6. 边界（如实写）

- ★ **本卡追加修了不在 §2 六条口径里的一个洞**（脚本路径缺失）—— 它不是"顺手扩范围"，而是
  **卡 §5 的证据 (b) 要求子进程真跑起来**；若不认可以回退（改动集中在 `detached_argv()` 一行）。
- 只改了 `--detach` 这一条路，别的一字未动（见 §4）。
- 子进程仍会重跑规格 / 工作区 / log 三道检查 —— 这是**有意**的（不省那三道，只省登录自检）。
- `--detach` 之后看门狗仍是那个脱离进程自己带着的（T-G91 的边界，未变）。

## 7. 没动的

- `tests/test_wb_dispatch.py` 里 T-G88/89/90/91 的既有断言一条没删（只适配了 detach 那两条）。
- 台账其它条目、`src/**`、其它 `tools/` 文件一个字没动。
