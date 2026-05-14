"""Paper Summarizer - generates a structured visual summary via LLM."""

from __future__ import annotations

import asyncio
import json
import logging

import fitz
import httpx

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "你是一位专业的学术论文分析专家。"
    "根据给定的研究论文文本，生成一份结构化的可视化摘要。\n\n"
    "**重要：所有文本内容必须使用中文撰写。**\n\n"
    "返回一个包含以下字段的 JSON 对象：\n"
    "{\n"
    '  "one_liner": "一句话概括核心贡献（不超过30字）",\n'
    '  "novelty_score": 4,\n'
    '  "estimated_minutes": 15,\n'
    '  "story": {\n'
    '    "problem": "这篇论文解决什么问题？（2-3句话）",\n'
    '    "method": "提出了什么方法？（2-3句话）",\n'
    '    "results": "关键结果是什么？（2-3句话）",\n'
    '    "impact": "为什么重要？（2-3句话）"\n'
    "  },\n"
    '  "key_numbers": [\n'
    '    {"value": "93.2%", "label": "Top-1 准确率", "context": "比之前 SOTA 高 2.1%"}\n'
    "  ],\n"
    '  "pipeline": {\n'
    '    "input": "输入内容（1-5个词）",\n'
    '    "steps": ["步骤1", "步骤2", "步骤3"],\n'
    '    "output": "输出内容（1-5个词）"\n'
    "  },\n"
    '  "contributions": ["贡献1", "贡献2"],\n'
    '  "limitations": ["局限性1", "局限性2"],\n'
    '  "keywords": [\n'
    '    {"text": "Transformer", "type": "method", "importance": 0.9}\n'
    "  ]\n"
    "}\n\n"
    "规则：\n"
    "- one_liner：简洁、具体、无废话\n"
    "- novelty_score：1=增量改进, 2=中等, 3=值得关注, 4=重要, 5=范式转变\n"
    "- estimated_minutes：该领域研究者的实际阅读时间\n"
    "- story：每个字段2-3句话，清晰具体，不要泛泛而谈\n"
    "- key_numbers：2-4个论文中的具体量化结果及精确数字。如果没有量化结果则返回空列表\n"
    "- pipeline：用3-6个简短的步骤名称描述核心方法流程\n"
    "- contributions：2-4项，每项一句具体的话\n"
    "- limitations：1-3项，来自论文本身或可明确推断\n"
    "- keywords：5-10个关键术语，类型为：method, model, dataset, metric, concept, task。"
    "专有名词（如模型名、方法名）保留英文原文\n"
    "- 仅返回 JSON 对象，不要包含其他文本\n"
)


class PaperSummarizer:
    """Generates a structured visual summary of an academic paper."""

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def summarize(self, pdf_bytes: bytes) -> dict:
        pages_text = self._extract_text(pdf_bytes)
        context = self._build_context(pages_text)

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
        ) as client:
            return await self._call_llm(client, context)

    def _extract_text(self, pdf_bytes: bytes) -> list[str]:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        try:
            for i in range(doc.page_count):
                text = doc.load_page(i).get_text("text")
                if text.strip():
                    pages.append(text)
        finally:
            doc.close()
        return pages

    def _build_context(self, pages: list[str]) -> str:
        if not pages:
            return ""

        full = "\n\n".join(pages)
        max_chars = 20000

        if len(full) <= max_chars:
            return full

        # Prioritize beginning (abstract/intro) and end (results/conclusion)
        head_budget = int(max_chars * 0.6)
        tail_budget = max_chars - head_budget

        return full[:head_budget] + "\n\n[...middle sections omitted for brevity...]\n\n" + full[-tail_budget:]

    async def _call_llm(self, client: httpx.AsyncClient, text: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Paper text:\n\n{text}"},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                return self._parse_json(content)
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.error(
                        "Summary generation failed after %d retries: %s",
                        max_retries,
                        exc,
                    )
                    raise
                delay = 2 * (2**attempt)
                logger.warning("Summary LLM error: %s, retrying in %ds...", exc, delay)
                await asyncio.sleep(delay)

        return {}

    def _parse_json(self, content: str) -> dict:
        if content.startswith("```"):
            lines = content.split("\n")
            start_idx = 1 if lines[0].startswith("```") else 0
            end_idx = -1 if lines[-1].strip() == "```" else len(lines)
            content = "\n".join(lines[start_idx:end_idx])

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                return json.loads(content[start : end + 1])
            raise
