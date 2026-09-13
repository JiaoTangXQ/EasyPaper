---
name: EasyPaper
description: 以完整论文和来源证据为中心的阅读工作台。
colors:
  ui-background: "hsl(60 11% 97%)"
  ui-foreground: "hsl(30 4% 9%)"
  ui-primary: "hsl(30 4% 9%)"
  ui-secondary: "hsl(40 9% 94%)"
  ui-muted: "hsl(40 7% 94%)"
  ui-muted-foreground: "hsl(30 4% 40%)"
  ui-border: "hsl(40 6% 85%)"
  ui-ring: "hsl(6 63% 45%)"
  paper: "#f7f7f5"
  surface: "#fff"
  ink: "#191817"
  muted: "#6b6864"
  line: "#deddd8"
  accent: "#bd392b"
  accent-soft: "#f9eeeb"
  accent-hover: "#a42e22"
  accent-active: "#892519"
  navigation-selected: "#efeeea"
  selection-bg: "#f2d8d2"
  selection-ink: "#4f1d16"
  destructive: "#b52b20"
  task-ready: "#226447"
  task-ready-bg: "#ecf6ee"
  task-pending: "#815214"
  task-pending-bg: "#fff5df"
  task-error: "#a22e3d"
  task-error-bg: "#fff0f2"
typography:
  display:
    fontFamily: '"EasyPaper Headline", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "clamp(30px, 3.5vw, 44px)"
    fontWeight: 700
    lineHeight: 1.45
    letterSpacing: "-0.035em"
  headline:
    fontSize: "clamp(24px, 2.5vw, 30px)"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-0.025em"
  title:
    fontSize: "18px"
    fontWeight: 600
    letterSpacing: "-0.015em"
  document-title:
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "15px"
    lineHeight: 1.6
  reading-support:
    fontSize: "14px"
    lineHeight: 1.85
  label:
    fontSize: "14px"
    fontWeight: 500
    lineHeight: "20px"
rounded:
  "5": "5px"
  "6": "6px"
  "8": "8px"
  "12": "12px"
spacing:
  "4": "4px"
  "8": "8px"
  "12": "12px"
  "16": "16px"
  "20": "20px"
  "24": "24px"
  "28": "28px"
components:
  button-primary:
    backgroundColor: "{colors.ui-primary}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.8}"
    padding: "8px 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "hsl(30 4% 9% / 0.9)"
  button-outline:
    backgroundColor: "{colors.ui-background}"
    textColor: "{colors.ink}"
    rounded: "{rounded.8}"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.ui-secondary}"
    textColor: "{colors.ui-foreground}"
    rounded: "{rounded.8}"
    height: "40px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.8}"
    height: "40px"
  button-link:
    backgroundColor: "transparent"
    textColor: "{colors.ui-primary}"
    height: "40px"
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.surface}"
    rounded: "{rounded.8}"
    height: "40px"
  input:
    backgroundColor: "{colors.ui-background}"
    textColor: "{colors.ink}"
    rounded: "{rounded.6}"
    padding: "8px 12px"
    height: "40px"
  navigation-active:
    backgroundColor: "{colors.navigation-selected}"
    textColor: "{colors.ink}"
    rounded: "{rounded.8}"
    padding: "10px 13px"
  task-ready:
    backgroundColor: "{colors.task-ready-bg}"
    textColor: "{colors.task-ready}"
    rounded: "{rounded.5}"
    padding: "3px 7px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ui-foreground}"
    rounded: "{rounded.12}"
    padding: "24px"
  graph-node:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.8}"
    width: "214px"
    height: "76px"
  graph-node-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.8}"
    width: "214px"
    height: "76px"
---

# Design System: EasyPaper

## Overview

**Creative North Star: "卷纸与手写印记"**

白色导航与文档表面、暖灰工作区和墨黑动作承托完整论文。黑色圆角方块中的白色卷纸小写 e、朱红圆点与手写字标共同构成 EasyPaper 标识；红色用于标识、局部选中与焦点。论文列表、来源笔记和复习内容以区域间距和细分隔线分组。

完整论文是阅读主体。概览和共享批注由用户打开，作为正文旁的辅助区域；提问使用右下角带卷纸 e 标识的悬浮对话入口。界面字体、色彩与间距不改写 PDF 内的原始排版，也不覆盖用户选择的批注颜色。

**Key Characteristics:**

- 白色表面、细边框与平整布局。
- 墨黑主动作、朱红圆点与焦点、文字说明状态。
- 共用卷纸 e 与手写轮廓字标，避免依赖运行时字体加载。
- 连续阅读与返回来源的动作保持可见。

依据为 [工作区样式](frontend/src/workspace.css)、[阅读器样式](frontend/src/components/reader/reader.css)及共享组件。基础样式中的旧定义由后续样式覆盖；新增界面沿用本文件记录的现行系统。

## Colors

白、暖灰与墨黑承担页面的大部分面积；朱红集中在标识和局部交互细节。

### Primary

- **墨黑操作色**：`ui-primary` 用于共享主按钮和链接；`ink` 用于标题、正文和论文对话按钮。
- **朱红印记**：`accent` 用于标识中的圆点、当前导航图标、阅读版本下划线、来源动作与原生控件焦点；`ui-ring` 用于共享控件焦点环。
- **浅朱红选中面**：`accent-soft` 用于知识导航、阅读辅助面板标签和 PDF 工具选中背景。
- **PDF 工具状态**：SDK 使用同一朱红操作色，悬停与按下分别使用 `accent-hover`、`accent-active`；这只影响控件，不重着色文档。

### Neutral

- **暖灰底面**：`paper` 是工作区底色，`ui-background` 是共享表单和描边按钮的底色；`ui-secondary` 承托次级按钮，`navigation-selected` 承托当前主导航。
- **白色文档面**：`surface` 用于列表、卡片、面板和导入对话框。
- **墨黑正文**：`ink` 与 `ui-foreground` 承担正文和标题；`muted` 与 `ui-muted-foreground` 承担说明、元数据与次级操作。
- **细分隔线**：`line` 用于工作区边界，`ui-border` 用于共享控件边框；`ui-muted` 提供共享组件中的低对比背景。

工作区 CSS 与 Tailwind 共享组件使用两组现行 token；共享主操作是墨黑，工作区 `accent` 是朱红，两者用途不同。扩展时使用所属组件已有的 token。PDF SDK 的内部主题在 `PdfViewer.tsx` 显式映射到相同色系。

### Status

任务完成、处理中和失败分别使用绿色、琥珀色、红色的文字与浅底组合；破坏性操作使用 `destructive`。这些状态色不作为页面品牌色。论文批注保留用户选择的颜色；图谱实体类型使用中性文字标签。

**The Sparse Red Rule.** 保持白黑与暖灰为大面积底色；沿用红色圆点、选中标记与焦点，不把主操作按钮统一改成红底。

**The Labeled State Rule.** 颜色必须与状态文字或选中语义一起出现；保存状态与跨版本匹配状态分别展示。

**The Textual Graph Rule.** 图谱类型由文字标签辨认，不按类型分配彩色节点。白底节点与墨黑选中面区分状态，红色标注选中印记、当前视图图标、悬停或聚焦时的关联线及焦点轮廓。

## Typography

**Brand lettering:** EasyPaper 字标由 Satisfy 手写字形转为 SVG 轮廓，保留原生字距、字偶距与连笔的粗细变化。字标是矢量图稿，无运行时字体请求，不作为界面字体使用。

**Display Font:** EasyPaper Headline，仅用于登录与注册页的宣传标题。

**Body Font:** 系统无衬线栈；阅读器控件使用 `ui-sans-serif, system-ui, -apple-system, "PingFang SC", sans-serif`。

标题通过字号、字重与较紧字距建立层级。论文题名允许换行，元数据弱于正文；概览、回答和知识详情采用更宽行距。

### Hierarchy

- **Display**：认证页标题；窄屏收为（28px），保留同一字重与行距。
- **Headline**：常规页面标题；知识详情为长题名采用相近的自适应字号和更宽行距。
- **Title**：列表及区域标题。
- **Document title**：论文列表题名；窄屏使用（15px）。
- **Body / Reading support**：常规正文与较长阅读辅助内容，分别使用前置 token。
- **Label**：共享按钮和表单标签；元数据通常使用（12px），阅读器标签通常使用（13px）。

字标文件为 [完整组合](frontend/public/brand/logo.svg)、[独立标识](frontend/public/brand/mark.svg)与[轮廓文字](frontend/public/brand/wordmark.svg)，来源和许可见 [品牌说明](frontend/public/brand/README.md)及 [Satisfy Apache 2.0 许可](frontend/public/brand/LICENSE-Satisfy.txt)。

认证标题字体来源与许可见 [字体说明](frontend/src/assets/fonts/README.md)。子集只含现有认证标题的字形；修改标题时同时更新子集，其他界面文字继续使用系统字体。

**The Document Type Rule.** PDF 的字体、公式与页面排版由文档决定，不套用界面正文的字体和行高。

## Layout

- **工作区骨架**：桌面采用导航列（216px）与可伸缩内容列；视口不超过（1100px）时导航收为（184px）。内容最大宽度（1400px），默认上下内边距（38px / 60px），水平内边距自适应（20–64px）。
- **区域节奏**：页面区域间距（28px）；标题与操作横向排列，空间不足时换行。论文使用完整宽度的列表行，题名、元数据与操作分组；不超过（1100px）时行操作移到正文下方。
- **手机工作区**：不超过（700px）时导航改为顶部三项导航，账户菜单保留设置入口。内容水平边距（16px），区域间距（23px），继续阅读区、导入选项和认证页改为单列。
- **阅读器**：独立占满视口高度，不显示工作区侧栏。顶部放返回、题名、阅读版本与辅助动作；其下独立显示保存及匹配信息，其余区域用于完整 PDF。桌面辅助面板宽（370px）。
- **紧凑阅读器**：不超过（1000px）时辅助面板覆盖阅读区域；PDF 保持挂载，覆盖期间不可见且不可交互。关闭面板或跳到批注位置后露出 PDF。版本控制在窄屏换行，不隐藏待生成状态。
- **专用内容宽度**：复习区最大宽度（780px），设置区最大宽度（850px）。
- **图谱工作台**：白色外框内并列放置可伸缩浏览区和详情栏（286px），中间使用细分隔线。暖灰画布高度随视口变化（400–640px），右侧详情独立滚动；不超过（1100px）时详情移到浏览区下方，解除高度限制，关系列表改为两列。选择概念后重置详情滚动位置，上下排列时同时露出并聚焦定义区。
- **手机图谱**：不超过（700px）时初始使用概念列表，保留图谱切换、搜索与类型筛选；列表和画布高度分别不超过（440px）与固定（440px），详情关系改为单列。桌面初始化使用当前概念的聚焦图谱。

**The Return to Paper Rule.** 概览、问答和知识内容保留清楚的来源入口；紧凑布局中的定位动作必须同时露出目标 PDF。

## Elevation & Depth

默认表面通过背景差异、细边框与分隔线区分层级。共享卡片和认证表单没有常驻阴影；主按钮使用很浅的高光与投影，按下时转为内阴影。对话框以半透明遮罩和浮层阴影与当前任务区分。PDF 页面的投影属于文档承载区。

**The Surface Boundary Rule.** 列表、笔记、复习内容沿用边框与色面；仅需表达浮层、按钮按压或 PDF 页边时使用现有阴影。

## Shapes

控件采用短圆角矩形，完整容器采用更大的圆角。共享输入框与小号按钮使用 `rounded.6`，默认按钮和主导航使用 `rounded.8`，卡片、论文列表、图谱容器和导入对话框使用 `rounded.12`。任务状态与版本内选项使用 `rounded.5`。实体标签等分类标记可以使用已有胶囊形状。

操作图标使用描边 SVG，与操作文字并列；仅保留图标时提供可访问名称。列表内容通过细线分开，同一个列表不为每行重复增加卡片阴影。

## Components

### Brand

共享 `Brand` 在工作区导航和认证入口组合卷纸 e 与手写轮廓字标；`BrandMark` 在论文助手中独立使用。标识固定使用墨黑圆角方块、白色曲线主体与朱红圆点，不随所在表面的文字色变化。完整组合提供 EasyPaper 可访问名称，装饰 SVG 不重复朗读。

导航字标默认宽（138px）、图形尺寸（32px），二者间距（9px）；中等宽度侧栏使用字标（115px）与图形（29px），认证页使用字标（190px）与图形（42px）。保留矢量比例与完整文字，不用普通文字重排替代轮廓文件。

链接中的标识悬停或键盘聚焦时，图形整体上移（1px），过渡为（220ms cubic-bezier(0.16, 1, 0.3, 1)）。只有未启用减少动态效果时发生，静止状态保留完整标识。

### Buttons

主动作使用实底墨黑，次级操作使用描边、浅底或透明按钮；删除等操作使用语义红色。默认高度及内边距见前置 token；小号高度（36px），大号及粗指针设备上的共享按钮最小高度（44px）。

主按钮悬停使用原色的九成不透明度；描边和透明按钮悬停使用暖灰背景与墨黑文字。禁用态降低不透明度并停止交互。共享控件使用焦点环，工作区原生控件使用与背景分离的朱红轮廓。

### Chips

任务状态采用小圆角、浅色底与紧凑内边距，文字明确说明完成、处理中或失败。标签用于分类；筛选项仍使用按钮和选中语义。静态状态标签不承担按钮行为。

### Cards / Containers

共享容器为白底、细边框、无默认阴影，标准内容内边距见 `card`。论文列表共用一个外框，行内先读题名，再读来源及状态，最后找到动作。完整原文题名自然换行，其下使用 14px、常规字重、1.6 行高和现有次级文字色展示中文译名；继续阅读卡片沿用同一译名样式。题名与译名间距 4px，之后状态区保持 8px 间距。长中文在窄屏自然换行，不固定高度或截断。空状态提供标题、短说明和下一步操作；错误状态提供重试。

### Inputs / Fields

共享输入框使用细边框、浅底与短圆角；列表搜索输入使用白底，为左侧搜索图标留出空间。桌面控件字体通常为（14px）；窄屏共享输入和粗指针环境使用（16px）。长路径与论文题名允许换行，不能挤出页面。

### Navigation

主导航提供三个带文字的入口，当前项采用暖灰底、墨黑文字与朱红图标。账户入口位于桌面导航底部；桌面与手机均通过账户菜单中的“连接设置”进入设置。知识浏览方式和详情标签采用浅朱红底与朱红文字，允许换行。页面提供跳到内容的键盘入口。

### Concept Graph

图谱使用位置可重复的 SVG 布局，默认选中直接关系最多的概念。聚焦图以当前节点居中、邻居分列两侧，每组最多显示八个邻居，超出时提供分组范围与前后翻页。全局图保留全部概念与端点有效的关系；分组只限制当前画布内容，详情中的“关联关系”保留当前概念的全部关系，包括方向和已有说明。同名概念保留各自身份与论文来源。

节点沿用 `graph-node` 与 `graph-node-selected`；尺寸为 SVG 基准坐标，随画布一起缩放。类型为次级文字（12px），名称为墨黑文字（15px / 550），选中后名称变白并显示红色圆点与勾形标记。名称最多显示两行，较长内容截短；完整名称保留在可访问名称、原生提示和详情标题中。节点支持点击、Enter 和空格选择；悬停或聚焦时以红线显示相连关系，键盘焦点另有虚线轮廓，墨黑选中态也保留可见焦点。

详情依次显示类型、完整名称、定义、来源论文入口与关联关系。切换概念重置分组和画布视角。画布可拖动，缩放控件始终提供缩小、比例、放大和适应画布；关系方向与说明放在详情中。搜索和类型筛选显示列表结果，列表行同时给出类型与关系数，选中行使用浅朱红底。

节点填色与关联线描边的状态过渡为（180ms ease-out），列表选中背景为（160ms ease-out）；仅在未开启减少动态效果时使用，不做随机布局移动。实现依据为 [图谱样式](frontend/src/pages/knowledge-graph.css)、[图谱画布](frontend/src/components/knowledge/GraphCanvas.tsx)、[页面交互](frontend/src/pages/KnowledgeGraph.tsx)与[布局函数](frontend/src/lib/knowledge-graph.ts)。

### Reading Workspace

阅读页顶部操作栏最右侧直接提供“全屏”；全屏范围包含版本切换、批注和提问入口。进入后显示“退出全屏”，并随浏览器退出操作同步状态。窄屏保留图标按钮及可访问名称。
全屏时顶部标题、保存状态及 PDF 工具栏一起向上收起；移到顶边展开，移出后延迟收起。工具栏以覆盖方式展开，正文不随展开折叠移动。菜单或键盘操作期间保持可见，触屏可点按顶边入口；系统减少动态效果时直接切换状态。

原文、译文、简化英文和双语版本共用可见的版本按钮；当前版本使用白底、墨黑文字与朱红底线；尚未生成的版本显示实际状态与生成入口。版本切换使用可用的来源页映射。概览与批注共用可关闭的辅助面板，不能替代完整页面。

批注列表展示来源版本、页码、摘录、用户笔记和匹配状态。服务器保存与跨版本匹配是两个独立反馈：“本地已保存 · 待上传”不能显示为“已保存到服务器”，保存成功也不能当成“跨版本匹配完成”。可验证的答案来源提供定位动作；没有定位依据时显示缺失状态。

部分匹配由服务器按（15 / 60 / 300 秒）间隔继续重试，关闭浏览器不停止已安排的重试；等待时显示“批注将自动重试”，重试耗尽后显示“部分内容无法确认对应”。选择边缘截断的零碎字母保留在来源版本中，只对有意义且可验证的文本建立跨版本对应，不补全残词或伪造对应。

论文对话独立悬浮在阅读页右下角，入口沿用卷纸 e 标识并标注“问论文”，助手标题、空状态与回答署名复用同一标识。桌面对话框宽（420px）、高不超过（600px），不占用 PDF 布局宽度；不超过（700px）时改为带遮罩的对话框，边缘留（12px），输入区避让软键盘。标题显示当前论文，只有一个问题输入框，选文作为可移除的附加引用。

回答自动使用当前论文全文，并携带最近六轮已完成问答以支持追问。收起对话保留本次阅读期间的消息、草稿和正在进行的请求；切换论文或刷新页面会清空。点击来源定位原文，在不超过（1000px）的视口中同时收起对话以露出正文。

### Dialogs & Motion

导入对话框使用不透明白底、标题和关闭入口；内容超出视口时在对话框内滚动，选项随屏幕宽度由两列变一列。按钮和主导航的状态变化采用（160ms ease-out），对话框保留组件的短入场过渡。开启减少动态效果偏好时，动画与过渡缩短到近乎即时。

## Do's and Don'ts

### Do:

- **Do** 复用 `Brand`、`BrandMark` 与轮廓 SVG，保留黑色方块、白色卷纸 e 与朱红圆点。
- **Do** 复用工作区与共享控件各自已有的 token、标题层级和选中状态。
- **Do** 保留完整 PDF、文档字体、用户批注颜色和返回来源的操作。
- **Do** 让长题名、操作组、表单与导航在窄屏换行，并保留可见焦点。
- **Do** 分别显示保存、生成和批注匹配的实际状态。

### Don't:

- **Don't** 用旧蓝紫配色或普通字体拼写覆盖已发布的黑白朱红标识。
- **Don't** 用摘要、自动卡片或装饰性内容替代连续论文页面。
- **Don't** 将状态或批注颜色扩展为品牌配色；朱红品牌标记不能代替失败状态文字。
- **Don't** 在正文列表和常规卡片上增加常驻装饰投影。
- **Don't** 将认证标题的字形子集应用到普通界面文字，或将界面字体强加给 PDF。
