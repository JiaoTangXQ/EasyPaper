import { downloadFile } from "./format";

export type ExportFormat = "json" | "obsidian" | "bibtex" | "csl" | "csv";

export const EXPORT_FORMATS: { format: ExportFormat; label: string; hint: string; path: string; filename: string }[] = [
  { format: "json", label: "知识备份 · JSON", hint: "完整可迁移", path: "/api/knowledge/export/json", filename: "easypaper_knowledge.json" },
  { format: "obsidian", label: "Obsidian 笔记 · ZIP", hint: "带双向链接", path: "/api/knowledge/export/obsidian", filename: "easypaper_vault.zip" },
  { format: "bibtex", label: "文献引用 · BibTeX", hint: "LaTeX", path: "/api/knowledge/export/bibtex", filename: "easypaper_references.bib" },
  { format: "csl", label: "文献引用 · CSL-JSON", hint: "Zotero", path: "/api/knowledge/export/csl-json", filename: "easypaper_references.json" },
  { format: "csv", label: "论文表格 · CSV ZIP", hint: "表格分析", path: "/api/knowledge/export/csv", filename: "easypaper_csv.zip" },
];

export async function exportKnowledge(format: ExportFormat) {
  const target = EXPORT_FORMATS.find((item) => item.format === format);
  if (!target) return;
  await downloadFile(target.path, target.filename);
}
