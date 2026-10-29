#!/bin/bash
# 把一张卡的「落地门禁」搬到云机跑、产物回传（卡 E35 · T-AG489；从 gates/diag/ 搬入库）。
#
# 用法（本机 Git Bash）：
#   TF_PROJECTS_TOML=<云机上的项目索引路径> bash scripts/cloud/run_gate.sh <卡号> [端口段]
#
# 为什么在库里：原来这份脚本住在 gates/diag/，而 `.gitignore` 的 `gates/diag/*` 把整个目录
# 忽略 ⇒「云机怎么跑门禁」只存在某台机器的磁盘上，换台机器就没有这件事。现在它是被 review 的源码。
#
# 三条口径（卡 E35 判据）：
#   ① 清树用 `git clean -xfdq`（**带 -x**）。不带 -x 时上一趟的 `gates/last.json` 与
#      `gates/logs/` 会留在盘上（它们是被忽略文件），被这一趟读成「上一轮的判定」⇒
#      自指钉子（test_false_success_pins / test_gates_reuse_line）必红。实测踩过。
#   ② 跑之前**断言 `gates/last.json` 不存在**：存在就报错退出（绝不静默沿用上一趟的判定）。
#   ③ 仓外配置（TF_PROJECTS_TOML 等）显式注入，**缺了就报错不跑**（fail fast）——
#      不许「跑一半发现没配」。
#
# 前提：卡树 `.wt/<卡号>` 已存在且已 realign 到当前主树 HEAD；云机 SSH 可用（~/.ssh/id_ed25519_cloud）。
set -u

# ---------------------------------------------------------------- 残留断言（可单测）
# 单独抽成函数：tests/test_cloud_sync.py::test_run_gate_refuses_residual_last_json
# 用 `--check-residue <目录>` 直接打这一针（不必真连云机）。
residue_of() { printf '%s/gates/last.json' "${1%/}"; }

require_no_residue() {
  local dir="${1:?用法: require_no_residue <目录>}"
  local victim
  victim="$(residue_of "$dir")"
  if [ -e "$victim" ]; then
    echo "✗ 残留：$victim 存在 —— 上一趟的判定会被这一趟读到（假绿/假红都算）。" >&2
    echo "  处置：清树要带 -x（git clean -xfdq），或换一个干净的 checkout。本脚本不静默沿用。" >&2
    return 2
  fi
  return 0
}

if [ "${1:-}" = "--check-residue" ]; then
  require_no_residue "${2:?用法: run_gate.sh --check-residue <目录>}"
  exit $?
fi

# ---------------------------------------------------------------- ③ fail fast：仓外配置
card="${1:?用法: TF_PROJECTS_TOML=<路径> bash scripts/cloud/run_gate.sh <卡号> [端口段]}"
port="${2:-9361}"
cloud_dir="${CLOUD_DIR:-C:/eng}"
projects_toml="${TF_PROJECTS_TOML:-}"
model_registry="${TF_MODEL_REGISTRY:-}"

if [ -z "$projects_toml" ]; then
  echo "✗ 缺 TF_PROJECTS_TOML：仓外项目索引必须显式注入（卡 E35 判据 3，fail fast）。" >&2
echo "  它不在仓里（真身就在**仓的祖父目录**下的 infra/pool/projects.toml），缺了 cloud 上" >&2
  echo "  test_pool_* / test_contract_audit 会集体红 —— 那是配置没给，不是代码坏。" >&2
echo "  例：TF_PROJECTS_TOML='/<仓的祖父目录>/infra/pool/projects.toml' \\" >&2
echo "        bash scripts/cloud/run_gate.sh E35" >&2
  exit 2
fi

KEY="$HOME/.ssh/id_ed25519_cloud"
# ★ CI 可复现性：**不给默认云机**。原来这里带一个默认地址（变配前的公网 IP，早已
#   失效，见 docs/subsystems/ci/云门禁机.md §1 的历史读数）—— 等于「没配就默默去连
#   一台死机器」，失败现场看起来像网络问题、不像配置问题。改成 fail fast。
#   exit 9 = 没配云机（与 exit 2 缺 projects_toml 并列，都是「配置没给、不是代码坏」）。
if [ -z "${CLOUD_HOST:-}" ]; then
  echo "✗ 缺 CLOUD_HOST：云机地址必须显式注入（不再有已失效的默认 IP）。" >&2
  echo "  例：CLOUD_HOST=administrator@<云机地址> TF_PROJECTS_TOML=<路径> \\" >&2
  echo "        bash scripts/cloud/run_gate.sh <卡号> [端口段]" >&2
  exit 9
fi
HOST="$CLOUD_HOST"
SSHOPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes"
TMP="$(mktemp -d)"
# ★ 卡 E49 pass7 实测：原来这两行按**调用者 cwd**（主仓）取提交 —— 主仓一往前走，
#   云机就 checkout 到主仓的 HEAD，而补丁是拿**卡树**的 HEAD 做的 diff ⇒
#   `git apply` 报 `patch failed: 复盘/交接-重构进度.md:3871`，门禁跑在错的树上。
#   ⇒ 提交号必须从卡树取。
head="$(git -C ".wt/$card" rev-parse HEAD)"
short="$(git -C ".wt/$card" rev-parse --short HEAD)"

# 云机侧的环境注入串：TF_PROJECTS_TOML 必给；码道池白名单给了就一并注入。
# ★ 卡 E49 落地后回归（云机 pass9）：**不许注入 TF_MODEL_REGISTRY** ——
#   注册表的真源是仓里那份 tools/pool/model-registry.toml（含 [[model]] 与
#   [pool.codearts] 引用）；仓外 models.whitelist.toml 只描述码道池（[[approved]]）。
#   把它当注册表注入，load_registry() 就找不到任何 [[model]] 条目 ⇒
#   test_model_registry / test_wb_dispatch 在云机集体红（实测 5 条）。
#   codearts 条目由 TF_MODEL_WHITELIST（CODEARTS_SOURCE_ENV）派生，注它就够。
envset="set \"TF_GATE_PORT_BASE=$port\" && set \"TF_PROJECTS_TOML=$projects_toml\""
# 卡 E49：码道池条目是**从这份白名单派生**的（tools/pool/model_registry.py 的 CODEARTS_SOURCE_ENV）
# —— 不注入就只剩 codebuddy 池，`test_model_registry` 的「跨池串用」「要有 codearts 条目」在云机必红。
model_whitelist="${TF_MODEL_WHITELIST:-}"
if [ -n "$model_whitelist" ]; then
  envset="$envset && set \"TF_MODEL_WHITELIST=$model_whitelist\""
fi
# 卡 E67：真机自检的单次 HTTP 等待窗。云机（2 物理核/4 逻辑核、内存紧）实测单次建课
# 2.1 秒，默认 10 秒在并发写时会被耗光 ⇒ `TimeoutError: timed out` 抛穿、web_live 只报
# 一条裸 traceback。云上给 30 秒。★ **这是调等待窗，不是放宽判据** —— 判据仍是
# 「全部检查通过」；超时照样记 FAIL（`tools/web_live_check.py` 的 `mark_live_error()`）。
web_live_timeout="${TF_WEB_LIVE_TIMEOUT:-30}"
envset="$envset && set \"TF_WEB_LIVE_TIMEOUT=$web_live_timeout\""

echo "=== 0/5 把主树这条分支同步到云机（目标 $cloud_dir）==="
if [ "$cloud_dir" = "C:/eng" ]; then
  git bundle create "$TMP/inc.bundle" line/impl-v1 >/dev/null 2>&1
  echo "bundle $(wc -c < "$TMP/inc.bundle") 字节"
  scp $SSHOPTS -i "$KEY" "$TMP/inc.bundle" "$HOST:C:/inc.bundle" >/dev/null
  ssh $SSHOPTS -i "$KEY" "$HOST" "cd C:/eng && git fetch -q C:/inc.bundle line/impl-v1 && git rev-parse --short FETCH_HEAD"
else
  # 第二处 checkout：同一台机上从 C:/eng 本地 fetch，不重复传包
  ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git fetch -q C:/eng line/impl-v1 && git rev-parse --short FETCH_HEAD"
fi

# 仓外配置的**落位约定**（卡 E49）：pool 工具的默认发现方式是「从 cwd 逐级向上找
# infra/pool/<文件>」。开发机上它就在**仓的祖父目录**下的 infra/pool/（不写盘符：
# 云机上仓库在 C:/eng ⇒ 对应位置是 C:/infra/pool/。配置只放 C:/poolcfg 而不铺到这里，
# test_pool_* / test_pool_task / test_wb_dispatch 这些「向上找」的用例在云机必红
# —— 那批红曾经被当成「代码不可移植」，其实是配置没按约定落位。
pool_cfg_src="${TF_POOL_CFG_DIR:-C:/poolcfg}"
pool_cfg_dst="${TF_POOL_CFG_DST:-C:/infra/pool}"

echo "=== 0.35/5 把本机仓外配置推上云机（白名单，卡 E54）==="
# ★ 卡 E54 实测：原来这里 `scp *.toml *.json`，把本机**私有账本** accounts.toml 与
#   **私有模型开关** model-switches.toml 一起推上云机 ⇒ 云机的判据输入被本机私有状态污染：
#   `test_pool_accounts.py` 两条「账本缺失要报错」判不出来（DID NOT RAISE / 走成崩溃）、
#   `test_wb_dispatch.py::test_account_auth_uses_the_profile_env_and_model` 被判「未授权模型」。
#   ⇒ 供给面收成**白名单**：门禁判据真正需要的只有项目索引（由模板渲染）与模型白名单。
cfg_local="${TF_POOL_CFG_SOURCE_DIR:-D:/repo/infra/pool}"
cfg_allow=(models.whitelist.toml)
if [ -d "$cfg_local" ]; then
  ssh $SSHOPTS -i "$KEY" "$HOST" "if not exist "$pool_cfg_src" mkdir "$pool_cfg_src"" >/dev/null 2>&1
  for f in "${cfg_allow[@]}"; do
    if [ ! -f "$cfg_local/$f" ]; then
      echo "✗ 本机缺 $cfg_local/$f —— 它是判据需要的输入（models.whitelist.toml 派生码道池条目），" >&2
      echo "  少了它云机会判「整池消失」而不是「配置没给」。fail fast。" >&2
      rm -rf "$TMP"
      exit 5
    fi
    if ! scp $SSHOPTS -i "$KEY" "$cfg_local/$f" "$HOST:$pool_cfg_src/$f" >/dev/null; then
      echo "✗ 配置推不上云机（$cfg_local/$f -> $pool_cfg_src）—— fail fast。" >&2
      rm -rf "$TMP"
      exit 5
    fi
  done
  echo "✓ 白名单配置已推上云机：${cfg_allow[*]} -> $pool_cfg_src"
else
  echo "（本机没有 $cfg_local：沿用云机上已有的 $pool_cfg_src）"
fi
# ★ 卡 E54 实测：PowerShell 的 `$_` 在 bash 双引号里会被**先在本地展开**（变成上一条命令的最后一个参数），
#   远端收到的是被啃坏的命令 ⇒ 那行整段语法错、退 5。写法：`\$_`。
echo "=== 0.4/5 铺仓外配置到 $pool_cfg_dst（向上找的约定）==="
if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
    "powershell -NoProfile -Command \"if (-not (Test-Path '$pool_cfg_src')) { exit 5 } ; New-Item -ItemType Directory -Force '$pool_cfg_dst' | Out-Null ; Get-ChildItem -Path '$pool_cfg_dst' -File -ErrorAction SilentlyContinue | Where-Object { @('projects.toml','projects.toml.tmpl','models.whitelist.toml') -notcontains \$_.Name } | Remove-Item -Force -ErrorAction SilentlyContinue ; Copy-Item (Join-Path '$pool_cfg_src' 'models.whitelist.toml') '$pool_cfg_dst' -Force -ErrorAction SilentlyContinue ; exit 0\""; then
  echo "✗ 云机上没有配置源 $pool_cfg_src（或铺不动 $pool_cfg_dst）—— fail fast，门禁一步都没跑。" >&2
  echo "  处置：本机 scp 四个仓外配置上去（scp infra/pool/*.toml $HOST:$pool_cfg_src/），" >&2
  echo "  或用 TF_POOL_CFG_DIR 指到已在云机上的那份。见 docs/subsystems/ci/云门禁机.md 的「仓外配置」表。" >&2
  rm -rf "$TMP"
  exit 5
fi
echo "✓ 配置已铺：$pool_cfg_src → $pool_cfg_dst"

# 项目索引里 `root` 是**绝对路径**：开发机那份指着本机的仓目录（带盘符的绝对路径）。
# 原样 scp 到云机 ⇒ `[project.engineering].root` 不存在 ⇒ 项目守卫拒（宁拒不许猜）⇒
# 云机上一片「项目索引读不了」。所以项目索引**由仓内模板渲染**（根换成云机的仓库目录）。
#
# ★ 模板**从本机传**、不从云机 checkout 读：模板本身可能是这张卡树里的新文件（卡 E49），
#   而补丁要 3/5 才 apply —— 让供给步去读一个还没上传的文件必然失败（实测 exit 6）。
tmpl_rel="scripts/cloud/pool-config/projects.toml.tmpl"
tmpl_local=""
if [ -f ".wt/$card/$tmpl_rel" ]; then tmpl_local=".wt/$card/$tmpl_rel"
elif [ -f "$tmpl_rel" ]; then tmpl_local="$tmpl_rel"
fi
if [ -z "$tmpl_local" ]; then
  echo "✗ 本机找不到项目索引模板 $tmpl_rel（卡树与主树都没有）—— fail fast。" >&2
  rm -rf "$TMP"
  exit 6
fi
echo "=== 0.45/5 按云机仓库根渲染项目索引（模板来自 $tmpl_local）==="
scp $SSHOPTS -i "$KEY" "$tmpl_local" "$HOST:$pool_cfg_dst/projects.toml.tmpl" >/dev/null
if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
    "powershell -NoProfile -Command \"\$t = Join-Path '$pool_cfg_dst' 'projects.toml.tmpl'; if (-not (Test-Path \$t)) { exit 6 } ; \$c = [IO.File]::ReadAllText(\$t, [Text.Encoding]::UTF8) -replace '__REPO_ROOT__', '$cloud_dir' ; [IO.File]::WriteAllText((Join-Path '$pool_cfg_dst' 'projects.toml'), \$c, (New-Object System.Text.UTF8Encoding(\$false))) ; exit 0\""; then
  echo "✗ 云机渲染不了项目索引（$tmpl_rel）—— fail fast，门禁一步都没跑。" >&2
  echo "  处置：确认本机有 $tmpl_rel；或 TF_POOL_CFG_DIR 里放一份 root 已改成云机路径的 projects.toml。" >&2
  rm -rf "$TMP"
  exit 6
fi
echo "✓ 项目索引已按 $cloud_dir 渲染 → $pool_cfg_dst/projects.toml"
echo "=== 0.5/5 云机侧核对仓外配置（缺就不往下走）==="
if ! ssh $SSHOPTS -i "$KEY" "$HOST" "if exist \"$projects_toml\" (exit 0) else (exit 1)"; then
  echo "✗ 云机上找不到 TF_PROJECTS_TOML：$projects_toml（fail fast，门禁一步都还没跑）" >&2
  rm -rf "$TMP"
  exit 3
fi
echo "✓ 云机侧配置就位：$projects_toml"

echo "=== 1/5 导出卡树补丁（卡片 $card @ $short）==="
git -C ".wt/$card" add -A -N
# ★ 卡 E49 pass6 实测：`gates/last.json` / `gates/reuse.json` 是**入库文件**，且由 2/5 步
#   从本机显式播种到云机 —— 若补丁里也带着它们，`git apply` 会 `patch does not apply`
#   （整份补丁不生效 ⇒ 门禁跑在裸树上，14 条红全是假红）。⇒ 导出补丁必须排除这两件。
git -C ".wt/$card" diff HEAD --binary -- . \
  ':(exclude)gates/last.json' ':(exclude)gates/reuse.json' > "$TMP/$card.patch"
git -C ".wt/$card" reset -q
echo "补丁 $(wc -c < "$TMP/$card.patch") 字节 / $(grep -c '^diff --git' "$TMP/$card.patch") 个文件"

echo "=== 1.5/5 清掉云机上的残留门禁进程（上一趟 ssh 断了会留孤儿）==="
# ★ 卡 E49 实测：ssh 中途 `Connection reset` 后，远端 xdist worker 继续活着，
#   下一次 `git apply` 就会 `unable to unlink ... Permission denied`（文件被占）⇒ 补丁半途而废、
#   门禁在**坏树**上跑。所以对齐提交之前先把残留 python 全停，并确认树是干净的。
if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
    "powershell -NoProfile -Command \"Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 1; exit 0\""; then
  echo "✗ 云机上清残留进程失败 —— 不跑门禁（否则补丁会在被占的文件上失败）" >&2
  rm -rf "$TMP"
  exit 4
fi
echo "✓ 云机残留进程已清"
echo "=== 2/5 云机对齐到同一提交 + 清树（带 -x）+ 播种上一趟读数 ==="
# ★ `gates/last.json` / `gates/reuse.json` 是**入库文件**（骨架里有一份基线），
#   所以 `git clean -xfdq` 清不掉（clean 只清未跟踪/被忽略），`checkout` 还会把它恢复成
#   提交里那份**陈旧读数**，自指钉子（test_false_success_pins）就把那一趟当成「上一轮」；
#   反过来**删掉**也不行：审计 ⑫ 的台账 evidence 引着它们，钉子也要读它们。
#   ⇒ 唯一正确做法是**显式播种**一份绿的上一趟读数（卡 E49 实测出来的第三版）。
# ★ 卡 E49 pass8 实测的第四个坑：播种目录**不能**就是回传目录。
#   原来 seed 默认 `.wt/$card/gates`，而 `5/5` 又把云机那份读数 scp 回同一个目录 ⇒
#   第二趟就播了**上一趟的红读数**，自指钉子（真 last.json 必须是绿的）当场判红自己。
seed_dir="${TF_LAST_SEED:-gates/diag/seed-$card}"  # 播种源：只读，永远不被回传覆盖
for f in last.json reuse.json; do
  if [ ! -f "$seed_dir/$f" ]; then
    echo "✗ 本机没有可播种的 $seed_dir/$f —— 云机跑门禁需要一份**绿的上一趟**读数。" >&2
    echo "  处置：先在卡树跑一趟（或从主树 cp gates/$f .wt/$card/gates/），再重跑本脚本。" >&2
    rm -rf "$TMP"
    exit 4
  fi
done
# ★ 播种前先验「这份读数是不是绿的」：`ok` 与每道门的 `exit_code` 都要干净。
#   拿红读数播种 ⇒ 云机上的自指钉子必红（`test_pin_gate_green_is_exit_codes_not_the_ok_field`），
#   而那条钉子红的是「判据自己坏了」，最容易被误读成被测代码坏了。
if ! python -X utf8 - "$seed_dir/last.json" <<'PYCHECK'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
# 判据必须与门禁侧一致：只数**阻断门**（scripts/run_gates.py 的 gates_ok() 就是这么判的）。
# blocking=False 的门（NOT RUN 渲染层、信息性门）不算红 —— 否则一份真·全绿读数会被当成红、云机根本起不来（卡 E60）。
bad = [g.get("name") for g in d.get("gates", []) if g.get("blocking", True) and g.get("exit_code") not in (0,)]
if bad or not d.get("ok"):
    print("✗ 播种源不是绿的：ok=%r 红门=%r" % (d.get("ok"), bad), file=sys.stderr)
    sys.exit(4)
gates = d.get("gates", [])
soft = [g.get("name") for g in gates
        if not g.get("blocking", True) and g.get("exit_code") not in (0,)]
msg = "✓ 播种源是绿的：%d 道阻断门全 exit_code=0（rev=%s）" % (len(gates) - len(soft), d.get("rev"))
if soft:
    msg += "；不计红的非阻断门：" + "、".join(soft)
print(msg)
PYCHECK
then
  echo "✗ $seed_dir/last.json 不是绿的 —— 不许拿红读数当「上一趟」。" >&2
  echo "  处置：在卡树把门禁跑绿，再把那份 last.json + reuse.json 复制到 $seed_dir/（该目录 gitignored）。" >&2
  rm -rf "$TMP"
  exit 4
fi
if ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git checkout -f --detach $head && git clean -xfdq && git log --oneline -1"; then
  echo "✗ 云机对齐 $head 失败 —— 不跑门禁" >&2
  rm -rf "$TMP"
  exit 4
fi
for f in last.json reuse.json; do
  scp $SSHOPTS -i "$KEY" "$seed_dir/$f" "$HOST:$cloud_dir/gates/$f" >/dev/null
done
if ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && if exist gates\last.json (if exist gates\reuse.json (exit 0) else (exit 4)) else (exit 4)"; then
  echo "✗ 云机上没有播种成功的 gates/last.json + gates/reuse.json —— 不跑门禁" >&2
  rm -rf "$TMP"
  exit 4
fi
echo "✓ 上一趟读数已从 $seed_dir 播种（提交里那份基线被覆盖）"
echo "=== 2.5/5 断言云机树就是目标提交（防「陈旧树判新队列」，卡 E54）==="
# ★ 卡 E54 实测：云机停在旧提交 050fa3d（那笔的 trailer 还是 T-AG503，后来 amend 成 T-AG504）时，
#   `tests/test_wb_plan.py` 会报「卡 E53：已落却仍 pending」并把结论写进 last.json 的 rev ——
#   看着像代码缺陷，其实是**树陈旧**。⇒ 开跑前 fail closed，别让旧树说话。
remote_head="$(ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git rev-parse HEAD" 2>/dev/null | tr -d '\r')"
if [ "$remote_head" != "$head" ]; then
  echo "✗ 云机 HEAD（$remote_head）≠ 目标提交（$head）—— 不许在陈旧树上跑门禁。" >&2
  echo "  处置：确认 0/5 的 bundle 已 fetch（或删 C:/eng/gates/last.json 后重跑），别手工 checkout。" >&2
  rm -rf "$TMP"
  exit 7
fi
echo "✓ 云机 HEAD == 目标提交（${head:0:7}）"

echo "=== 3/5 传补丁并应用 ==="
scp $SSHOPTS -i "$KEY" "$TMP/$card.patch" "$HOST:C:/card-$card.patch" >/dev/null
if [ ! -s "$TMP/$card.patch" ]; then
  echo "（补丁为空：卡树与主树同 HEAD，跳过 apply）"
elif ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git apply --binary C:/card-$card.patch && git status --porcelain | find /c /v \"\""; then
  echo "✗ 补丁应用失败 —— 不许在错的树上跑门禁（卡 E49 pass9 实测：空补丁只打一行 error 就继续跑）" >&2
  rm -rf "$TMP"
  exit 5
fi

echo "=== 3.5/5 同步 dev 依赖（集合来自仓里 pyproject 的 [dev]，版本钉 C:/pins.txt）==="
# ★ 卡 E54 实测：云机缺 hypothesis（`tests/test_properties.py` 收集期 ModuleNotFoundError），
#   因为 bootstrap 按手抄清单装包、不走 extras。⇒ 每趟开跑前按 extras 同步一次（已满足时只花几秒）。
if ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && \"C:/Program Files/Python312/python.exe\" -m pip install --quiet -e \".[dev]\" -c C:/pins.txt"; then
  echo "✗ 云机 dev 依赖同步失败 —— 不跑门禁（否则读数是「环境缺包」而不是代码结论）。" >&2
  echo "  处置：先跑 scripts/cloud/bootstrap.ps1 生成 C:/pins.txt，再重跑本脚本。" >&2
  rm -rf "$TMP"
  exit 8
fi
echo "✓ dev 依赖已按 pyproject 的 [dev] 同步"

echo "=== 4/5 云机跑全量门禁（端口段 $port；TF_PROJECTS_TOML 已注入）==="
start=$(date +%s)
# ★ 卡 E66（T-AG526）：记下**本机**起跑时刻，供 5/5 判断产物是不是这一趟写的。
#   不用云机时钟：云机断电重启后 RTC 不可信，而 `at` 正是云机本地时间写的。
started_at=$(date -Iseconds)
ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && $envset && \"C:/Program Files/Python312/python.exe\" -X utf8 scripts/run_gates.py && \"C:/Program Files/Python312/python.exe\" -X utf8 scripts/run_gates.py --seal" > "$TMP/gate.out" 2>&1
rc=$?
echo "门禁退出码=$rc 用时=$(( $(date +%s) - start ))s"
tail -6 "$TMP/gate.out"

echo "=== 5/5 回传 gates/last.json 与日志 ==="
mkdir -p ".wt/$card/gates/logs"
scp $SSHOPTS -i "$KEY" "$HOST:$cloud_dir/gates/last.json" ".wt/$card/gates/last.json" >/dev/null
scp $SSHOPTS -i "$KEY" "$HOST:$cloud_dir/gates/logs/*.log" ".wt/$card/gates/logs/" >/dev/null 2>&1
mkdir -p gates/diag
cp "$TMP/gate.out" "gates/diag/cloud-gate-$card.log"

# ★ 卡 E66（T-AG526）：上一趟的绿播种在云机同一个路径上，云机中途死掉时 5/5 搬回来的
#   就是那份播种 —— 它绿、host 是云机、rev 也对得上，落地链的 ok/host/tree 三道自检全过。
#   所以这里必须问一句「这是这一趟写的吗」，判不出来就**不许把它留在卡树里**。
if ! python -X utf8 tools/gate_pool.py check-product-fresh \
      ".wt/$card/gates/last.json" --started-at "$started_at" \
      --seed "$seed_dir/last.json"; then
  rm -f ".wt/$card/gates/last.json"
  echo "★★ 回传的 last.json 不是这一趟跑出来的（rc=$rc，起跑 $started_at）⇒ 已删除卡树里那份。" >&2
  echo "   处置：看一下 gates/diag/cloud-gate-$card.log 的 4/5 段；机器可能被关机/断线。" >&2
  echo "   日志照常保留：gates/diag/cloud-gate-$card.log" >&2
  rm -rf "$TMP"
  exit 9
fi
python -X utf8 -c "import json,sys; d=json.load(open('.wt/$card/gates/last.json',encoding='utf-8')); print('last.json ok=',d.get('ok'),'rev=',d.get('rev'),'host=',d.get('host'))"
# ★ CI 可复现性（判据 A 的可核读数）：host 是「这趟真在哪台机器跑的」的唯一凭证。
#   空 ⇒ 落地链 tools/pool/landing.py 会拒提交（「证明不了是云机跑的」）。
#   这里不改 rc：强制点在 tools/gate_pool.py::validate_cloud_return ③（已 fail closed）。
python -X utf8 -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); h=str(d.get('host') or ''); sys.exit(0 if h.strip() else 1)" ".wt/$card/gates/last.json" || {
  echo "★★ 回传的 last.json 没有非空 host 字段 ⇒ 证明不了是云机跑的 ⇒ 这趟不能直接落地。" >&2
  echo "   处置：确认云机上 scripts/run_gates.py 含 host 字段（判据 A：socket.gethostname()）。" >&2
}
echo "日志：gates/diag/cloud-gate-$card.log ；产物：.wt/$card/gates/"
rm -rf "$TMP"
exit "$rc"
