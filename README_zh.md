# EasyPaper

**把论文变成带得走的知识。**

EasyPaper 是一个可本地部署的 Web 应用，帮助你阅读、理解并留住英文学术论文中的知识。上传一个 PDF 或粘贴论文链接 — 获取翻译或简化版本（排版完整保留）、AI 重点高亮，以及可导出到任何平台的便携知识库。

### AI 执行方式

后端支持两种可切换的 AI 执行方式：默认的 OpenAI 兼容 HTTP 接口，以及使用本机 ChatGPT 登录态的 Codex CLI。要使用 Codex，先在运行后端的同一账户执行 `codex login`，然后在 `backend/config/config.yaml` 设置 `llm.provider: "codex"`，或启动前设置 `EASYPAPER_AI_PROVIDER=codex`。重启后，阅读辅助、知识提取、摘要、高亮和 PDF 翻译都会通过受限的 `codex exec --ephemeral --sandbox read-only` 执行，不需要填写 API Key；Codex 不可用时任务会明确失败并可重试，不会静默切换成低质量规则结果。

[English](README.md)

![论文列表与中英文标题](imgs/screenshots/library.png)

---

## 核心功能

### 1. 翻译 & 简化

- **英文 → 中文** 翻译，保留排版、图片和公式（基于 [pdf2zh](https://github.com/Byaidu/PDFMathTranslate)）
- **英文 → 简单英文** 词汇简化（CEFR A2/B1 级别，约 2000 常用词）
- 支持本地 PDF 上传，也支持直接粘贴 PDF、arXiv、OpenReview 链接
- PDF 输入，PDF 输出 — 图表、公式、格式完整保留
- 在同一阅读器切换原文、中文译文、简化英语和双语对照；未生成的版本可按需生成
- 支持全屏阅读，顶部工具栏自动折叠，移入时展开

### 2. AI 重点高亮

AI 选出论文中的重点句子，按类别着色。文字标记根据各版本 PDF 的实际文字重新定位；阅读器显示匹配进度，无法确认对应内容时保留原始批注并给出提示。

| 颜色 | 分类 | 标注内容 |
|------|------|---------|
| 黄色 | 核心结论 | 主要发现和研究成果 |
| 蓝色 | 方法创新 | 新颖方法和技术贡献 |
| 绿色 | 关键数据 | 定量结果、指标、实验数据 |

阅读器内置共享批注面板，可搜索摘录和笔记、筛选批注类型、跳转原文，并导出带批注的 PDF。

![HarnessDev：AI 重点句子高亮](imgs/screenshots/ai-highlights.png)

### 3. 知识库（可迁移）

通过 LLM 从论文中提取结构化知识 — 以便携 JSON 格式存储，不与本应用绑定：

- **实体**：方法、模型、数据集、指标、概念、任务、人物、机构
- **关系**：扩展、使用、评估于、优于、类似、矛盾、属于、依赖
- **发现**：结果、局限性、贡献，附带证据引用
- **闪卡**：自动生成的学习卡片，支持 SM-2 间隔重复调度
- **提取流程**：可在阅读器中发起知识提取、跟踪状态，并在完成后跳转到论文详情页

![论文知识笔记：发现与证据](imgs/screenshots/paper-findings.png)

<details>
<summary>查看概念与方法、知识笔记列表</summary>

![论文中提取的概念与方法](imgs/screenshots/paper-concepts.png)

![知识笔记列表](imgs/screenshots/knowledge-library.png)

</details>

### 4. 知识图谱

交互式力导向图谱，可视化所有论文中的实体与关系。按实体类型着色，按重要性调整大小，支持搜索和缩放。

![知识图谱：概念与关系](imgs/screenshots/knowledge-graph.png)

### 5. 多格式导出

知识是你的，随时带走：

| 格式 | 扩展名 | 用途 |
|------|--------|------|
| EasyPaper JSON | `.epaper.json` | 完整便携知识（主格式） |
| Obsidian Vault | `.zip` | 含双向链接的 Markdown 笔记 |
| 本地 Obsidian 同步 | `.md` 文件 | 直接把论文笔记和实体笔记写入本机 vault |
| BibTeX | `.bib` | LaTeX 引用管理 |
| CSL-JSON | `.json` | Zotero / Mendeley 兼容 |
| CSV | `.zip` | 电子表格分析（实体 + 关系） |

本地 Obsidian 同步支持 macOS、Windows、Linux 自动检测 vault，也支持手动填写路径。同步后的论文主笔记会包含已生成的摘要页内容（如有）、论文信息、章节摘要、研究发现、方法、数据集、实体、关系、闪卡和用户笔记。EasyPaper 只写入它管理的论文笔记和实体笔记；主笔记里的 `Paper Title - Notes.md` 是红色链接，用户点击后再由 Obsidian 创建。删除 EasyPaper 里的论文不会删除 Obsidian 中已有的 `.md` 文件。

<details>
<summary>查看导出入口</summary>

![知识备份、Obsidian、文献引用与表格导出](imgs/screenshots/knowledge-export.png)

</details>

### 6. 闪卡复习

内置间隔重复系统（SM-2 算法），复习自动生成的闪卡。查看答案后评价掌握程度，系统据此安排下一次复习。

![闪卡复习：显示答案与掌握程度评分](imgs/screenshots/flashcard-review.png)

*此图以已有论文卡片演示复习流程，未改动真实复习安排。*

<details>
<summary>查看论文中的已生成卡片</summary>

![论文详情中的复习卡](imgs/screenshots/paper-flashcards.png)

</details>

---

## 效果展示

以下图片来自当前版本的实际页面。原文、中文译文、简化英语和双语对照均使用同一篇 **Repo-To-Skill** 论文，展示已有划线在不同版本中的效果。点击图片可查看大图。

### 同一篇论文，四种阅读版本

<details open>
<summary>中文译文</summary>

![Repo-To-Skill：中文译文与同步标记](imgs/screenshots/reader-chinese.png)

</details>

<details>
<summary>英文原文</summary>

![Repo-To-Skill：原文与同步标记](imgs/screenshots/reader-original.png)

</details>

<details>
<summary>简化英语</summary>

![Repo-To-Skill：简化英语与同步标记](imgs/screenshots/reader-simple.png)

</details>

<details>
<summary>双语对照 · 并排查看</summary>

![双语 PDF 中的原文页与中文页并排查看](imgs/screenshots/reader-bilingual.png)

</details>

### 阅读、批注与提问

点击右下角「问论文」即可围绕当前文章提问，无需再次粘贴全文。

![根据当前论文回答问题](imgs/screenshots/paper-chat.png)

<details>
<summary>共享划线与批注面板</summary>

![搜索摘录、查看批注与同步状态](imgs/screenshots/reader-annotations.png)

</details>

<details>
<summary>正文旁的论文概览</summary>

![论文正文与概览同时查看](imgs/screenshots/reader-overview.png)

</details>

<details>
<summary>全屏阅读 · 自动隐藏工具栏</summary>

![全屏状态下展开阅读空间](imgs/screenshots/reader-fullscreen.png)

</details>

### 登录与导入

<details>
<summary>登录页</summary>

![新版登录页与手写品牌字标](imgs/screenshots/login.png)

</details>

<details>
<summary>导入本地 PDF 或论文链接</summary>

![导入论文对话框](imgs/screenshots/import.png)

</details>

---

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
cp backend/config/config.example.yaml backend/config/config.yaml
# 编辑 config.yaml — 填入你的 API Key，选择模型

docker compose up --build
```

浏览器打开 http://localhost 即可使用。

如果用 Docker 同步本机 Obsidian，需要把宿主机 vault 目录挂载到后端容器里，并在知识库设置中填写容器内路径。没有挂载时，容器看不到宿主机文件。

### 方式二：本地开发

**环境要求：** Python 3.11+、Node.js 18+（推荐 Node 20）、一个 OpenAI 兼容的 LLM API Key

**启动后端：**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config/config.example.yaml config/config.yaml
# 编辑 config.yaml — 填入你的 API Key

uvicorn app.main:app --reload
```

**启动前端：**

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 即可使用。

---

## 配置说明

编辑 `backend/config/config.yaml`：

```yaml
llm:
  provider: "api"                     # "api" 或 "codex"
  api_key: "YOUR_API_KEY"             # provider=api 时填写；Codex 模式不需要
  base_url: "https://api.example.com/v1"
  model: "gemini-2.5-flash"           # 翻译/简化/知识提取使用的模型
  judge_model: "gemini-2.5-flash"
  codex:
    executable: "codex"
    model: ""                          # 空值使用本机 Codex 默认模型
    reasoning_effort: "low"

processing:
  max_pages: 100
  max_upload_mb: 50
  max_concurrent: 3                   # 最大并发处理任务数

storage:
  cleanup_minutes: 30                 # 临时文件过期时间（分钟）
  temp_dir: "./backend/tmp"

database:
  url: "sqlite:///./data/app.db"

security:
  secret_key: "CHANGE_THIS"           # JWT 签名密钥 — 生产环境必须修改
  cors_origins:
    - "http://localhost:5173"

agent:
  api_keys:
    - "CHANGE_ME"                     # 给 agent 调用方单独使用的 key
  draft_ttl_minutes: 30
  mcp_mount_path: "/mcp"
```

---

## Agent 接入

EasyPaper 现在在现有 Web 应用之上额外提供了一层面向 agent 的 PDF 翻译接口。

### HTTP

- `POST /api/agent/v1/translate`
- `GET /api/agent/v1/tasks/{task_id}`
- `GET /api/agent/v1/tasks/{task_id}/artifact`
- 认证请求头：`X-Agent-Api-Key: <your key>`

如果没有提供 `highlight`，翻译接口不会直接启动任务，而是返回结构化追问结果：

```json
{
  "status": "needs_input",
  "draft_id": "dr_123",
  "missing_fields": ["highlight"],
  "question": "Do you want key sentences highlighted in the translated PDF?"
}
```

外部 agent 拿到这个结果后，向用户补问并带着相同 `draft_id` 再调用一次即可；参数补齐后接口会返回 `202 Accepted` 和 `task_id`。

```bash
curl -X POST http://127.0.0.1:8000/api/agent/v1/translate \
  -H 'Content-Type: application/json' \
  -H 'X-Agent-Api-Key: CHANGE_ME' \
  -d '{"pdf_base64":"JVBERi0xLjQgdGVzdA=="}'
```

### MCP

- 挂载路径：`/mcp`
- 工具：
  - `translate_pdf`
  - `get_translation_task`
  - `get_translation_artifact`

`translate_pdf` 与 HTTP 接口共用同一套 draft 流程。`get_translation_artifact` 会返回元数据和 base64 编码后的 PDF，方便外部 agent 再把结果发回自己的客户端。

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI, PyMuPDF, pdf2zh (PDFMathTranslate), httpx |
| 前端 | React 18, TypeScript, Vite, Tailwind CSS, Radix UI |
| 数据库 | SQLite（SQLModel） |
| 认证 | JWT (python-jose), bcrypt, OAuth2 bearer |
| AI/LLM | 任意 OpenAI 兼容 API（可配置） |
| 工程化 | Docker Compose, GitHub Actions, ruff, ESLint |

---

## API 概览

| 接口 | 说明 |
|------|------|
| `POST /api/upload` | 上传 PDF（翻译/简化，可选高亮） |
| `POST /api/upload-url` | 导入 PDF、arXiv、OpenReview 链接 |
| `GET /api/status/{id}` | 处理状态、进度、高亮统计和可下载版本 |
| `GET /api/result/{id}/pdf?format=mono\|dual` | 下载处理后的 PDF 或中英对照版 |
| `POST /api/agent/v1/translate` | Agent 翻译 draft / 提交接口 |
| `GET /api/agent/v1/tasks/{id}` | Agent 任务状态 |
| `GET /api/agent/v1/tasks/{id}/artifact` | Agent 成果文件下载 |
| `POST /api/knowledge/extract/{id}` | 触发知识提取 |
| `GET /api/knowledge/extract/status/{paper_id}` | 查询知识提取状态 |
| `GET /api/knowledge/papers` | 知识库论文列表 |
| `GET /api/knowledge/graph` | 知识图谱（实体 + 关系） |
| `GET /api/knowledge/flashcards/due` | 到期闪卡 |
| `POST /api/knowledge/flashcards/{id}/review` | 提交复习结果 |
| `GET /api/knowledge/export/json` | 导出完整知识库 |
| `GET /api/knowledge/export/obsidian` | 导出为 Obsidian 笔记库 |
| `GET /api/knowledge/settings/obsidian/vaults` | 检测本机 Obsidian vault |
| `POST /api/knowledge/settings/obsidian` | 保存本地 Obsidian 同步设置 |
| `POST /api/knowledge/papers/{id}/sync/obsidian` | 同步单篇论文到本地 Obsidian |
| `GET /api/knowledge/export/bibtex` | 导出为 BibTeX |

---

## 开发指南

```bash
# 后端
cd backend
ruff check app/
pytest

# 前端
cd frontend
npm run lint
npm run type-check
npm test
```

---

## 开源协议

MIT
