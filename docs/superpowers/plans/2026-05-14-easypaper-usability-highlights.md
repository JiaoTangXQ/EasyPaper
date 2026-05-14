# EasyPaper Usability And Highlights Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make Chinese AI highlights accurate enough to trust, remove duplicate bilingual output from the default reader, keep knowledge extraction navigable, and make the main UI Chinese.

**Architecture:** The backend will own sentence segmentation and PDF coordinate lookup before calling the LLM. The LLM will classify stable `sentence_id` values instead of returning text for PyMuPDF to search. Task status will expose highlight status and highlight sentence metadata; the frontend will render a filterable highlight panel and use page-level PDF navigation.

**Tech Stack:** FastAPI, SQLModel, PyMuPDF, React 18, TypeScript, Vite, Vitest, pytest.

---

## File Structure

- Modify `backend/app/services/highlighter.py`: sentence extraction, sentence IDs, quad caching, LLM classification by ID, highlight metadata.
- Modify `backend/app/models/task.py`: task fields for `highlight_status` and `highlight_sentences`.
- Modify `backend/app/services/task_manager.py`: persist highlight result metadata.
- Modify `backend/app/core/db.py`: lightweight SQLite compatibility migrations for new task columns.
- Modify `backend/app/api/routes.py`: expose highlight metadata, support `format=mono|dual` result downloads, keep task execution references.
- Modify `backend/app/services/document_processor.py`: select mono by default, preserve dual artifact path, set highlight result.
- Modify `backend/app/api/knowledge_routes.py`: create `PaperKnowledge` synchronously and return real `paper_id`.
- Modify frontend pages under `frontend/src/pages/`: Chinese UI, highlight panel, knowledge extraction handling, dual download.
- Add `backend/tests/test_highlighter.py`: regression tests for Chinese sentence matching and invalid IDs.
- Add/update environment docs: `.python-version`, `frontend/.nvmrc`, README Python requirement.

## Task 1: Highlight Regression Tests

**Files:**
- Create: `backend/tests/test_highlighter.py`
- Modify: none

- [x] Step 1: Add tests that build a small Chinese PDF with one sentence split across visual lines.
- [x] Step 2: Assert sentence extraction produces one normalized sentence with usable quads.
- [x] Step 3: Assert applying a mocked LLM result by `sentence_id` creates a highlight without `search_for` string matching.
- [x] Step 4: Assert invalid sentence IDs increase `failed_matches` and do not crash.
- [x] Step 5: Run `python3.11 -m pytest tests/test_highlighter.py -q` and verify tests fail before implementation.

## Task 2: Sentence-ID Highlight Service

**Files:**
- Modify: `backend/app/services/highlighter.py`

- [x] Step 1: Add a `HighlightCandidate` dataclass with `sentence_id`, `text`, `page_index`, and `quads`.
- [x] Step 2: Extract candidates from `page.get_text("dict")`, preserving span/line coordinates.
- [x] Step 3: Split Chinese and English sentence endings while allowing line breaks inside one sentence.
- [x] Step 4: Send candidate IDs and text snippets to the LLM in chunks.
- [x] Step 5: Parse only `{sentence_id, category}` results; reject unknown IDs.
- [x] Step 6: Apply highlights from candidate quads directly.
- [x] Step 7: Preserve `failed_matches` for invalid IDs and empty-quad candidates.
- [x] Step 8: Run `python3.11 -m pytest tests/test_highlighter.py -q`.

## Task 3: Persist Highlight Status

**Files:**
- Modify: `backend/app/models/task.py`
- Modify: `backend/app/services/task_manager.py`
- Modify: `backend/app/core/db.py`
- Modify: `backend/app/services/document_processor.py`
- Modify: `backend/app/api/routes.py`

- [x] Step 1: Add task columns `highlight_status` and `highlight_sentences`.
- [x] Step 2: Replace `set_highlight_stats` with `set_highlight_result`, keeping compatibility if useful.
- [x] Step 3: Set status to `success`, `partial`, `failed`, or `skipped`.
- [x] Step 4: Include `failed_matches` and sentence metadata in `/api/status/{task_id}`.
- [x] Step 5: Add tests or extend existing route tests if a seam exists.

## Task 4: Default Mono Output And Dual Download

**Files:**
- Modify: `backend/app/models/task.py`
- Modify: `backend/app/core/db.py`
- Modify: `backend/app/services/task_manager.py`
- Modify: `backend/app/services/document_processor.py`
- Modify: `backend/app/api/routes.py`
- Modify: `frontend/src/pages/Reader.tsx`

- [x] Step 1: Store both mono and dual output paths when pdf2zh returns both.
- [x] Step 2: Use mono as the default result PDF.
- [x] Step 3: Support `/api/result/{task_id}/pdf?format=dual`.
- [x] Step 4: Add a Reader button for Chinese-English dual PDF download when available.
- [x] Step 5: Verify existing result download still returns mono.

## Task 5: Knowledge Extraction Navigation

**Files:**
- Modify: `backend/app/api/knowledge_routes.py`
- Modify: `backend/app/services/knowledge_extractor.py`
- Modify: `frontend/src/pages/Reader.tsx`
- Modify: `frontend/src/pages/KnowledgeBase.tsx`

- [x] Step 1: Create or reuse `PaperKnowledge` before starting extraction.
- [x] Step 2: Return the real `paper_id` and `status`.
- [x] Step 3: Ensure the extractor updates the existing row instead of creating a second row.
- [x] Step 4: In Reader, navigate to the paper detail page on already-completed extraction, or show extraction-in-progress state and poll.
- [x] Step 5: Make KnowledgeBase refresh extracting papers.

## Task 6: Chinese UI Text

**Files:**
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/pages/Register.tsx`
- Modify: `frontend/src/pages/Reader.tsx`
- Modify: `frontend/src/pages/KnowledgeBase.tsx`
- Modify: `frontend/src/pages/PaperDetail.tsx`
- Modify: `frontend/src/pages/FlashcardReview.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [x] Step 1: Replace visible English strings in main flows with Chinese.
- [x] Step 2: Keep API field names and PDF annotation categories unchanged.
- [x] Step 3: Avoid introducing an i18n framework.

## Task 7: Environment Documentation

**Files:**
- Add: `.python-version`
- Add: `frontend/.nvmrc`
- Modify: `README.md`
- Modify: `README_zh.md`

- [x] Step 1: Set Python requirement to 3.11+.
- [x] Step 2: Set frontend Node version hint to 20.
- [x] Step 3: Keep Docker instructions unchanged.

## Task 8: Additional Review Findings

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `backend/app/services/document_processor.py`
- Modify: `backend/app/api/knowledge_routes.py`
- Modify: `frontend/src/pages/PaperDetail.tsx`
- Modify: `frontend/src/pages/FlashcardReview.tsx`

- [x] Step 1: Fix Dashboard polling so the interval changes between active and idle states.
- [x] Step 2: Serialize pdf2zh environment variable overrides and restore previous values after each run.
- [x] Step 3: Change flashcard review, flashcard creation, and annotation creation to JSON request bodies.
- [x] Step 4: Update frontend callers to send JSON bodies.
- [x] Step 5: Add regression tests for the body endpoints and pdf2zh environment restoration.

## Verification

- [x] Run backend highlighter tests: `python3.11 -m pytest tests/test_highlighter.py -q`.
- [x] Run backend route/service tests where dependencies allow: `python3.11 -m pytest -q`.
- [x] Run frontend type check with Node 20 if available: `npm run type-check`.
- [x] Run frontend tests with Node 20 if available: `npm test`.
- [x] If local runtime lacks dependencies, state the exact missing dependency/runtime and the command that failed.
