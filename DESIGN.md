---
name: EasyPaper
description: 以完整论文为中心的阅读工作台。界面安静，细节靠层级、材质和动效完成。
source:
  tokens: frontend/src/styles/tokens.css
  base: frontend/src/styles/base.css
  components: frontend/src/styles/components.css
  pages: frontend/src/styles/app.css
  reader: frontend/src/components/reader/reader.css
  chat: frontend/src/components/reader/paper-chat.css
  graph: frontend/src/pages/knowledge-graph.css
colors:
  bg: "#f5f5f7"
  bg-elevated: "#fbfbfd"
  surface: "#ffffff"
  ink: "#1d1d1f"
  ink-2: "#3a3a3c"
  muted: "#6e6e73"
  faint: "#8e8e93"
  hairline: "rgba(0,0,0,0.08)"
  line: "#d9d9de"
  accent: "#b0322a"
  accent-soft: "#fbefed"
  ok: "#1f7a4d"
  warn: "#9a5b00"
  danger: "#c0352b"
  info: "#2f5fb3"
  reader-canvas: "#e9e9ed"
radius:
  control: "999px (按钮、搜索、胶囊)"
  input: "9px"
  card: "18px"
  hero: "24px"
motion:
  ease-out: "cubic-bezier(0.16, 1, 0.3, 1)"
  spring: "cubic-bezier(0.34, 1.4, 0.64, 1)"
  fast: "140ms"
  base: "240ms"
  slow: "420ms"
---

# Design System: EasyPaper

## 方向

**简洁，但不简单。** 第一眼只有内容和少量动作；细节放在层级、材质和反馈里：毛玻璃导航、滑动的分段控件、翻转的复习卡、点读释义的浮层、带进度的骨架屏。参照对象是 Apple 的系统应用和官网：大字标题、浅灰底、白色卡片、墨黑主按钮、只用一个品牌色。

完整 PDF 永远是阅读主体。AI 解释、概览和批注放在用户主动打开的侧栏或浮层中，不替代正文，也不改写 PDF 的字体与排版。

## 信息架构

```text
顶部导航（桌面）/ 底部标签栏（手机）
├─ 我的论文  /dashboard        继续阅读 → 全部论文（筛选 · 搜索）→ 导入
│  └─ 阅读器 /reader/:id       原文 · 中文 · 简化 · 双语 · 点读
│     ├─ 助手侧栏：概览 · 本页解读 · 批注（一次一个）
│     ├─ 更多：知识笔记、下载此版本、重新生成、全屏
│     └─ 问论文：右下角悬浮对话
├─ 知识笔记  /knowledge         论文笔记 · 概念图谱 · 术语本（同一子导航）
│  └─ 单篇   /knowledge/paper/:id   发现与证据 · 概念与方法 · 关系 · 复习卡 · 我的笔记
├─ 复习      /review           知识卡片 · 术语（同一页切换，徽标显示到期总数）
└─ 设置      /settings          阅读与点读 · 连接与同步 · 数据与导出 · 账户
⌘K 搜索：任意论文、页面和操作
```

规则：

- **一件事只有一个入口位置。** 复习统一在“复习”，术语的浏览在“术语本”；导出在知识笔记的“导出”和设置的“数据与导出”，二者调用同一份格式列表。
- **从产物回到来源。** 发现、概念证据、术语、复习卡都有“原文”或“来源论文”入口。
- **阅读器只留两层控件。** 顶栏放返回、题名与页码、版本切换和少量动作；PDF 自带工具栏放批注工具。保存与匹配状态合成一个可点开的状态标签。
- 旧地址 `/knowledge/review`、`/terms` 自动跳转到新位置。

## 颜色

- 大面积是 `bg` 浅灰和 `surface` 白，文字是 `ink` 墨黑与 `muted` 灰。
- 主动作用墨黑实底胶囊按钮；次级动作用 `fill` 浅灰底；危险动作用 `danger`。
- 朱红 `accent` 只用于品牌圆点、焦点环、选中的关键标记和少量链接，不做大面积底色。
- 状态色（`ok` / `warn` / `danger` / `info`）总是和文字一起出现，不单独表达含义。
- 用户批注保留自己选择的颜色；AI 高亮的黄、蓝、绿三类沿用原定义。

## 字体与层级

- 系统字体栈（SF Pro / PingFang SC）。英文论文片段、术语和引文使用衬线体 `--font-serif`，让“原文”在界面里一眼可辨。
- 页面标题 30–40px / 700 / 字距 -0.028em；区块标题 21px / 650；正文 15px；元数据 12–13px。
- 认证页的品牌标题字体 `EasyPaper Headline` 只含现有标题的字形子集，不用于其他文字。

## 材质与形状

- 卡片：白底、18px 圆角、极浅的双层阴影 `--shadow-1`，悬停时上浮 2–3px 并换用 `--shadow-2`。
- 浮层（菜单、点读卡、对话框、命令面板）：半透明白 + `backdrop-filter` 模糊 + `--shadow-pop`。
- 列表使用一个分组容器，行之间是从图标右侧开始的细线（类似 iOS 设置）。
- 按钮、搜索框、筛选标签都是胶囊形；输入框 9px 圆角，聚焦时出现 4px 朱红光环。

## 动效

所有动效都有作用，并尊重 `prefers-reduced-motion`（只保留旋转的加载指示，速度放慢）。

- 页面与区块进场：上移 10px 淡入（420ms），列表前五行依次错开 40ms。
- 分段控件：一个白色滑块在选项间滑动（240ms ease-out）。
- 开关：弹性曲线，iOS 绿色。
- 复习卡：3D 翻转（620ms），评分按钮上浮反馈，完成时绘制对勾。
- 继续阅读卡：右侧纸张悬停时展开。
- 对话框：缩放淡入；手机上改为从底部弹出的面板。
- 加载：骨架屏闪光，而不是居中转圈。

## 组件

- `Button`（`ui/button.tsx`）：`default` 墨黑、`secondary` 浅灰、`outline` 白底描边、`ghost` 透明、`destructive`、`link`；尺寸 `sm` / `default` / `lg` / `icon` / `icon-sm`。默认 `type="button"`。
- `SegmentedControl`（`ui/segmented-control.tsx`）：带滑块的分段切换，选项是普通按钮（`aria-pressed`），可带图标与计数。
- `confirmAction()`（`lib/confirm.ts` + `ui/confirm.tsx`）：替代 `window.confirm` 的确认对话框。
- `EmptyState` / `ListSkeleton` / `PageHeader`（`workspace/PageHeader.tsx`）。
- `CommandPalette`：⌘K / Ctrl K 打开，上下键选择、回车打开。
- `ReadingDemo`：登录页和首次使用时循环演示“高亮 → 对照译文 → 点读释义”。

## 布局

- 内容最大宽度 1180px，两侧留白 `clamp(20px, 4vw, 48px)`。
- 顶部导航 56px 高，毛玻璃，三段式：品牌 · 主导航 · 搜索与账户。
- ≤ 760px：主导航移到底部标签栏（我的论文 · 知识笔记 · 复习 · 设置），内容底部为标签栏留出空间。
- 阅读器：桌面默认缩放不超过 150%，避免宽屏上一页要翻几屏；侧栏 380px；≤ 1000px 时侧栏覆盖全屏，PDF 保持挂载；≤ 860px 时版本切换换到第二行并使用短名称。

## Don'ts

- 不用朱红做主按钮或大面积背景。
- 不在同一列表里给每一行都加卡片阴影。
- 不用摘要、卡片或装饰内容替代连续的论文页面。
- 不在页面里硬编码颜色和阴影；新增样式从 `tokens.css` 取值。
