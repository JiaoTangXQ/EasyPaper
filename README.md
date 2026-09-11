# EasyPaper

**Turn academic papers into knowledge you keep.**

EasyPaper is a self-hosted web app that helps you read, understand, and retain knowledge from English academic papers. Upload a PDF or paste a paper link — get back a translated or simplified version with layout intact, AI-highlighted key sentences, and a portable knowledge base you can export anywhere.

[中文说明](README_zh.md)

![Paper library with original and Chinese titles](imgs/screenshots/library.png)

---

## What It Does

### 1. Translate & Simplify

- **English → Chinese** translation preserving layout, images, and formulas (powered by [pdf2zh](https://github.com/Byaidu/PDFMathTranslate))
- **English → Simple English** vocabulary simplification (CEFR A2/B1, ~2000 common words)
- Local PDF upload and direct PDF/arXiv/OpenReview link import
- PDF-in, PDF-out — figures, equations, and formatting stay intact
- Switch between the original, Chinese, simplified English, and bilingual PDFs in one reader; generate missing versions on demand
- Fullscreen reading with toolbars that collapse automatically and reappear on hover

### 2. AI Highlighting

AI selects key sentences and assigns a highlight category. Shared text marks are positioned against each version’s own PDF text. The reader shows matching progress and preserves the original annotation when a corresponding passage cannot be confirmed.

| Color | Category | What It Highlights |
|-------|----------|-------------------|
| Yellow | Core Conclusions | Main findings and research outcomes |
| Blue | Method Innovations | Novel approaches and technical contributions |
| Green | Key Data | Quantitative results, metrics, experimental data |

The shared annotation panel lets you search excerpts and notes, filter annotation types, jump to passages, and export annotated PDFs.

![HarnessDev with AI-highlighted key sentences](imgs/screenshots/ai-highlights.png)

### 3. Knowledge Base (Portable)

Extract structured knowledge from papers via LLM — stored as portable JSON, never locked to this app:

- **Entities**: methods, models, datasets, metrics, concepts, tasks, people, organizations
- **Relationships**: extends, uses, evaluates_on, outperforms, similar_to, contradicts, part_of, requires
- **Findings**: results, limitations, contributions with evidence references
- **Flashcards**: auto-generated study cards with SM-2 spaced repetition scheduling
- **Extraction workflow**: start extraction from the reader, track status, and jump to the generated paper page when ready

![Paper knowledge: findings and evidence](imgs/screenshots/paper-findings.png)

<details>
<summary>Concepts, methods, and the knowledge library</summary>

![Concepts and methods extracted from a paper](imgs/screenshots/paper-concepts.png)

![Knowledge library](imgs/screenshots/knowledge-library.png)

</details>

### 4. Knowledge Graph

Explore concepts and relationships across your papers in a diagram with text labels. Focus on one concept at a time, browse its neighbors in groups of eight, and inspect definitions and source papers alongside the graph. Search, type filters, a global view, zoom, and a keyboard-accessible list keep the complete graph available.

![Knowledge graph of concepts and relationships](imgs/screenshots/knowledge-graph.png)

### 5. Multi-Format Export

Your knowledge is yours. Export it in any format:

| Format | Extension | Use Case |
|--------|-----------|----------|
| EasyPaper JSON | `.epaper.json` | Complete portable knowledge (primary format) |
| Obsidian Vault | `.zip` | Markdown notes with wikilinks for Obsidian |
| Local Obsidian Sync | `.md` files | Write paper and entity notes directly into a local vault |
| BibTeX | `.bib` | LaTeX citation management |
| CSL-JSON | `.json` | Zotero / Mendeley compatible |
| CSV | `.zip` | Spreadsheet analysis (entities + relationships) |

Local Obsidian sync detects vaults on macOS, Windows, and Linux. You can also paste a vault path manually. A synced paper note includes the generated summary (when available), metadata, section summaries, findings, methods, datasets, entities, relationships, flashcards, and user notes. EasyPaper writes managed paper/entity notes only; the linked `Paper Title - Notes.md` file is not created until you click it in Obsidian. Deleting a paper in EasyPaper does not delete existing Obsidian `.md` files.

<details>
<summary>Available export actions</summary>

![Knowledge backup, Obsidian, citation, and table exports](imgs/screenshots/knowledge-export.png)

</details>

### 6. Flashcard Review

Review generated flashcards with SM-2 spaced repetition. Reveal the answer, rate your recall, and schedule the next review.

![Flashcard review with answer and recall ratings](imgs/screenshots/flashcard-review.png)

*This review demonstration uses existing paper cards without changing their actual review schedule.*

<details>
<summary>Generated cards in the paper detail</summary>

![Generated paper flashcards](imgs/screenshots/paper-flashcards.png)

</details>

---

## Screenshots

Captured from the current application, with the UI shown in Chinese. The four reading views use the same **Repo-To-Skill** paper and its existing annotations. Open an image to inspect it at full size.

### One paper, four reading views

<details open>
<summary>Chinese translation</summary>

![Repo-To-Skill: Chinese translation and synchronized annotations](imgs/screenshots/reader-chinese.png)

</details>

<details>
<summary>English original</summary>

![Repo-To-Skill: original text and synchronized annotations](imgs/screenshots/reader-original.png)

</details>

<details>
<summary>Simplified English</summary>

![Repo-To-Skill: simplified English and synchronized annotations](imgs/screenshots/reader-simple.png)

</details>

<details>
<summary>Bilingual PDF · facing pages</summary>

![Original and translated pages displayed together in the bilingual PDF](imgs/screenshots/reader-bilingual.png)

</details>

### Reading, annotations, and questions

The floating paper assistant answers questions about the current article without requiring the full text to be pasted again.

![A question answered using the current paper](imgs/screenshots/paper-chat.png)

<details>
<summary>Shared annotations</summary>

![Search excerpts and inspect annotation matching status](imgs/screenshots/reader-annotations.png)

</details>

<details>
<summary>Paper overview beside the source</summary>

![Paper text and overview together](imgs/screenshots/reader-overview.png)

</details>

<details>
<summary>Fullscreen reading · auto-hiding toolbars</summary>

![Fullscreen reading with collapsed controls](imgs/screenshots/reader-fullscreen.png)

</details>

### Sign in and import

<details>
<summary>Sign-in page</summary>

![Sign-in page with the handwritten wordmark](imgs/screenshots/login.png)

</details>

<details>
<summary>Import a local PDF or paper link</summary>

![Paper import dialog](imgs/screenshots/import.png)

</details>

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
cp backend/config/config.example.yaml backend/config/config.yaml
# Edit config.yaml — add your API key and choose your model

docker compose up --build
```

Open http://localhost in your browser.

This `docker-compose.yml` is for a quick local trial (HTTP only, SQLite, backend
port exposed). **For a public multi-user deployment** use the hardened stack
(Caddy auto-HTTPS + Postgres, self-registration disabled, backend not exposed) —
see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and `docker-compose.prod.yml`.

For local Obsidian sync in Docker, mount your host vault into the backend container and use the mounted path in the Knowledge Base settings. Without a mount, the container cannot access files on your host machine.

### Option 2: Local Development

**Prerequisites:** Python 3.11+, Node.js 18+ (Node 20 recommended), an OpenAI-compatible LLM API key

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config/config.example.yaml config/config.yaml
# Edit config.yaml — add your API key

uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

---

## Configuration

Edit `backend/config/config.yaml`:

```yaml
llm:
  provider: "api"                     # "api" or "codex"
  api_key: "YOUR_API_KEY"             # Required only when provider=api
  base_url: "https://api.example.com/v1"
  model: "gemini-2.5-flash"           # Model for translation/simplification/extraction
  judge_model: "gemini-2.5-flash"
  codex:
    executable: "codex"
    model: ""                          # Empty uses the local Codex default model
    reasoning_effort: "low"

processing:
  max_pages: 100
  max_upload_mb: 50
  max_concurrent: 3                   # Concurrent processing tasks

storage:
  cleanup_minutes: 30                 # TTL for temporary files
  temp_dir: "./backend/tmp"

database:
  url: "sqlite:///./data/app.db"

security:
  secret_key: "CHANGE_THIS"           # JWT signing key — must change in production
  cors_origins:
    - "http://localhost:5173"

agent:
  api_keys:
    - "CHANGE_ME"                     # Separate key for agent callers
  draft_ttl_minutes: 30
  mcp_mount_path: "/mcp"
```

Set `APP_ENV=production` when deploying. In production the app **refuses to start**
if `security.secret_key` or any `agent.api_keys` entry is still the placeholder
default — in development these only log a warning.

---

## Agent Integration

EasyPaper now exposes the PDF translation flow as an agent-friendly interface on top of the existing Web app.

### HTTP

- `POST /api/agent/v1/translate`
- `GET /api/agent/v1/tasks/{task_id}`
- `GET /api/agent/v1/tasks/{task_id}/artifact`
- Auth header: `X-Agent-Api-Key: <your key>`

If `highlight` is omitted, the translation endpoint returns a structured follow-up contract instead of starting the job:

```json
{
  "status": "needs_input",
  "draft_id": "dr_123",
  "missing_fields": ["highlight"],
  "question": "Do you want key sentences highlighted in the translated PDF?"
}
```

Once the missing field is supplied with the same `draft_id`, the API returns `202 Accepted` and a `task_id`.

```bash
curl -X POST http://127.0.0.1:8000/api/agent/v1/translate \
  -H 'Content-Type: application/json' \
  -H 'X-Agent-Api-Key: CHANGE_ME' \
  -d '{"pdf_base64":"JVBERi0xLjQgdGVzdA=="}'
```

### MCP

- Mount path: `/mcp`
- Tools:
  - `translate_pdf`
  - `get_translation_task`
  - `get_translation_artifact`

`translate_pdf` follows the same draft workflow as the HTTP endpoint. `get_translation_artifact` returns metadata plus a base64-encoded PDF so an external agent can pass the file back to its own client surface.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI, PyMuPDF, pdf2zh (PDFMathTranslate), httpx |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Radix UI |
| Database | SQLite via SQLModel |
| Auth | JWT (python-jose), bcrypt, OAuth2 bearer |
| AI/LLM | Any OpenAI-compatible API (configurable) |
| DevOps | Docker Compose, GitHub Actions, ruff, ESLint |

---

## API Overview

| Endpoint | Description |
|----------|-------------|
| `POST /api/upload` | Upload PDF (translate/simplify, optional highlight) |
| `POST /api/upload-url` | Import a direct PDF/arXiv/OpenReview link |
| `GET /api/status/{id}` | Processing status, progress, highlight stats, and available outputs |
| `GET /api/result/{id}/pdf?format=mono\|dual` | Download processed PDF or bilingual PDF |
| `POST /api/agent/v1/translate` | Agent translation draft + submit endpoint |
| `GET /api/agent/v1/tasks/{id}` | Agent task status |
| `GET /api/agent/v1/tasks/{id}/artifact` | Agent artifact download |
| `POST /api/knowledge/extract/{id}` | Trigger knowledge extraction |
| `GET /api/knowledge/extract/status/{paper_id}` | Poll knowledge extraction status |
| `GET /api/knowledge/papers` | List knowledge base papers |
| `GET /api/knowledge/graph` | Knowledge graph (entities + relationships) |
| `GET /api/knowledge/flashcards/due` | Due flashcards for review |
| `POST /api/knowledge/flashcards/{id}/review` | Submit review result |
| `GET /api/knowledge/export/json` | Export full knowledge base |
| `GET /api/knowledge/export/obsidian` | Export as Obsidian vault |
| `GET /api/knowledge/settings/obsidian/vaults` | Detect local Obsidian vaults |
| `POST /api/knowledge/settings/obsidian` | Save local Obsidian sync settings |
| `POST /api/knowledge/papers/{id}/sync/obsidian` | Sync one paper to local Obsidian |
| `GET /api/knowledge/export/bibtex` | Export as BibTeX |

---

## Development

```bash
# Backend
cd backend
ruff check app/
pytest

# Frontend
cd frontend
npm run lint
npm run type-check
npm test
```

---

## License

MIT
