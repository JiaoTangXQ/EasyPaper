"""Markdown helpers for local Obsidian sync."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_SPACE_RE = re.compile(r"\s+")


def normalize_entity_key(name: str) -> str:
    """Deterministic entity key: trim, NFKC, collapse whitespace, case-insensitive."""
    normalized = unicodedata.normalize("NFKC", name or "")
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    return normalized.casefold()


def sanitize_markdown_name(name: str, *, fallback: str = "Untitled", max_length: int = 120) -> str:
    """Create a stable filename/wiki target for Obsidian markdown notes."""
    value = unicodedata.normalize("NFKC", name or "")
    value = value.replace("/", "_").replace("\\", "_")
    value = re.sub(r"[\[\]]", "", value)
    value = re.sub(r"[#:^]", " ", value)
    value = re.sub(r'[<>:"|?*]', " ", value)
    value = _SPACE_RE.sub(" ", value).strip(" .")
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = fallback
    return value[:max_length].rstrip(" ._") or fallback


def frontmatter_value(value: Any) -> str:
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _join_values(values: list[Any]) -> str:
    return ", ".join(str(value) for value in values if str(value).strip())


def _entity_target(name: str, entity_links: dict[str, str]) -> str:
    return entity_links.get(normalize_entity_key(name), sanitize_markdown_name(name))


def build_paper_markdown(
    *,
    paper_id: str,
    paper: dict[str, Any],
    title: str,
    note_link: str,
    entity_links: dict[str, str],
) -> str:
    metadata = paper.get("metadata") or {}
    authors = metadata.get("authors") or []
    author_names = []
    for author in authors:
        if not isinstance(author, dict) or not author.get("name"):
            continue
        if author.get("affiliation"):
            author_names.append(f"{author['name']} ({author['affiliation']})")
        else:
            author_names.append(author["name"])
    keywords = metadata.get("keywords") or paper.get("keywords") or []
    abstract = metadata.get("abstract") or paper.get("abstract") or ""
    summary = paper.get("summary") or paper.get("tl_dr") or ""
    summary_page = paper.get("summary_page") if isinstance(paper.get("summary_page"), dict) else {}

    lines = [
        "---",
        f"easypaper_id: {frontmatter_value(paper_id)}",
        'easypaper_type: "paper"',
        f"title: {frontmatter_value(title)}",
        "---",
        "",
        f"# {title}",
        "",
        f"个人笔记：[[{note_link}]]",
        "",
    ]

    if summary_page:
        lines.extend(["## AI 速览"])
        if summary_page.get("one_liner"):
            lines.append(f"- 一句话：{summary_page['one_liner']}")
        if summary_page.get("estimated_minutes"):
            lines.append(f"- 预计阅读：{summary_page['estimated_minutes']} 分钟")
        if summary_page.get("novelty_score"):
            lines.append(f"- 新颖度：{summary_page['novelty_score']}/5")
        story = summary_page.get("story") if isinstance(summary_page.get("story"), dict) else {}
        story_labels = {
            "problem": "问题",
            "method": "方法",
            "results": "结果",
            "impact": "影响",
        }
        for key, label in story_labels.items():
            if story.get(key):
                lines.extend(["", f"### {label}", str(story[key])])
        key_numbers = summary_page.get("key_numbers") if isinstance(summary_page.get("key_numbers"), list) else []
        if key_numbers:
            lines.extend(["", "### 关键数据"])
            for item in key_numbers:
                if not isinstance(item, dict):
                    continue
                value = item.get("value") or ""
                label = item.get("label") or ""
                context = item.get("context")
                line = f"- **{value}** {label}".rstrip()
                if context:
                    line += f"：{context}"
                lines.append(line)
        pipeline = summary_page.get("pipeline") if isinstance(summary_page.get("pipeline"), dict) else {}
        if pipeline:
            steps = pipeline.get("steps") if isinstance(pipeline.get("steps"), list) else []
            flow = [pipeline.get("input"), *steps, pipeline.get("output")]
            flow_text = " -> ".join(str(part) for part in flow if part)
            if flow_text:
                lines.extend(["", "### 技术流程", flow_text])
        contributions = (
            summary_page.get("contributions") if isinstance(summary_page.get("contributions"), list) else []
        )
        if contributions:
            lines.extend(["", "### 主要贡献"])
            lines.extend(f"- {item}" for item in contributions if item)
        limitations = summary_page.get("limitations") if isinstance(summary_page.get("limitations"), list) else []
        if limitations:
            lines.extend(["", "### 局限性"])
            lines.extend(f"- {item}" for item in limitations if item)
        summary_keywords = summary_page.get("keywords") if isinstance(summary_page.get("keywords"), list) else []
        if summary_keywords:
            lines.extend(["", "### 关键概念"])
            for item in summary_keywords:
                if isinstance(item, dict) and item.get("text"):
                    suffix = f" ({item.get('type', 'concept')})" if item.get("type") else ""
                    lines.append(f"- {item['text']}{suffix}")
        lines.append("")

    if author_names or metadata.get("year") or metadata.get("venue") or metadata.get("doi") or metadata.get("url"):
        lines.extend(["## 论文信息"])
        if author_names:
            lines.append(f"- 作者：{', '.join(author_names)}")
        if metadata.get("year"):
            lines.append(f"- 年份：{metadata['year']}")
        if metadata.get("venue"):
            lines.append(f"- 会议/期刊：{metadata['venue']}")
        if metadata.get("doi"):
            lines.append(f"- DOI：{metadata['doi']}")
        if metadata.get("arxiv_id"):
            lines.append(f"- arXiv：{metadata['arxiv_id']}")
        if metadata.get("url"):
            lines.append(f"- 链接：{metadata['url']}")
        if keywords:
            lines.append(f"- 关键词：{', '.join(str(keyword) for keyword in keywords)}")
        lines.append("")

    if abstract:
        lines.extend(["## 摘要", str(abstract), ""])

    if summary:
        lines.extend(["## AI 总结", str(summary), ""])

    sections = (paper.get("structure") or {}).get("sections") if isinstance(paper.get("structure"), dict) else []
    if sections:
        lines.extend(["## 章节结构"])
        for section in sections:
            if not isinstance(section, dict):
                continue
            title_text = section.get("title") or ""
            if not title_text:
                continue
            indent = "  " if int(section.get("level") or 1) > 1 else ""
            summary_text = section.get("summary")
            lines.append(f"{indent}- {title_text}" + (f"：{summary_text}" if summary_text else ""))
        lines.append("")

    entities = paper.get("entities") or []
    if entities:
        lines.extend(["## 实体"])
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = entity.get("name") or ""
            if not name:
                continue
            target = _entity_target(name, entity_links)
            entity_type = entity.get("type") or entity.get("entity_type") or "concept"
            definition = entity.get("definition") or entity.get("description") or ""
            suffix = f"：{definition}" if definition else ""
            lines.append(f"- [[{target}]] ({entity_type}){suffix}")
        lines.append("")

    relationships = paper.get("relationships") if isinstance(paper.get("relationships"), list) else []
    if relationships:
        lines.extend(["## 关系"])
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            source = relationship.get("source") or ""
            target = relationship.get("target") or ""
            rel_type = relationship.get("type") or "relates_to"
            if not source or not target:
                continue
            source_link = _entity_target(source, entity_links)
            target_link = _entity_target(target, entity_links)
            line = f"- [[{source_link}]] **{rel_type}** [[{target_link}]]"
            if relationship.get("description"):
                line += f"：{relationship['description']}"
            if relationship.get("confidence") is not None:
                line += f"（置信度：{relationship['confidence']}）"
            lines.append(line)
        lines.append("")

    findings = paper.get("findings") or []
    if findings:
        lines.extend(["## 发现"])
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            title_text = finding.get("title") or finding.get("statement") or finding.get("description") or ""
            if not title_text:
                continue
            lines.append(f"- {title_text}")
            evidence = finding.get("evidence")
            if evidence:
                lines.append(f"  - 证据：{evidence}")
        lines.append("")

    methods = paper.get("methods") or []
    if methods:
        lines.extend(["## 方法"])
        for method in methods:
            if isinstance(method, dict):
                lines.append(f"### {method.get('name', 'Method')}")
                if method.get("description"):
                    lines.append(str(method["description"]))
                inputs = method.get("inputs") if isinstance(method.get("inputs"), list) else []
                outputs = method.get("outputs") if isinstance(method.get("outputs"), list) else []
                if inputs:
                    lines.append(f"- 输入：{_join_values(inputs)}")
                if outputs:
                    lines.append(f"- 输出：{_join_values(outputs)}")
                lines.append("")

    datasets = paper.get("datasets") or []
    if datasets:
        lines.extend(["## 数据集"])
        for dataset in datasets:
            if isinstance(dataset, dict):
                name = dataset.get("name") or "Dataset"
                description = dataset.get("description") or ""
                lines.append(f"- {name}" + (f"：{description}" if description else ""))
                if dataset.get("usage"):
                    lines.append(f"  - 用途：{dataset['usage']}")
        lines.append("")

    flashcards = paper.get("flashcards") if isinstance(paper.get("flashcards"), list) else []
    if flashcards:
        lines.extend(["## 闪卡"])
        for index, flashcard in enumerate(flashcards, start=1):
            if not isinstance(flashcard, dict):
                continue
            lines.append(f"### 卡片 {index}")
            if flashcard.get("front"):
                lines.append(f"- 问：{flashcard['front']}")
            if flashcard.get("back"):
                lines.append(f"- 答：{flashcard['back']}")
            tags = flashcard.get("tags") if isinstance(flashcard.get("tags"), list) else []
            if tags:
                lines.append(f"- 标签：{_join_values(tags)}")
            if flashcard.get("difficulty") is not None:
                lines.append(f"- 难度：{flashcard['difficulty']}/5")
            srs = flashcard.get("srs") if isinstance(flashcard.get("srs"), dict) else {}
            if srs.get("next_review"):
                lines.append(f"- 下次复习：{srs['next_review']}")
            lines.append("")

    annotations = paper.get("annotations") if isinstance(paper.get("annotations"), list) else []
    if annotations:
        lines.extend(["## 用户笔记"])
        for annotation in annotations:
            if not isinstance(annotation, dict) or not annotation.get("content"):
                continue
            kind = annotation.get("type") or "note"
            created_at = f"（{annotation['created_at']}）" if annotation.get("created_at") else ""
            lines.append(f"- {kind}{created_at}：{annotation['content']}")
        lines.append("")

    sync_lines = []
    if paper.get("extraction_model"):
        sync_lines.append(f"- 提取模型：{paper['extraction_model']}")
    if paper.get("extracted_at"):
        sync_lines.append(f"- 提取时间：{paper['extracted_at']}")
    if sync_lines:
        lines.extend(["## 同步信息", *sync_lines, ""])

    return "\n".join(lines).rstrip() + "\n"


def build_entity_markdown(
    *,
    entity_key: str,
    entity_name: str,
    entity_type: str,
    definition: str,
    paper_links: list[tuple[str, str]],
    relationships: list[dict[str, Any]] | None = None,
    entity_links: dict[str, str] | None = None,
) -> str:
    lines = [
        "---",
        'easypaper_type: "entity"',
        f"easypaper_entity_key: {frontmatter_value(entity_key)}",
        f"name: {frontmatter_value(entity_name)}",
        f"type: {frontmatter_value(entity_type or 'concept')}",
        "---",
        "",
        f"# {entity_name}",
        "",
    ]
    if definition:
        lines.extend([definition, ""])
    if paper_links:
        lines.extend(["## 出现在哪些论文"])
        seen: set[str] = set()
        for _title, target in paper_links:
            if target in seen:
                continue
            seen.add(target)
            lines.append(f"- [[{target}]]")
        lines.append("")
    if relationships:
        links = entity_links or {}
        lines.extend(["## 相关关系"])
        for relationship in relationships:
            source = relationship.get("source") or ""
            target = relationship.get("target") or ""
            rel_type = relationship.get("type") or "relates_to"
            if not source or not target:
                continue
            source_link = _entity_target(source, links)
            target_link = _entity_target(target, links)
            line = f"- [[{source_link}]] **{rel_type}** [[{target_link}]]"
            if relationship.get("description"):
                line += f"：{relationship['description']}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
