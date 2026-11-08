#!/usr/bin/env python
"""云门禁 profile 读取器 —— 把 scripts/cloud/profiles/<仓>.toml 摊平成 shell 能读的键值。

为什么要有它：run_gate.sh 里原来写死了一堆本仓假设（C:/eng、line/impl-v1、
TF_PROJECTS_TOML、models.whitelist.toml、gates/diag/seed-<卡>…）。抽成「仓无关骨架 + 每仓一份
profile」之后，骨架只认键、不认仓；这份脚本就是「键」的唯一读法。

用法（只在 run_gate.sh 与测试里调用）：
  python -X utf8 scripts/cloud/profile.py list
  python -X utf8 scripts/cloud/profile.py check --profile scripts/cloud/profiles/engineering.toml
  python -X utf8 scripts/cloud/profile.py dump  --profile <path> [--card <卡号>]
  python -X utf8 scripts/cloud/profile.py render --skeleton scripts/cloud/run_gate.sh
                                                --profile <path>

dump 的输出每行「键 US 值」（US = 0x1f），供 bash 直接读成变量。
列表类的键用 RS（0x1e）分隔。
值里不许有换行 —— 有就在 dump 阶段拒掉（否则 bash 那边会读串行）。

render 是给**人和测试**看的：把骨架里所有 `${P_<键>}` / `${P_<键>:-缺省}` 换成这份 profile 的值，
于是「这趟到底会执行什么」可以逐字读出来（`bash scripts/cloud/run_gate.sh --render`）。
它不执行、不联网；卡号渲染成符号 `$card`（产物路径里带卡号，渲染成某个具体卡号就没法当通用读数了）。
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

import tomllib

US = chr(31)  # 键 / 值 分隔
RS = chr(30)  # 列表元素分隔

SYNC_MODES = ("auto", "bundle", "peer", "none")
ENV_STYLES = ("pipe", "shell", "none")


class ProfileError(Exception):
    pass


def _load(path):
    path = Path(path)
    if not path.is_file():
        raise ProfileError("没有这份 profile：" + str(path))
    with open(path, "rb") as fh:
        try:
            return tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ProfileError(str(path) + " 不是合法 TOML：" + str(exc)) from exc


def _require(doc, key, path):
    val = doc.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ProfileError(path.name + " 缺 " + key + "（必填，非空字符串）")
    return val.strip()


def _strlist(doc, key, sep=" "):
    val = doc.get(key, [])
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise ProfileError(key + " 必须是字符串数组")
    return sep.join(val)


def _render(value, ctx):
    """把 {card} / {cloud_dir} / {repo_root} / {branch} / {seed_dir} 换掉。

    ★ 只做**整串占位符**替换，不碰 shell 的 ${VAR:-…} —— 那是运行时变量，必须原样留给 bash。
    """
    out = value
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", v)
    return out


def _bool(doc, key, default):
    val = doc.get(key, default)
    return "1" if val else "0"


def _flatten(doc, path, ctx):
    name = _require(doc, "name", path)
    sync = doc.get("sync", {}) or {}
    cfg = doc.get("cloud_config", {}) or {}
    seed = doc.get("seed", {}) or {}
    prep = doc.get("prepare", {}) or {}
    gate = doc.get("gate", {}) or {}
    paths = doc.get("paths", {}) or {}
    env = doc.get("env", {}) or {}
    prod = doc.get("product", {}) or {}

    rows = [
        ("NAME", name),
        ("REPO_ROOT", _require(doc, "repo_root", path)),
        ("CLOUD_DIR", _require(doc, "cloud_dir", path)),
        ("BRANCH", _require(doc, "branch", path)),
        # 有没有「卡树」（本仓的 .wt/<卡>）。没有 ⇒ 补丁 / 播种 / 回传产物三步空转。
        ("CARDTREE", _bool(doc, "card_tree", True)),
        ("SYNC_MODE", str(sync.get("mode", "auto"))),
        ("BUNDLE_TARGET", str(sync.get("bundle_target", "C:/inc.bundle"))),
        ("PEER_FETCH_FROM", str(sync.get("peer_fetch_from", ""))),
        ("REQUIRES_ENV", _strlist(doc, "requires_env")),
        ("REQUIRED_REMOTE", _strlist(doc, "required_remote")),
        ("CFG_SOURCE_DEFAULT", str(cfg.get("source_default", ""))),
        ("CFG_STAGE_DIR", str(cfg.get("stage_dir", ""))),
        ("CFG_DEST", str(cfg.get("dest", ""))),
        # ★ 独立复核 D2：骨架用 IFS=$'\036' 拆这几个列表。这里若按空格拼，
        #   "projects.toml projects.toml.tmpl models.whitelist.toml" 会被读成**一项**，
        #   于是 0.4/5 的 keep 白名单只剩最后一项、其余被 Remove-Item 删掉（实测过）。
        ("CFG_ALLOW", _strlist(cfg, "allow", RS)),
        ("CFG_KEEP", _strlist(cfg, "keep", RS)),
        ("CFG_TEMPLATE", str(cfg.get("template", ""))),
        ("SEED_DIR_DEFAULT", str(seed.get("dir_default", ""))),
        ("SEED_FILES", _strlist(seed, "files", RS)),
        ("SEED_REQUIRE_GREEN", _bool(seed, "require_green", False)),
        ("PREPARE_CMD", str(prep.get("cmd", ""))),
        ("PREPARE_EXIT", str(prep.get("exit_code", 8))),
        ("PREPARE_HINT", str(prep.get("hint", ""))),
        ("GATE_CMD", str(gate.get("cmd", ""))),
        ("GATE_TIMEOUT_DEFAULT", str(gate.get("timeout_default", 3600))),
        # 产物清单：每项 "<远端路径>|<本地路径>"，骨架按顺序各自尽力取回（清单 R10）。
        ("ARTIFACTS", _strlist(gate, "artifacts", RS)),
        ("STALE_PROCS", str(gate.get("stale_procs", "python"))),
        ("PATCH_EXCLUDES", _strlist(gate, "patch_excludes", RS)),
        ("GATE_REMOTE_LOG", str(paths.get("remote_log", ""))),
        ("GATE_LOCAL_LOG", str(paths.get("local_log", ""))),
        # ★ 卡 E90：云机那份是**裸输出**，本机那份带 `# rc=…` 头；
        #   两者落到同一路径时 scp 会把头冲掉。
        #   缺省（空）＝与 local_log 同路径（旧行为），给了就另落一处。
        ("GATE_REMOTE_LOCAL_LOG", str(paths.get("remote_local_log", ""))),
        ("CFG_PLACEHOLDER", str(cfg.get("placeholder", ""))),
        ("ENV_STYLE", str(env.get("style", "pipe"))),
        ("ENV_LINES", _strlist(env, "lines", RS)),
        ("ENV_FORWARD", _strlist(env, "forward")),
        ("PRODUCT_FRESH", _bool(prod, "fresh_check", False)),
        ("PRODUCT_READOUT_CMD", str(prod.get("readout_cmd", ""))),
        ("PRODUCT_HOST_CHECK", _bool(prod, "host_check", False)),
    ]
    defaults = env.get("defaults", {}) or {}
    for var, val in defaults.items():
        rows.append(("ENVDEFAULT", str(var) + "=" + str(val)))

    out = []
    for key, val in rows:
        if not isinstance(val, str):
            val = str(val)
        if "\n" in val or "\r" in val:
            raise ProfileError(
                path.name + " 的 " + key + " 里有换行 —— bash 那边会读串行，改成一个命令一行"
            )
        out.append((key, _render(val, ctx)))
    return out


def _ctx(doc, args):
    return {
        "card": args.card or "",
        "cloud_dir": args.cloud_dir or doc.get("cloud_dir", ""),
        "repo_root": doc.get("repo_root", ""),
        "branch": doc.get("branch", ""),
        "seed_dir": (doc.get("seed", {}) or {}).get("dir_default", "").replace(
            "{card}", args.card or ""
        ),
    }


def cmd_dump(args):
    path = Path(args.profile)
    doc = _load(path)
    for key, val in _flatten(doc, path, _ctx(doc, args)):
        sys.stdout.write(key + US + val + "\n")
    return 0


# 骨架里引用 profile 的唯一写法：${P_<键>} 或 ${P_<键>:-缺省}。
# ★ 只认 P_ 前缀 —— bash 自己的变量（${env_defaults[@]}、${!var:-}、${cloud_dir}…）一个都不碰。
_PSLOT = re.compile(r"\$\{(P_[A-Z0-9_]+)(?::-([^}]*))?\}")


def cmd_render(args):
    """把骨架 + 这份 profile 渲染成一份**可读的平铺脚本**（不执行）。

    为什么要有它：判断「这趟门禁会怎么做」过去靠读脚本里的字面量；字面量搬进 profile 之后，
    唯一还读得懂的形态就是「渲染结果」。它也是 tests/test_cloud_sync.py 里那些
    「engineering 这趟必须成立」的断言的 haystack —— 断言口径没变，只是值来自 profile。
    """
    path = Path(args.profile)
    doc = _load(path)
    skel_path = Path(args.skeleton)
    if not skel_path.is_file():
        raise ProfileError("没有这份骨架：" + str(skel_path))
    text = skel_path.read_bytes().decode("utf-8")

    # 卡号渲染成符号 $card：产物路径里都带卡号，渲染成某张具体的卡就不是通用读数了。
    args.card = "$card"
    rows = dict(_flatten(doc, path, _ctx(doc, args)))

    # rows 的键是 "BRANCH"，骨架里写的是 "${P_BRANCH}" —— 去掉前缀再查。
    def _val(m):
        return rows.get(m.group(1)[2:])

    missing = sorted({m.group(1) for m in _PSLOT.finditer(text) if _val(m) is None})

    def _sub(m):
        val = _val(m)
        if val is None:
            return m.group(0)
        # 空值渲染成 "" —— 否则 '${P_PRODUCT_READOUT_CMD} || echo …' 会留成 '  || echo …'，
        # 渲染结果连 bash -n 都过不去（这份渲染产物要能被语法检查，才当得了判据的 haystack）。
        return '""' if val == "" else val

    out = _PSLOT.sub(_sub, text)
    sys.stdout.write(out)
    if missing:
        sys.stderr.write("⚠ 骨架引用了 profile 没给的键（原样留着）：" + ", ".join(missing) + "\n")
    return 0


def cmd_list(args):
    here = Path(args.profiles_dir)
    for p in sorted(here.glob("*.toml")):
        doc = _load(p)
        cells = [p.stem, str(doc.get("cloud_dir", "?")), str(doc.get("branch", "?"))]
        sys.stdout.write("\t".join(cells) + "\n")
    return 0


def cmd_check(args):
    path = Path(args.profile)
    doc = _load(path)
    rows = _flatten(doc, path, _ctx(doc, args))
    keys = [k for k, _ in rows]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ProfileError(path.name + " 里有重复键：" + repr(dup))
    mode = str((doc.get("sync", {}) or {}).get("mode", "auto"))
    if mode not in SYNC_MODES:
        raise ProfileError(path.name + " 的 sync.mode 只能是 " + " / ".join(SYNC_MODES))
    style = str((doc.get("env", {}) or {}).get("style", "pipe"))
    if style not in ENV_STYLES:
        raise ProfileError(path.name + " 的 env.style 只能是 " + " / ".join(ENV_STYLES))
    for required in ("name", "repo_root", "cloud_dir", "branch"):
        _require(doc, required, path)
    sys.stdout.write("OK " + path.name + "：共 " + str(len(rows)) + " 个键，无重复、无换行\n")
    return 0


def main(argv):
    # ★ Windows 下 sys.stdout 默认把 \n 翻成 \r\n —— bash 那边 read 会把 \r 吃进值里。
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(newline="\n")
    ap = argparse.ArgumentParser(description="云门禁 profile 读取器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dump", help="摊平成「键 US 值」行")
    d.add_argument("--profile", required=True)
    d.add_argument("--card", default="")
    d.add_argument("--cloud-dir", default="")
    d.set_defaults(func=cmd_dump)

    rd = sub.add_parser("render", help="把骨架 + profile 渲染成平铺脚本（不执行）")
    rd.add_argument("--skeleton", required=True)
    rd.add_argument("--profile", required=True)
    rd.add_argument("--cloud-dir", default="")
    rd.set_defaults(func=cmd_render)

    ls = sub.add_parser("list", help="列出 profiles/ 下的仓")
    ls.add_argument("--profiles-dir", default=str(Path(__file__).resolve().parent / "profiles"))
    ls.set_defaults(func=cmd_list)

    ck = sub.add_parser("check", help="校验一份 profile")
    ck.add_argument("--profile", required=True)
    ck.add_argument("--card", default="")
    ck.add_argument("--cloud-dir", default="")
    ck.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ProfileError as exc:
        sys.stderr.write("✗ " + str(exc) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
