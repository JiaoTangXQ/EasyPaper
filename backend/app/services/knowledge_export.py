"""知识库导出引擎 - 支持多种可迁移格式"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile

# LaTeX/BibTeX special characters that must be escaped inside a {...} field.
_BIBTEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _bibtex_escape(value: str) -> str:
    # Escape backslash first so we don't double-escape the ones we introduce.
    out = value.replace("\\", _BIBTEX_ESCAPES["\\"])
    for char, repl in _BIBTEX_ESCAPES.items():
        if char == "\\":
            continue
        out = out.replace(char, repl)
    return out


def _bibtex_cite_key(raw: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_:-]", "", raw or "")
    return key or "ref"


def _yaml_quote(value: object) -> str:
    """Double-quote a scalar for YAML front-matter, escaping \\ and \"."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def to_bibtex(metadata: dict, cite_key: str) -> str:
    """Render a BibTeX @article entry with LaTeX-escaped fields and a safe key."""
    authors = metadata.get("authors", [])
    author_str = " and ".join(a.get("name", "") for a in authors)
    lines = [
        f"@article{{{_bibtex_cite_key(cite_key)},",
        f"  title = {{{_bibtex_escape(str(metadata.get('title', '')))}}},",
        f"  author = {{{_bibtex_escape(author_str)}}},",
        f"  year = {{{metadata.get('year', '') or ''}}},",
    ]
    if metadata.get("doi"):
        lines.append(f"  doi = {{{_bibtex_escape(str(metadata['doi']))}}},")
    if metadata.get("venue"):
        lines.append(f"  journal = {{{_bibtex_escape(str(metadata['venue']))}}},")
    lines.append("}\n")
    return "\n".join(lines)


class KnowledgeExporter:
    """将知识库导出为多种标准格式。"""

    @staticmethod
    def export_obsidian_vault(papers_json: list[dict]) -> bytes:
        """导出为 Obsidian 兼容的 Markdown vault (ZIP)。"""
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 收集所有实体用于独立的实体笔记
            all_entities: dict[str, dict] = {}

            for paper in papers_json:
                metadata = paper.get("metadata", {})
                title = metadata.get("title", "Untitled")
                safe_title = _safe_filename(title)

                # --- 论文笔记 ---
                md = _paper_to_markdown(paper)
                zf.writestr(f"papers/{safe_title}.md", md)

                # 收集实体
                for ent in paper.get("entities", []):
                    name = ent.get("name", "")
                    if name:
                        key = name.lower().strip()
                        if key not in all_entities:
                            all_entities[key] = {**ent, "papers": [title]}
                        else:
                            all_entities[key].setdefault("papers", []).append(title)

            # --- 实体笔记 ---
            for ent in all_entities.values():
                name = ent.get("name", "Unknown")
                safe_name = _safe_filename(name)
                md = _entity_to_markdown(ent)
                zf.writestr(f"entities/{safe_name}.md", md)

        return buffer.getvalue()

    @staticmethod
    def export_csv(papers_json: list[dict]) -> tuple[bytes, bytes]:
        """导出实体和关系为 CSV。返回 (entities_csv, relationships_csv)。"""
        # Entities CSV
        ent_buffer = io.StringIO()
        ent_writer = csv.writer(ent_buffer)
        ent_writer.writerow(["id", "name", "type", "definition", "importance", "paper_title"])

        # Relationships CSV
        rel_buffer = io.StringIO()
        rel_writer = csv.writer(rel_buffer)
        rel_writer.writerow(["id", "source", "target", "type", "description", "confidence", "paper_title"])

        for paper in papers_json:
            title = paper.get("metadata", {}).get("title", "")
            entity_names: dict[str, str] = {}

            for ent in paper.get("entities", []):
                ent_id = ent.get("id", "")
                name = ent.get("name", "")
                entity_names[ent_id] = name
                ent_writer.writerow(
                    [
                        ent_id,
                        name,
                        ent.get("type", ""),
                        ent.get("definition", ""),
                        ent.get("importance", 0.5),
                        title,
                    ]
                )

            for rel in paper.get("relationships", []):
                src_id = rel.get("source_entity_id", "")
                tgt_id = rel.get("target_entity_id", "")
                rel_writer.writerow(
                    [
                        rel.get("id", ""),
                        entity_names.get(src_id, rel.get("source", src_id)),
                        entity_names.get(tgt_id, rel.get("target", tgt_id)),
                        rel.get("type", ""),
                        rel.get("description", ""),
                        rel.get("confidence", 0.5),
                        title,
                    ]
                )

        return ent_buffer.getvalue().encode("utf-8"), rel_buffer.getvalue().encode("utf-8")

    @staticmethod
    def export_csl_json(papers_json: list[dict]) -> bytes:
        """导出为 CSL-JSON 格式（Zotero/Mendeley 兼容）。"""
        csl_items = []
        for paper in papers_json:
            metadata = paper.get("metadata", {})

            # 如果论文已有 csl_json，直接使用
            if metadata.get("csl_json"):
                csl_items.append(metadata["csl_json"])
                continue

            # 从 metadata 构建 CSL-JSON
            authors = [
                {"family": _split_name(a.get("name", ""))[1], "given": _split_name(a.get("name", ""))[0]}
                for a in metadata.get("authors", [])
            ]
            item = {
                "type": "article-journal",
                "id": paper.get("id", ""),
                "title": metadata.get("title", ""),
                "author": authors,
                "abstract": metadata.get("abstract", ""),
            }
            if metadata.get("year"):
                item["issued"] = {"date-parts": [[metadata["year"]]]}
            if metadata.get("doi"):
                item["DOI"] = metadata["doi"]
            if metadata.get("venue"):
                item["container-title"] = metadata["venue"]
            if metadata.get("url"):
                item["URL"] = metadata["url"]
            csl_items.append(item)

        return json.dumps(csl_items, ensure_ascii=False, indent=2).encode("utf-8")


# ------------------------------------------------------------------
# 内部工具函数
# ------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """将名称转为安全的文件名。"""
    unsafe = '<>:"/\\|?*'
    result = name
    for ch in unsafe:
        result = result.replace(ch, "_")
    return result[:100].strip()


def _split_name(full_name: str) -> tuple[str, str]:
    """尝试分割姓名为 (given, family)。"""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return full_name, ""


def _paper_to_markdown(paper: dict) -> str:
    """将 PaperKnowledge JSON 转为 Obsidian Markdown 笔记。"""
    metadata = paper.get("metadata", {})
    title = metadata.get("title", "Untitled")
    authors = metadata.get("authors", [])
    author_str = ", ".join(a.get("name", "") for a in authors)
    keywords = metadata.get("keywords", [])

    lines = [
        "---",
        f"title: {_yaml_quote(title)}",
        f"authors: [{', '.join(_yaml_quote(a.get('name', '')) for a in authors)}]",
        f"year: {metadata.get('year', '')}",
    ]
    if metadata.get("doi"):
        lines.append(f"doi: {_yaml_quote(metadata['doi'])}")
    if keywords:
        lines.append(f"tags: [{', '.join(_yaml_quote(k) for k in keywords)}]")
    lines.append(f"easypaper_id: {_yaml_quote(paper.get('id', ''))}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")

    # Metadata
    lines.append("## Metadata")
    lines.append(f"- **Authors**: {author_str}")
    if metadata.get("year"):
        lines.append(f"- **Year**: {metadata['year']}")
    if metadata.get("venue"):
        lines.append(f"- **Venue**: {metadata['venue']}")
    if metadata.get("doi"):
        lines.append(f"- **DOI**: [{metadata['doi']}](https://doi.org/{metadata['doi']})")
    lines.append("")

    # Abstract
    if metadata.get("abstract"):
        lines.append("## Abstract")
        lines.append(metadata["abstract"])
        lines.append("")

    # Key Concepts
    entities = paper.get("entities", [])
    if entities:
        lines.append("## Key Concepts")
        for ent in entities:
            name = ent.get("name", "")
            definition = ent.get("definition", "")
            lines.append(f"- [[{name}]] ({ent.get('type', '')}) - {definition}")
        lines.append("")

    # Relationships
    relationships = paper.get("relationships", [])
    if relationships:
        lines.append("## Relationships")
        for rel in relationships:
            src = rel.get("source", "")
            tgt = rel.get("target", "")
            rtype = rel.get("type", "")
            lines.append(f"- [[{src}]] **{rtype}** [[{tgt}]]")
        lines.append("")

    # Key Findings
    findings = paper.get("findings", [])
    if findings:
        lines.append("## Key Findings")
        for f in findings:
            ftype = f.get("type", "")
            statement = f.get("statement", "")
            evidence = f.get("evidence", "")
            lines.append(f"- **{ftype.title()}**: {statement}")
            if evidence:
                lines.append(f"  - Evidence: {evidence}")
        lines.append("")

    # Methods
    methods = paper.get("methods", [])
    if methods:
        lines.append("## Methods")
        for m in methods:
            lines.append(f"### {m.get('name', 'Method')}")
            lines.append(m.get("description", ""))
            lines.append("")

    # Flashcards
    flashcards = paper.get("flashcards", [])
    if flashcards:
        lines.append("## Flashcards")
        for fc in flashcards:
            lines.append(f"**Q:** {fc.get('front', '')}")
            lines.append(f"**A:** {fc.get('back', '')}")
            lines.append("")

    return "\n".join(lines)


def _entity_to_markdown(entity: dict) -> str:
    """将实体转为 Obsidian Markdown 笔记。"""
    name = entity.get("name", "Unknown")
    etype = entity.get("type", "concept")
    aliases = entity.get("aliases", [])
    definition = entity.get("definition", "")
    papers = entity.get("papers", [])

    lines = [
        "---",
        f"type: {etype}",
    ]
    if aliases:
        lines.append(f"aliases: [{', '.join(repr(a) for a in aliases)}]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    if definition:
        lines.append(definition)
        lines.append("")
    if papers:
        lines.append("## Appears In")
        for p in papers:
            lines.append(f"- [[{p}]]")
        lines.append("")

    return "\n".join(lines)
