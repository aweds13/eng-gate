#!/bin/bash
# 云门禁骨架：把一张卡的「落地门禁」搬到云机跑、产物回传。
# 卡 E35 入库；云门禁泛用化（让第二个仓也能跑）时抽成「仓无关骨架 + 每仓一份 profile」。
#
# 用法（本机 Git Bash）：
#   CLOUD_HOST=administrator@<云机> [TF_CLOUD_PROFILE=scripts/cloud/profiles/<仓>.toml] \
#     bash scripts/cloud/run_gate.sh <卡号> [端口段]
#
# 这份文件只认**键**，不认仓：仓名 / 云机目录 / 分支 / 跑什么门禁 / 产物在哪 / 要不要播种，
# 全部来自 `scripts/cloud/profiles/<仓>.toml`（唯一的读法是 scripts/cloud/profile.py dump）。
# 不给 TF_CLOUD_PROFILE 时用同目录的 profiles/engineering.toml —— 本仓的历史调用点原样可用。
#
# 为什么在库里：原来这份脚本住在 gates/diag/，而 `.gitignore` 的 `gates/diag/*` 把整个目录
# 忽略 ⇒「云机怎么跑门禁」只存在某台机器的磁盘上，换台机器就没有这件事。现在它是被 review 的源码。
#
# 三条口径（卡 E35 判据）：
#   ① 清树用 `git clean -xfdq`（**带 -x**）。不带 -x 时上一趟的 `gates/last.json` 与
#      `gates/logs/` 会留在盘上（它们是被忽略文件），被这一趟读成「上一轮的判定」⇒
#      自指钉子（test_false_success_pins / test_gates_reuse_line）必红。实测踩过。
#   ② 跑之前**断言 `gates/last.json` 不存在**：存在就报错退出（绝不静默沿用上一趟的判定）。
#   ③ 仓外配置显式注入，**缺了就报错不跑**（fail fast）—— 不许「跑一半发现没配」。
#
# 前提：card_tree = true 的仓，卡树 `.wt/<卡号>` 已 realign 到主树 HEAD；
#       云机 SSH 可用（~/.ssh/id_ed25519_cloud）。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"

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

# ---------------------------------------------------------------- 渲染（可读、可测；不执行）
# `--render` 把这份骨架 + 一份 profile 摊成**平铺脚本**打到 stdout：所有 `${P_<键>}` 被换成本仓的值。
# 为什么要有它：判据（tests/test_cloud_sync.py）问的是「engineering 这趟端到端会怎么做」，
# 而 engineering 的值现在住在 profiles/engineering.toml —— 渲染结果就是那个问题的答案。
# 它不联网、不执行、不需要任何环境变量（缺 profile 才退 2）。
if [ "${1:-}" = "--render" ]; then
  render_profile="${TF_CLOUD_PROFILE:-$HERE/profiles/engineering.toml}"
  python -X utf8 "$HERE/profile.py" render --skeleton "$0" --profile "$render_profile" --cloud-dir "${CLOUD_DIR:-}"
  exit $?
fi

# ---------------------------------------------------------------- profile：仓专属的那一半
# 骨架不许知道「仓里有什么」。这份 TOML 说的是「这个仓在云机上怎么跑」：
#   云机目录 / 分支 / 同步方式 / 仓外配置供给 / 播种 / 开跑前准备 / 门禁命令 / 产物清单。
# 键的读法只有一份：scripts/cloud/profile.py dump 打「键 US 值」行，这里逐行读成 P_<键>。
PROFILE="${TF_CLOUD_PROFILE:-$HERE/profiles/engineering.toml}"
card="${1:?用法: CLOUD_HOST=<云机> bash scripts/cloud/run_gate.sh <卡号> [端口段]}"
port="${2:-9361}"

if [ ! -f "$PROFILE" ]; then
  echo "✗ 找不到 profile：$PROFILE（不会拿别的仓的假设替你猜）" >&2
  echo "  处置：TF_CLOUD_PROFILE=scripts/cloud/profiles/<仓>.toml 重跑；现有几份见 profile.py list" >&2
  exit 2
fi
if ! dump="$(python -X utf8 "$HERE/profile.py" dump --profile "$PROFILE" --card "$card" --cloud-dir "${CLOUD_DIR:-}")"; then
  echo "✗ profile 读不出来：$PROFILE（原话见上）—— fail fast，门禁一步都没跑。" >&2
  exit 2
fi
env_defaults=()
while IFS=$'\037' read -r pkey pval; do
  [ -n "$pkey" ] || continue
  case "$pkey" in
    ENVDEFAULT) env_defaults+=("$pval") ;;
    *) printf -v "P_$pkey" '%s' "$pval" ;;
  esac
done <<< "$dump"

cloud_dir="${CLOUD_DIR:-${P_CLOUD_DIR:-}}"
branch="${P_BRANCH:-}"
cardtree="${P_CARDTREE:-1}"
if [ -z "$cloud_dir" ] || [ -z "$branch" ]; then
  echo "✗ profile 缺 cloud_dir / branch：$PROFILE" >&2
  exit 2
fi
# ★ 独立复核 D4：这两份日志路径是 profile 的必填键，缺了在 4/5 才知道就太晚——
#   0/5–3.5/5 的 ssh / scp / pip 已经全跑完（十几分钟白跑）。开跑前就判，缺了直接退 2。
if [ -z "${P_GATE_REMOTE_LOG:-}" ] || [ -z "${P_GATE_LOCAL_LOG:-}" ]; then
  echo "✗ profile 缺 paths.remote_log / paths.local_log：$PROFILE" >&2
  echo "  这两份是 4/5 的现场落点（云机一份、本机一份），缺了门禁跑了也没处看。" >&2
  exit 2
fi

# ---------------------------------------------------------------- ③ fail fast：仓外配置
# 哪些环境变量是「仓外配置」（缺了云机上会集体红），由 profile 的 requires_env 声明。
# 缺一个就退 2，且报错里必须出现**键名** —— 现场要能一眼看出是配置没给、不是代码坏。
for var in ${P_REQUIRES_ENV:-}; do
  # ★ N1（独立复核）：空列表（openmaic 的 requires_env）渲染成字面 ""，
  #   于是这里的变量名是空的。${!var:-} 对空变量名只会往 stderr 吐一句
  #   invalid variable name 就跳过（不是报错）⇒ if 判假、循环体跳过、脚本继续跑，
  #   守卫「在」但不「咬」， bash -n 也照不到。所以先把空变量名挡掉。
  [ -n "$var" ] || continue
  if [ -z "${!var:-}" ]; then
    echo "✗ 缺 $var：仓外配置必须显式注入（卡 E35 判据 3，fail fast）。" >&2
    echo "  它不在仓里；缺了云机上依赖它的用例会集体红 —— 那是配置没给，不是代码坏。" >&2
    echo "  例：$var=<路径> bash scripts/cloud/run_gate.sh $card" >&2
    echo "  （这条要求来自 $(basename "$PROFILE") 的 requires_env）" >&2
    exit 2
  fi
done

KEY="$HOME/.ssh/id_ed25519_cloud"
# ★ CI 可复现性：**不给默认云机**。原来这里带一个默认地址（变配前的公网 IP，早已
#   失效，见 docs/subsystems/ci/云门禁机.md §1 的历史读数）—— 等于「没配就默默去连
#   一台死机器」，失败现场看起来像网络问题、不像配置问题。改成 fail fast。
#   exit 9 = 没配云机（与 exit 2 缺仓外配置并列，都是「配置没给、不是代码坏」）。
if [ -z "${CLOUD_HOST:-}" ]; then
  echo "✗ 缺 CLOUD_HOST：云机地址必须显式注入（不再有已失效的默认 IP）。" >&2
  echo "  例：CLOUD_HOST=administrator@<云机地址> bash scripts/cloud/run_gate.sh <卡号> [端口段]" >&2
  exit 9
fi
HOST="$CLOUD_HOST"
# ★ 卡 E84（T-AG591）：一趟门禁约 15 分钟，长连接空闲时会被中间设备剪断 ——
#   实测 A366 那趟本机收到 rc=255，而云机上 22 门已经跑完（产物就在盘上）。
#   ⇒ 加保活：30 s 一次探测、容忍 6 次（≈3 分钟）不发包也不判定断线。
SSHOPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes"
SSHOPTS="$SSHOPTS -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -o TCPKeepAlive=yes"
TMP="$(mktemp -d)"
# ★ 卡 E49 pass7 实测：原来这两行按**调用者 cwd**（主仓）取提交 —— 主仓一往前走，
#   云机就 checkout 到主仓的 HEAD，而补丁是拿**卡树**的 HEAD 做的 diff ⇒
#   `git apply` 报 `patch failed: 复盘/交接-重构进度.md:3871`，门禁跑在错的树上。
#   ⇒ 提交号必须从卡树取（card_tree = false 的仓没有卡树，用云机自己那份树）。
if [ "$cardtree" = "1" ]; then
  head="$(git -C ".wt/$card" rev-parse HEAD)"
  short="$(git -C ".wt/$card" rev-parse --short HEAD)"
else
  # 没有卡树就没有「目标提交」：两个变量留空（下面每一步都按 cardtree 空转）。
  read -r head short <<< " "
fi

# ---------------------------------------------------------------- 云机侧环境注入串
# ★ 卡 E49 落地后回归（云机 pass9）：**不许注入 TF_MODEL_REGISTRY** ——
#   注册表的真源是仓里那份 tools/pool/model-registry.toml（含 [[model]] 与
#   [pool.codearts] 引用）；仓外 models.whitelist.toml 只描述码道池（[[approved]]）。
#   把它当注册表注入，load_registry() 就找不到任何 [[model]] 条目 ⇒
#   test_model_registry / test_wb_dispatch 在云机集体红（实测 5 条）。
#   ⇒ 骨架只注入三类：端口段（骨架自己）、profile 声明的 requires_env、profile 的 env.forward
#   与 env.defaults（后者带「没给就用这个默认值」的语义），别的一概不注入。
#   注入语法由 profile 的 env.style 决定：pipe = 本仓那套 `set "K=V" && …`；none = 不注入。
envset=""
add_env() { envset="${envset:+$envset && }set \"$1=$2\""; }
if [ "${P_ENV_STYLE:-pipe}" != "none" ]; then
  add_env TF_GATE_PORT_BASE "$port"
  for var in ${P_REQUIRES_ENV:-}; do
    # ★ N1（同上）：空列表渲成字面 "" ⇒ 空变量名先挡掉，
    #   别让 ${!var:-} 只吐一句 invalid variable name 就把它拼进云机命令。
    [ -n "$var" ] || continue
    add_env "$var" "${!var:-}"
  done
  # 卡 E49：码道池条目是**从这份白名单派生**的（tools/pool/model_registry.py 的 CODEARTS_SOURCE_ENV）
  # —— 不注入就只剩 codebuddy 池，`test_model_registry` 的「跨池串用」「要有 codearts 条目」在云机必红。
  for var in ${P_ENV_FORWARD:-}; do
    # ★ N1（同上）：空列表的名字为空时也要先挡掉，不然 ${!var:-} 只会往 stderr 吐一句 invalid variable name。
    [ -n "$var" ] || continue
    if [ -n "${!var:-}" ]; then
      add_env "$var" "${!var:-}"
    fi
  done
  # env.defaults 的语义：环境里有就用环境的，没有就用 profile 给的默认值。
  for kv in ${env_defaults[@]+"${env_defaults[@]}"}; do
    dvar="${kv%%=*}"
    dval="${kv#*=}"
    add_env "$dvar" "${!dvar:-$dval}"
  done
fi

echo "=== 0/5 把主树这条分支同步到云机（目标 $cloud_dir）==="
sync_mode="${P_SYNC_MODE:-none}"
if [ "$sync_mode" = "bundle" ]; then
  git bundle create "$TMP/inc.bundle" "$branch" >/dev/null 2>&1
  echo "bundle $(wc -c < "$TMP/inc.bundle") 字节"
  scp $SSHOPTS -i "$KEY" "$TMP/inc.bundle" "$HOST:${P_BUNDLE_TARGET}" >/dev/null
  ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git fetch -q ${P_BUNDLE_TARGET} $branch && git rev-parse --short FETCH_HEAD"
elif [ "$sync_mode" = "peer" ]; then
  # 第二处 checkout：同一台机上从另一份 checkout 本地 fetch，不重复传包
  ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git fetch -q ${P_PEER_FETCH_FROM} $branch && git rev-parse --short FETCH_HEAD"
else
  echo "（profile 说这棵树不用推送：$cloud_dir 由云机侧自己维护）"
fi

# ---------------------------------------------------------------- 仓外配置供给（0.35/5 – 0.5/5）
# 落位约定：门禁工具常按「从 cwd 逐级向上找 infra/pool/<文件>」发现配置。云机上仓库在
# $cloud_dir ⇒ 对应位置由 profile 的 cloud_config.dest 给出。本机源目录默认值也在 profile 里
# （本仓那个默认值是登记过的债，见 docs/subsystems/ci/云门禁-可复现性清单.md §2 的 R2）。
pool_cfg_src="${TF_POOL_CFG_DIR:-${P_CFG_STAGE_DIR:-}}"
pool_cfg_dst="${TF_POOL_CFG_DST:-${P_CFG_DEST:-}}"
cfg_local="${TF_POOL_CFG_SOURCE_DIR:-${P_CFG_SOURCE_DEFAULT:-}}"
cfg_allow=()
if [ -n "${P_CFG_ALLOW:-}" ]; then IFS=$'\036' read -r -a cfg_allow <<< "${P_CFG_ALLOW}"; fi
cfg_keep=()
if [ -n "${P_CFG_KEEP:-}" ]; then IFS=$'\036' read -r -a cfg_keep <<< "${P_CFG_KEEP}"; fi

echo "=== 0.35/5 把本机仓外配置推上云机（白名单，卡 E54）==="
# ★ 卡 E54 实测：原来这里整目录推 `*.toml`，把本机**私有账本** accounts.toml 与
#   **私有模型开关** model-switches.toml 一起推上云机 ⇒ 云机的判据输入被本机私有状态污染：
#   `test_pool_accounts.py` 两条「账本缺失要报错」判不出来（DID NOT RAISE / 走成崩溃）、
#   `test_wb_dispatch.py::test_account_auth_uses_the_profile_env_and_model` 被判「未授权模型」。
#   ⇒ 供给面收成**白名单**：门禁判据真正需要的只有项目索引（由模板渲染）与白名单里那几份。
if [ ${#cfg_allow[@]} -eq 0 ]; then
  echo "（profile 的 cloud_config.allow 是空的：这个仓不需要仓外配置）"
elif [ -d "$cfg_local" ]; then
  ssh $SSHOPTS -i "$KEY" "$HOST" "if not exist "$pool_cfg_src" mkdir "$pool_cfg_src"" >/dev/null 2>&1
  for f in "${cfg_allow[@]}"; do
    if [ ! -f "$cfg_local/$f" ]; then
      echo "✗ 本机缺 $cfg_local/$f —— 它是判据需要的输入（${cfg_allow[*]}），" >&2
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
# 铺之前先清掉落位上**不属于这份白名单**的旧文件：留着上一趟的私有账本等于让判据读本机状态。
if [ ${#cfg_keep[@]} -eq 0 ]; then
  echo "（profile 的 cloud_config.keep 是空的：这个仓不铺仓外配置）"
else
  keep_ps=""
  for k in "${cfg_keep[@]}"; do keep_ps="${keep_ps}${keep_ps:+,}'$k'"; done
  copy_ps=""
  for k in ${cfg_allow[@]+"${cfg_allow[@]}"}; do copy_ps="$copy_ps ; Copy-Item (Join-Path '$pool_cfg_src' '$k') '$pool_cfg_dst' -Force -ErrorAction SilentlyContinue"; done
  if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
      "powershell -NoProfile -Command \"if (-not (Test-Path '$pool_cfg_src')) { exit 5 } ; New-Item -ItemType Directory -Force '$pool_cfg_dst' | Out-Null ; Get-ChildItem -Path '$pool_cfg_dst' -File -ErrorAction SilentlyContinue | Where-Object { @($keep_ps) -notcontains \$_.Name } | Remove-Item -Force -ErrorAction SilentlyContinue$copy_ps ; exit 0\""; then
    echo "✗ 云机上没有配置源 $pool_cfg_src（或铺不动 $pool_cfg_dst）—— fail fast，门禁一步都没跑。" >&2
    echo "  处置：本机 scp 那几份仓外配置上去（scp <配置目录>/*.toml $HOST:$pool_cfg_src/），" >&2
    echo "  或用 TF_POOL_CFG_DIR 指到已在云机上的那份。见 docs/subsystems/ci/云门禁机.md 的「仓外配置」表。" >&2
    rm -rf "$TMP"
    exit 5
  fi
  echo "✓ 配置已铺：$pool_cfg_src → $pool_cfg_dst"
fi

# 项目索引里 `root` 是**绝对路径**：开发机那份指着本机的仓目录（带盘符的绝对路径）。
# 原样 scp 到云机 ⇒ `[project.<name>].root` 不存在 ⇒ 项目守卫拒（宁拒不许猜）⇒
# 云机上一片「项目索引读不了」。所以项目索引**由仓内模板渲染**（根换成云机的仓库目录）。
#
# ★ 模板**从本机传**、不从云机 checkout 读：模板本身可能是这张卡树里的新文件（卡 E49），
#   而补丁要 3/5 才 apply —— 让供给步去读一个还没上传的文件必然失败（实测 exit 6）。
tmpl_rel="${P_CFG_TEMPLATE:-}"
tmpl_local=""
echo "=== 0.45/5 按云机仓库根渲染项目索引（模板来自 $tmpl_rel）==="
if [ -z "$tmpl_rel" ]; then
  echo "（profile 的 cloud_config.template 是空的：这个仓没有要渲染的项目索引）"
else
  if [ -f ".wt/$card/$tmpl_rel" ]; then tmpl_local=".wt/$card/$tmpl_rel"
  elif [ -f "$tmpl_rel" ]; then tmpl_local="$tmpl_rel"
  fi
  if [ -z "$tmpl_local" ]; then
    echo "✗ 本机找不到项目索引模板 $tmpl_rel（卡树与主树都没有）—— fail fast。" >&2
    rm -rf "$TMP"
    exit 6
  fi
  scp $SSHOPTS -i "$KEY" "$tmpl_local" "$HOST:$pool_cfg_dst/projects.toml.tmpl" >/dev/null
  if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
      "powershell -NoProfile -Command \"\$t = Join-Path '$pool_cfg_dst' 'projects.toml.tmpl'; if (-not (Test-Path \$t)) { exit 6 } ; \$c = [IO.File]::ReadAllText(\$t, [Text.Encoding]::UTF8) -replace '${P_CFG_PLACEHOLDER}', '$cloud_dir' ; [IO.File]::WriteAllText((Join-Path '$pool_cfg_dst' 'projects.toml'), \$c, (New-Object System.Text.UTF8Encoding(\$false))) ; exit 0\""; then
    echo "✗ 云机渲染不了项目索引（$tmpl_rel）—— fail fast，门禁一步都没跑。" >&2
    echo "  处置：确认本机有 $tmpl_rel；或 TF_POOL_CFG_SOURCE_DIR 里放一份 root 已改成云机路径的项目索引。" >&2
    rm -rf "$TMP"
    exit 6
  fi
  echo "✓ 项目索引已按 $cloud_dir 渲染 → $pool_cfg_dst/projects.toml"
fi
echo "=== 0.5/5 云机侧核对仓外配置（缺就不往下走）==="
required_remote="${P_REQUIRED_REMOTE:-}"
if [ -z "$required_remote" ]; then
  echo "（profile 的 required_remote 是空的：这个仓没有必须在云机上就位的仓外文件）"
else
  for rv in $required_remote; do
    if ! ssh $SSHOPTS -i "$KEY" "$HOST" "if exist \"${!rv:-}\" (exit 0) else (exit 1)"; then
      echo "✗ 云机上找不到 $rv：${!rv:-}（fail fast，门禁一步都还没跑）" >&2
      rm -rf "$TMP"
      exit 3
    fi
    echo "✓ 云机侧配置就位：$rv=${!rv:-}"
  done
fi

echo "=== 1/5 导出卡树补丁（卡片 $card @ $short）==="
# ★ 卡 E49 pass6 实测：`gates/last.json` / `gates/reuse.json` 是**入库文件**，且由 2/5 步
#   从本机显式播种到云机 —— 若补丁里也带着它们，`git apply` 会 `patch does not apply`
#   （整份补丁不生效 ⇒ 门禁跑在裸树上，14 条红全是假红）。⇒ 导出补丁必须排除 profile 列的这几件。
patch_excludes=()
if [ -n "${P_PATCH_EXCLUDES:-}" ]; then IFS=$'\036' read -r -a patch_excludes <<< "${P_PATCH_EXCLUDES}"; fi
if [ "$cardtree" = "1" ]; then
  git -C ".wt/$card" add -A -N
  git -C ".wt/$card" diff HEAD --binary -- . ${patch_excludes[@]+"${patch_excludes[@]}"} > "$TMP/$card.patch"
  git -C ".wt/$card" reset -q
  echo "补丁 $(wc -c < "$TMP/$card.patch") 字节 / $(grep -c '^diff --git' "$TMP/$card.patch") 个文件"
else
  : > "$TMP/$card.patch"
  echo "（profile 的 card_tree = false：没有卡树，不导出补丁）"
fi

echo "=== 1.5/5 清掉云机上的残留门禁进程（上一趟 ssh 断了会留孤儿）==="
# ★ 卡 E49 实测：ssh 中途 `Connection reset` 后，远端 worker 继续活着，
#   下一次 `git apply` 就会 `unable to unlink ... Permission denied`（文件被占）⇒ 补丁半途而废、
#   门禁在**坏树**上跑。所以对齐提交之前先把残留进程全停，并确认树是干净的。
if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
    "powershell -NoProfile -Command \"Get-Process ${P_STALE_PROCS:-python} -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 1; exit 0\""; then
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
seed_dir="${TF_LAST_SEED:-${P_SEED_DIR_DEFAULT:-}}"
seed_files=""
if [ -n "${P_SEED_FILES:-}" ]; then seed_files="$(printf '%s' "${P_SEED_FILES}" | tr '\036' ' ')"; fi
if [ "$cardtree" = "1" ] && [ -n "$seed_files" ]; then
  for f in $seed_files; do
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
  if [ "${P_SEED_REQUIRE_GREEN:-0}" = "1" ]; then
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
  fi
  if ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git checkout -f --detach $head && git clean -xfdq && git log --oneline -1"; then
    echo "✗ 云机对齐 $head 失败 —— 不跑门禁" >&2
    rm -rf "$TMP"
    exit 4
  fi
  for f in $seed_files; do
    scp $SSHOPTS -i "$KEY" "$seed_dir/$f" "$HOST:$cloud_dir/gates/$f" >/dev/null
  done
  # ★ 独立复核 D3：旧脚本这里验的是 last.json **与** reuse.json；
  #   泛用化时只验了 last.json，少一件也不会被发现（云机上那份陈旧 reuse.json 会被当成本轮的）。
  #   ⇒ 按 profile 声明的 seed.files 逐件验，一件都不许少（仍旧在 scp 之后验）。
  # ★ 卡 E93 实测（泛用化后第一个跑到这里的落地：E93 二跑 rc=2「云机上没有播种成功的」）：
  #   这两行原写法各有一个真缺陷。
  #   ① `gates\$f`：双引号里的 `\$` 是**字面美元符** ⇒ 拼出去的是 `gates$f`，cmd 当它不存在 ⇒ 恒退 4。
  #   ② `(if exist X (exit 0) else (exit 4)) && (if exist Y …)`：这种「命中就 exit 0」的链在 cmd 里
  #      **第二件永远不被判**（实测第二件不存在也返回 0）⇒ 校验形同虚设。
  #   ⇒ 改成「不存在就 exit 4」的链：存在不影响返回码、逐件都判、也不必再转义美元符。
  #   云机三态实测（C:/eng）：两件都在=0 / 第二件缺=4 / 第一件缺=4。
  seed_exist=""
  for f in $seed_files; do
    seed_exist="$seed_exist && (if not exist gates/$f (exit 4))"
  done
  if ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir$seed_exist"; then
    echo "✗ 云机上没有播种成功的（$seed_files）—— 不跑门禁" >&2
    rm -rf "$TMP"
    exit 4
  fi
  echo "✓ 上一趟读数已从 $seed_dir 播种（提交里那份基线被覆盖）"
else
  echo "（profile 说这个仓没有卡树 / 不播种：云机上的树保持原样）"
fi
echo "=== 2.5/5 断言云机树就是目标提交（防「陈旧树判新队列」，卡 E54）==="
# ★ 卡 E54 实测：云机停在旧提交 050fa3d（那笔的 trailer 还是 T-AG503，后来 amend 成 T-AG504）时，
#   `tests/test_wb_plan.py` 会报「卡 E53：已落却仍 pending」并把结论写进 last.json 的 rev ——
#   看着像代码缺陷，其实是**树陈旧**。⇒ 开跑前 fail closed，别让旧树说话。
if [ "$cardtree" != "1" ]; then
  echo "（没有卡树就没有「目标提交」：这一步空转）"
else
  remote_head="$(ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git rev-parse HEAD" 2>/dev/null | tr -d '\r')"
  if [ "$remote_head" != "$head" ]; then
    echo "✗ 云机 HEAD（$remote_head）≠ 目标提交（$head）—— 不许在陈旧树上跑门禁。" >&2
    echo "  处置：确认 0/5 的 bundle 已 fetch（或删云机上那份旧产物后重跑），别手工 checkout。" >&2
    rm -rf "$TMP"
    exit 7
  fi
  echo "✓ 云机 HEAD == 目标提交（${head:0:7}）"
fi

echo "=== 3/5 传补丁并应用 ==="
if [ "$cardtree" != "1" ]; then
  echo "（profile 的 card_tree = false：没有补丁要应用）"
else
  scp $SSHOPTS -i "$KEY" "$TMP/$card.patch" "$HOST:C:/card-$card.patch" >/dev/null
  if [ ! -s "$TMP/$card.patch" ]; then
    echo "（补丁为空：卡树与主树同 HEAD，跳过 apply）"
  elif ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git apply --binary C:/card-$card.patch && git status --porcelain | find /c /v \"\""; then
    echo "✗ 补丁应用失败 —— 不许在错的树上跑门禁（卡 E49 pass9 实测：空补丁只打一行 error 就继续跑）" >&2
    rm -rf "$TMP"
    exit 5
  fi
fi

echo "=== 3.5/5 同步依赖（集合与版本都来自 profile 的 prepare）==="
# ★ 卡 E54 实测：云机缺 hypothesis（`tests/test_properties.py` 收集期 ModuleNotFoundError），
#   因为 bootstrap 按手抄清单装包、不走 extras。⇒ 每趟开跑前按 profile 的 prepare 同步一次
#   （已满足时只花几秒）。prepare 的失败码也由 profile 给（默认 8）。
prepare_exit="${P_PREPARE_EXIT:-8}"
if [ -z "${P_PREPARE_CMD:-}" ]; then
  echo "（profile 的 prepare.cmd 是空的：这个仓不需要每趟同步依赖）"
elif ! ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && ${P_PREPARE_CMD}"; then
  echo "✗ 云机依赖同步失败 —— 不跑门禁（否则读数是「环境缺包」而不是代码结论）。" >&2
  echo "  ${P_PREPARE_HINT:-处置：看 profile 的 prepare.hint。}" >&2
  rm -rf "$TMP"
  exit "$prepare_exit"
fi
if [ -n "${P_PREPARE_CMD:-}" ]; then
  echo "✓ 依赖已按 profile 的 prepare 同步"
fi

echo "=== 4/5 云机跑全量门禁（端口段 $port；profile $(basename "$PROFILE")）==="
start=$(date +%s)
# ★ 卡 E66（T-AG526）：记下**本机**起跑时刻，供 5/5 判断产物是不是这一趟写的。
#   不用云机时钟：云机断电重启后 RTC 不可信，而 `at` 正是云机本地时间写的。
started_at=$(date -Iseconds)
# ★ 卡 E84（T-AG591）：4/5 的输出**先写云机盘上**再由本机取回。
#   实测（卡 A366 那趟）：原来是 `ssh … > "$TMP/gate.out"`，连接一断（rc=255）
#   本机只剩断点前那 1026 字节，而云机上 15 分钟的真输出还在盘上没人取。
#   改成「云机落盘 + 本机取回」后，传输断掉也还能补取。
gate_timeout="${TF_CLOUD_GATE_TIMEOUT:-3600}"
# profile 也可以给它自己那份默认超时（本仓就是 3600，与上面那个字面一致）；
# 显式给了 TF_CLOUD_GATE_TIMEOUT 就以显式的为准。
if [ -z "${TF_CLOUD_GATE_TIMEOUT:-}" ] && [ -n "${P_GATE_TIMEOUT_DEFAULT:-}" ]; then
  gate_timeout="${P_GATE_TIMEOUT_DEFAULT}"
fi
remote_out="${P_GATE_REMOTE_LOG:-}"
local_out="${P_GATE_LOCAL_LOG:-}"
if [ -z "$remote_out" ] || [ -z "$local_out" ]; then
  echo "✗ profile 缺 gate.remote_log / gate.local_log：$PROFILE" >&2
  rm -rf "$TMP"
  exit 2
fi
# 远端命令行：`cd → 环境注入 → 门禁命令`，输出重定向写在命令组外（门禁的退出码仍是这条 ssh 的退出码）。
remote_cmd="cd $cloud_dir"
if [ -n "$envset" ]; then remote_cmd="$remote_cmd && $envset"; fi
remote_cmd="$remote_cmd && ( ${P_GATE_CMD} ) > $remote_out 2>&1"
timeout "$gate_timeout" ssh $SSHOPTS -i "$KEY" "$HOST" "$remote_cmd" > "$TMP/gate.out" 2>&1
rc=$?
elapsed=$(( $(date +%s) - start ))
echo "门禁退出码=$rc 用时=${elapsed}s"

# ★ 卡 E84：ssh 一返回就**立刻**把本机这一侧落盘（早于下面任何 scp）。
#   传输中途断掉时，剩下的就只有这份；不许等 5/5 才写。
mkdir -p "$(dirname "$local_out")"
{
  echo "# rc=$rc elapsed=${elapsed}s started_at=$started_at timeout=${gate_timeout}s card=$card"
  cat "$TMP/gate.out"
} > "$local_out"
tail -6 "$local_out"

if [ "$rc" = "124" ]; then
  echo "✗ 云门禁超时（${gate_timeout}s）—— 云机可能挂住了。" >&2
  echo "  处置：用 TF_CLOUD_GATE_TIMEOUT 放宽后重跑；云机现场在下面 5/5 的取回结果里。" >&2
elif [ "$rc" = "255" ]; then
  echo "✗ 与云机的长连接断了（rc=255）—— 门禁**可能已在云机上跑完**，现场就在云机盘上。" >&2
  echo "  处置：5/5 会尽力取回；取不回就手工 scp $remote_out 与 $cloud_dir 下那几份产物。" >&2
fi

echo "=== 5/5 回传产物与日志（各项各自尽力，任何一项失败都不许中断其它）==="
artifacts=()
if [ -n "${P_ARTIFACTS:-}" ]; then IFS=$'\036' read -r -a artifacts <<< "${P_ARTIFACTS}"; fi
if [ "$cardtree" = "1" ]; then
  mkdir -p ".wt/$card/gates/logs"
fi
fetch() {
  local what="$1" src="$2" dst="$3" try=1
  while [ "$try" -le 3 ]; do
    if scp $SSHOPTS -i "$KEY" "$HOST:$src" "$dst" >/dev/null 2>&1; then
      return 0
    fi
    try=$((try + 1))
  done
  echo "  [取不回] $what（$src）—— 连试 3 次都没成；云机上那份还在，可手工 scp。" >&2
  return 0
}
# ★ 卡 E90（验收① 那趟发现的退化）：云机那份是**裸输出**，本机那份带 `# rc=…` 头。
#   两者若落到同一个路径，scp 会把头冲掉（grep -c '^# rc=' 变 0），断线复盘就少了「这趟是断是超时」。
#   ⇒ 云机原件另落一处（profile 的 gate.remote_log_local），本机现场保持原地。
remote_local="${P_GATE_REMOTE_LOCAL_LOG:-}"
if [ -z "$remote_local" ]; then remote_local="$local_out"; fi
mkdir -p "$(dirname "$remote_local")"
fetch "云机 4/5 输出" "$remote_out" "$remote_local"
for art in ${artifacts[@]+"${artifacts[@]}"}; do
  fetch "${art%%|*}" "${art%%|*}" "${art##*|}"
done

# ★ 卡 E66（T-AG526）：上一趟的绿播种在云机同一个路径上，云机中途死掉时 5/5 搬回来的
#   就是那份播种 —— 它绿、host 是云机、rev 也对得上，落地链的 ok/host/tree 三道自检全过。
#   所以这里必须问一句「这是这一趟写的吗」，判不出来就**不许把它留在卡树里**。
if [ "$cardtree" = "1" ] && [ "${P_PRODUCT_FRESH:-0}" = "1" ]; then
  if ! python -X utf8 tools/gate_pool.py check-product-fresh \
        ".wt/$card/gates/last.json" --started-at "$started_at" \
        --seed "$seed_dir/last.json"; then
    rm -f ".wt/$card/gates/last.json"
    echo "★★ 回传的 last.json 不是这一趟跑出来的（rc=$rc，起跑 $started_at）⇒ 已删除卡树里那份。" >&2
    echo "   处置：看一下 $local_out 的 4/5 段；机器可能被关机/断线。" >&2
    echo "   日志照常保留：$local_out" >&2
    rm -rf "$TMP"
    exit 9
  fi
  python -X utf8 -c "import json,sys; d=json.load(open('.wt/$card/gates/last.json',encoding='utf-8')); print('last.json ok=',d.get('ok'),'rev=',d.get('rev'),'host=',d.get('host'))"
  # ★ CI 可复现性（判据 A 的可核读数）：host 是「这趟真在哪台机器跑的」的唯一凭证。
  #   空 ⇒ 落地链 tools/pool/landing.py 会拒提交（「证明不了是云机跑的」）。
  #   这里不改 rc：强制点在 tools/gate_pool.py::validate_cloud_return ③（已 fail closed）。
  if [ "${P_PRODUCT_HOST_CHECK:-0}" = "1" ]; then
    python -X utf8 -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); h=str(d.get('host') or ''); sys.exit(0 if h.strip() else 1)" ".wt/$card/gates/last.json" || {
      echo "★★ 回传的 last.json 没有非空 host 字段 ⇒ 证明不了是云机跑的 ⇒ 这趟不能直接落地。" >&2
      echo "   处置：确认云机上的门禁入口往产物里写了 host 字段（判据 A：socket.gethostname()）。" >&2
    }
  fi
fi
# profile 可以给一条「这趟读数怎么抓」（例如从日志里抓一行汇总），失败不改 rc。
if [ -n "${P_PRODUCT_READOUT_CMD:-}" ]; then
  echo "—— profile 的读数："
  # 整串交给一个 shell：裸展开会按 IFS 把带空格的正则拆碎（OM2 实测 `grep: *(Test: No such file`）。
  bash -c "${P_PRODUCT_READOUT_CMD}" || echo "（读数命令没给出结论，原样保留上面 4/5 的输出）"
fi
echo "日志：$local_out"
rm -rf "$TMP"
exit "$rc"
