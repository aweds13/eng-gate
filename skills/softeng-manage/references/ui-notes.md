# ui-notes —— 界面判据（缺口回填）

> 来源：`复盘/INDEX.md` §5.2（结论为原文）。判据在 `tools/contrast_audit.py` / `tools/style_audit.py`，这里只写什么时候跑。

1. （缺口 UI1）面板/图表不许硬编码颜色，一律用主题令牌（`--dsw-alias-*`）；硬编码色在暗色下是白底刺眼条。
   操作：改面板 / 图表前先查现有令牌复用；体系有没有破例用 `python -X utf8 tools/style_audit.py` 体检，别肉眼估。
   证据：`复盘/卡/卡251-面板不硬编码颜色.md`、`复盘/设计基线-workbench与去AI味-T-G26.md`、`复盘/使用体验问题与修改台账.md`
2. （缺口 UI2）非文字元素（图标/边框/状态色）也要过对比度门，只查文字的对比度门会放过真正的暗雷。
   操作：图标 / 边框 / 状态色改动一并过 `python -X utf8 tools/contrast_audit.py`（候选令牌预演用 `python -X utf8 tools/candidate_contrast.py`），不只查文字。
   证据：`复盘/非文字对比度-T-G70.md`、`复盘/非文字悬停态判据-T-G103.md`、`复盘/视觉线地图.md`
