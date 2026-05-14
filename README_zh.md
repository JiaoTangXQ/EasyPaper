# EasyPaper

**把论文变成带得走的知识。**

EasyPaper 是一个可本地部署的 Web 应用，帮助你阅读、理解并留住英文学术论文中的知识。上传一个 PDF 或粘贴论文链接 — 获取翻译或简化版本（排版完整保留）、AI 重点高亮，以及可导出到任何平台的便携知识库。

[English](README.md)

---

## 核心功能

### 1. 翻译 & 简化

- **英文 → 中文** 翻译，保留排版、图片和公式（基于 [pdf2zh](https://github.com/Byaidu/PDFMathTranslate)）
- **英文 → 简单英文** 词汇简化（CEFR A2/B1 级别，约 2000 常用词）
- 支持本地 PDF 上传，也支持直接粘贴 PDF、arXiv、OpenReview 链接
- PDF 输入，PDF 输出 — 图表、公式、格式完整保留
- 默认打开干净的单语 PDF，中英对照版作为单独文件下载

### 2. AI 重点高亮

自动识别并用颜色标注 PDF 中的关键句子。现在高亮定位使用后端生成的句子 ID 和 PDF 坐标，不再依赖脆弱的全文搜索，中文跨行和标点差异下更可靠。

| 颜色 | 分类 | 标注内容 |
|------|------|---------|
| 黄色 | 核心结论 | 主要发现和研究成果 |
| 蓝色 | 方法创新 | 新颖方法和技术贡献 |
| 绿色 | 关键数据 | 定量结果、指标、实验数据 |

阅读器内置可筛选的高亮句子面板，支持按类别过滤、点击跳页、查看分类数量和未定位状态。

![AI 重点高亮](imgs/img-5.png)

### 3. 知识库（可迁移）

通过 LLM 从论文中提取结构化知识 — 以便携 JSON 格式存储，不与本应用绑定：

- **实体**：方法、模型、数据集、指标、概念、任务、人物、机构
- **关系**：扩展、使用、评估于、优于、类似、矛盾、属于、依赖
- **发现**：结果、局限性、贡献，附带证据引用
- **闪卡**：自动生成的学习卡片，支持 SM-2 间隔重复调度
- **提取流程**：可在阅读器中发起知识提取、跟踪状态，并在完成后跳转到论文详情页

![知识库 — 论文详情](imgs/img-2.png)

![知识库 — 研究发现](imgs/img-3.png)

### 4. 知识图谱

交互式力导向图谱，可视化所有论文中的实体与关系。按实体类型着色，按重要性调整大小，支持搜索和缩放。

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

### 6. 闪卡复习

内置间隔重复系统（SM-2 算法），复习自动生成的闪卡。按 0-5 评分你的记忆效果，系统自动安排最优复习间隔。

![闪卡复习](imgs/img-4.png)

---

## 效果展示

### 翻译为中文
![翻译为中文](imgs/img-0.png)

### 简化英文
![简化英文](imgs/img-1.png)

### 保留排版技术
![排版分析](imgs/test.png)

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
  api_key: "YOUR_API_KEY"             # 必填 — 任意 OpenAI 兼容 API
  base_url: "https://api.example.com/v1"
  model: "gemini-2.5-flash"           # 翻译/简化/知识提取使用的模型
  judge_model: "gemini-2.5-flash"

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
