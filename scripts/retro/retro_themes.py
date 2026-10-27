"""一次性脚本：给 587 篇复盘分主题（分区，每篇只进一个主题）。
先把标题里的噪声剥掉（「复盘 · 」前缀、台账号/卡号/T-Gxxx/外包卡 NNN），再按词打分：
标题 6 分、路径 4 分、正文（h2 段名 + 抽取出的结论句）2 分。
产物：gates/diag/retro_theme.json（诊断产物，不入库）（rel -> theme）
用法：python -X utf8 scripts/retro/retro_themes.py [--show] [--only KEY]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIAG = ROOT / "gates" / "diag"
EX = DIAG / "retro_extract.json"
OUT = DIAG / "retro_theme.json"

# (key, 中文主题名, 标题词, 路径词, 正文词)
THEMES: list[tuple[str, str, tuple, tuple, tuple]] = [
    (
        "dsh",
        "DSH 插件与宿主",
        ("DSH", "dsh", "宿主", "工具箱", "插件协议", "面板三座位"),
        ("DSH", "dsh"),
        ("dsh", "宿主", "cordis", "client-modules"),
    ),
    (
        "ext",
        "外部系统接入与研究",
        (
            "禅道",
            "Trae",
            "MCP",
            "Obsidian",
            "外部",
            "外网",
            "生态",
            "研究",
            "Kimi",
            "K3",
            "GLM-5.3",
            "Kimi-K3",
            "配对码",
            "局域网",
        ),
        ("禅道", "Trae", "MCP", "Obsidian", "外部", "外网"),
        ("禅道", "trae", "obsidian", "github", "生态", "kimi"),
    ),
    (
        "panel",
        "工作台·面板·读数",
        (
            "面板",
            "读数",
            "工作台",
            "今日一页",
            "看板",
            "总览",
            "座位",
            "起停栈",
            "内嵌页",
            "首屏",
            "路由",
            "热表",
            "状态器",
            "桌面启动器",
            "启动器",
        ),
        ("panel", "wb_dash", "pipeline_view", "workbench", "dash", "wb_daily", "wb_status"),
        ("一份读数", "六块读数", "面板", "看板", "看门狗读数"),
    ),
    (
        "pool",
        "号池·派活·并发与收口",
        (
            "派活",
            "工人",
            "号池",
            "并发",
            "看门狗",
            "租约",
            "额度",
            "队列",
            "栅栏",
            "越界",
            "白名单",
            "巡检",
            "detach",
            "定时",
            "集成卡",
            "攒批",
            "波次",
            "守卫",
            "收口",
            "域不相交",
            "域检查",
            "串行",
            "切片",
            "薄壳",
            "续租",
            "门禁锁",
            "重跑",
            "派活器",
            "两卡",
            "八张",
            "十一张",
        ),
        ("pool", "dispatch", "wb_plan", "task.py", "land.py", "autoland", "gatelock", "pool"),
        ("派活", "工人", "号池", "租约", "并发", "栅栏", "收口"),
    ),
    (
        "gate",
        "门禁与判据",
        (
            "门禁",
            "判决",
            "钉子",
            "金丝雀",
            "假红",
            "假绿",
            "判据",
            "冒烟",
            "棘轮",
            "用例",
            "四要素",
            "去留",
            "假阳",
            "接缝",
            "预检",
            "seam",
            "reuse",
            "复用",
            "提速",
            "质量门",
            "验收机器化",
            "审计脚本",
            "人工验收",
            "端口",
        ),
        ("gate", "gates", "audit", "door", "check_", "seam"),
        ("门禁", "这道门", "钉子", "三值"),
    ),
    (
        "ledger",
        "台账·对账·证据与封存",
        (
            "台账",
            "对账",
            "封存",
            "证据",
            "指针",
            "编号",
            "坑总账",
            "不变量",
            "审计",
            "指纹",
            "凭据",
            "条款",
            "死账",
            "收敛",
            "档位",
        ),
        ("ledger", "trace", "reconcile", "seal", "evidence", "workbacklog"),
        ("台账", "对账", "封存", "证据指针"),
    ),
    (
        "visual",
        "视觉与界面",
        (
            "视觉",
            "令牌",
            "暗色",
            "对比度",
            "字号",
            "图标",
            "图表",
            "键盘",
            "设计基线",
            "审美",
            "融洽",
            "样式",
            "内联",
            "层次语言",
            "节奏",
            "排版",
            "渲染",
            "截图",
            "界面",
            "交互",
            "动线",
            "颜色",
            "字体",
            "去AI味",
            "骨架屏",
            "悬停态",
            "按钮",
            "文案",
        ),
        ("视觉", "ui", "render", "uihotmap", "contrast", "design", "uitextscan"),
        ("视觉线", "令牌", "对比度", "暗色"),
    ),
    (
        "product",
        "产品功能线（timeflow）",
        (
            "myday",
            "我的一天",
            "习惯",
            "复习",
            "学业",
            "团队视角",
            "备忘录",
            "年历",
            "收件箱",
            "番茄钟",
            "跨端",
            "手机",
            "离线",
            "同步",
            "左栏",
            "设置",
            "专注",
            "重复节奏",
            "视图",
            "分组",
            "标签",
            "附件",
            "提醒",
            "成绩",
            "课程",
            "通知",
            "打卡",
            "拖拽",
            "排序",
            "分组不存在",
        ),
        ("myday", "habit", "review", "study", "team", "uiflow", "sync"),
        ("我的一天", "习惯", "复习", "学业", "跨端"),
    ),
    (
        "framework",
        "框架与架构",
        (
            "框架",
            "架构",
            "术语",
            "契约",
            "分层",
            "事实层",
            "MVP",
            "独立仓",
            "扩展点",
            "骨架",
            "skills",
            "验证分层",
            "可控性",
            "并行度",
            "抽取清单",
            "居所",
            "自举",
            "项目书",
            "重构",
            "接口边界",
            "接缝重构",
            "事务",
            "插件",
            "ruff",
            "DESIGN",
            "LEARN",
        ),
        ("framework", "harness", "arch", "pipe"),
        ("框架", "架构", "契约", "事实层", "术语"),
    ),
    (
        "ai",
        "AI 协作·长任务·审查",
        (
            "长任务",
            "续跑",
            "反空转",
            "少读",
            "导读",
            "对抗",
            "复核",
            "GLM",
            "审查",
            "想问题",
            "问题清单",
            "长跑",
            "上下文",
            "接手",
            "主控",
            "记忆层",
            "外部做法",
            "问MCP",
            "引文回溯",
            "写事实",
            "AI",
        ),
        ("ai", "review", "protocol", "glm", "kimi"),
        ("长任务", "续跑", "对抗", "复核", "少读", "问题清单"),
    ),
    (
        "doc",
        "文档·口径·漂移",
        (
            "文档",
            "口径",
            "漂移",
            "债务",
            "重整",
            "加注",
            "一致性",
            "docs",
            "更正",
            "叙事",
            "话术",
            "共享文档",
            "陈旧",
            "过期",
            "去幽灵",
            "投影",
            "命令表",
            "文案清理",
            "说明书",
        ),
        ("docs", "doc"),
        ("文档", "口径", "漂移"),
    ),
    ("handoff", "交接单与现场交接", ("交接", "CHECKPOINT", "新窗口"), ("交接.d",), ("交接",)),
    (
        "defect",
        "缺陷与事故根因",
        (
            "根因",
            "缺陷",
            "崩",
            "500",
            "漏档",
            "假阳性",
            "时区",
            "跨天",
            "幂等",
            "定时炸弹",
            "误判",
            "误杀",
            "空渲染",
            "星号",
            "409",
            "死代码",
            "内存",
            "失败",
            "坏了",
            "脏",
            "幽灵行",
            "幻影",
        ),
        (),
        ("根因", "缺陷", "复现", "假阳性"),
    ),
]

DEFAULT = ("misc", "其他（未归类）")

NOISE = [
    re.compile(r"[（(]\s*台账号\s*T-AG?\d+[^）)]*[)）]"),
    re.compile(r"台账号\s*T-AG?\d+"),
    re.compile(r"T-AG?\d+"),
    re.compile(r"外包卡\s*\d+[ab]?"),
    re.compile(r"集成者卡\s*\d+[a-f]?"),
    re.compile(r"并发(作者)?卡\s*\d+"),
    re.compile(r"卡\s*A?\d+"),
    re.compile(r"^复盘\s*[·:：]\s*"),
    re.compile(r"^卡\s*A?\d+\s*[—\-·]+\s*"),
]


def clean_title(s: str) -> str:
    for rx in NOISE:
        s = rx.sub(" ", s)
    return s


def score(row: dict, tk: tuple, pk: tuple, bk: tuple) -> tuple[int, list[str]]:
    title = clean_title(row["title"])
    stem = clean_title(row["rel"].rsplit("/", 1)[-1])
    body = (
        " ".join(row.get("h2", []))
        + " "
        + row.get("hdr_concl", "")
        + " "
        + " ".join(row.get("sent", []))
    )
    s, hits = 0, []
    for k in tk:
        if k in title or k in stem:
            s += 6
            hits.append(f"T:{k}")
    for k in pk:
        if k in row["rel"]:
            s += 4
            hits.append(f"P:{k}")
    for k in bk:
        if k in body:
            s += 2
            hits.append(f"B:{k}")
    return s, hits


def classify(row: dict) -> tuple[str, str, list[str]]:
    if row["dir"] == "交接.d":
        return ("handoff", "交接单与现场交接", ["dir"])
    best, best_s, best_hits = DEFAULT, 0, []
    pri = {k: i for i, (k, *_rest) in enumerate(THEMES)}
    for key, name, tk, pk, bk in THEMES:
        s, hits = score(row, tk, pk, bk)
        if s > best_s or (s == best_s and s > 0 and pri[key] < pri.get(best[0], 99)):
            best, best_s, best_hits = (key, name), s, hits
    return best[0], best[1], best_hits


def main() -> int:
    d = json.loads(EX.read_text(encoding="utf-8"))
    rows = d["rows"]
    theme_of, names, why = {}, {}, {}
    cnt = Counter()
    per = defaultdict(list)
    for r in rows:
        key, name, hits = classify(r)
        theme_of[r["rel"]] = key
        names[key] = name
        why[r["rel"]] = hits
        cnt[key] += 1
        per[key].append(r)
    OUT.write_text(
        json.dumps(
            {"theme_of": theme_of, "names": names, "why": why}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    print(f"total {len(rows)}")
    for key, n in cnt.most_common():
        print(f"{n:4d}  {key:10s} {names[key]}")
    show = "--show" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    if show or only:
        for key in cnt:
            if only and key != only:
                continue
            print(f"\n########## {key} {names[key]} ({cnt[key]})")
            for r in per[key]:
                print(f"  {r['rel'][3:]:46s} || {clean_title(r['title'])[:52]}  {why[r['rel']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
