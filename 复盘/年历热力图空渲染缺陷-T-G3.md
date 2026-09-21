# 复盘 · 年历热力图一直渲染空（T-G3）

> 性质：**缺陷复盘**（问题 / 怎么发现的 / 为什么会漏掉 / 修法 / 教训）。
> 上游：G 批 · T-G1（把维度词表从写死改成后端配置）—— 这个缺陷是在**换接口时暴露**的。
> 结果：年历热力图从"永远灰"变成"真的按当天数值上色"；并补了一条能抓住它的断言。

---

## 一、问题

统计页那张「时间热力图（近一年）」**从来没有显示过数据**：

```js
// 旧代码（HEAD~1 的 src/web/index.html）
const HM_METRICS=[
  ['focus','专注','focus_minutes'],['manual','手动投入','manual_minutes'],
  ['review','复习','review_count'],['output','产出','output_count'],
  ['debt','债务（欠多少）','debt_count']];
...
const values=cells.map(c=>Number(c[metric])||0);        // metric === 'focus'
const v=map.has(iso)?Number(map.get(iso)[metric])||0:0; // 同上
```

后端的 `HeatmapCell` 字段叫 `focus_minutes` / `manual_minutes` / `review_count` / `output_count` /
`debt_count`，而界面传下去的是**短 id**（`focus`、`review`…）。`HM_METRICS` 的第三个元素
（真字段名）**从来没被用过**：

```powershell
node -e "const cells=[{date:'2026-09-20',focus_minutes:90}]; console.log(cells.map(c=>Number(c['focus'])||0))"
# [ 0 ]   ← 取的是 undefined
```

于是 `values` 全是 0 → `max=1` → 每个格子的 `on` 都是 `false` → 全部填 `--surface-2`（灰）。
**换维度按钮只有下面那句说明文字在变**，图本身永远是同一张空图。

## 二、为什么会漏掉（这一段才是重点）

1. **断言只看了"渲染没渲染"，没看"值对不对"**：DOM 探针当时的检查是"视图能渲染出 HTML"，
   而空图**一样能渲染出完整 SVG**（53×7 个 `<rect>`，只是全灰）。这类"结构齐全、数据为零"
   的缺陷，靠"能不能渲染"永远抓不住。
2. **探针的夹具里那条数据是空数组**：`'/api/insights/heatmap': []` —— 就算断言了"颜色"，
   也没有任何一天有值，仍然抓不到。**夹具不造有值的数据，等于把这类 bug 放过**。
3. **前后端各有一份"维度词表"**：后端只出字段名，前端自己编了一套短 id，两边没有任何东西
   把它们绑在一起 —— 这正是 `SR-NF7`（"词表只在后端一处"）想解决的问题，本例是它的反面教材。

## 三、修法（T-G1 顺手修 + 防复发）

- **维度 id 改成数据字段名本身**：词表在后端 `vocab.HEATMAP_DIMENSIONS`（`allowed` = 那五个真字段），
  界面拿 `GET /api/insights/heatmap-dimensions` 给的 `id/label/unit/kind` 渲染按钮与取值 ——
  于是"按钮的 id"与"数据的字段"**由构造保证同名**，不再有第二份短 id 表。
- **补一条真断言**（`tools/ui_dom_probe.mjs` 的 `stats·热力图有值渲染`）：
  - 夹具里放一天**有值**的数据（`focus_minutes: 90`）；
  - 断言渲染出来的 SVG 里**出现过 `var(--accent)`** —— 有值的格子才会上色；
  - 并断言按钮的 `data-metric` 就是 `focus_minutes`/`review_count`（真字段名）。
  老代码在同样的夹具下不会有 `var(--accent)` → 这条会红。**只断言"渲染出按钮和说明"是抓不住的。**
- 测试里再加一条**结构性**护栏：`test_vocab_line.py` 断言
  `vocab.HEATMAP_DIMENSIONS.allowed == insights.HEATMAP_FIELDS`（多一个少一个都会红）。

## 四、教训

1. **"能不能渲染"和"渲染得对不对"是两回事**：可视化类改动，断言要落在**数据映射**上
   （有没有色、数值对不对），而不是"有没有 HTML"。
2. **探针夹具必须带"有值"的数据**：空数组夹具会让一大类缺陷永久免疫于检查。
3. **同一份词表不许存两份**：一旦前后端各写一份映射，中间就没人保证它们对得上 ——
   要么后端给全（本例），要么前端从后端拿。
