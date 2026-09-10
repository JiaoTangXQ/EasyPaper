# EasyPaper

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

英语较弱、希望完整读懂英文学术论文的读者。阅读目标是连续读完正文，理解论证、方法、公式和实验，而不是只获取摘要。

## Product Purpose

以完整论文页面为阅读主体。原文和翻译保持论文的页序、图表、公式与版式，中文译文、简化英文和双语对照可以切换。AI 只在用户主动提问、选文或查询术语时使用，不能用自动生成的卡片替换正文。

## Capabilities and Constraints

用户明确要求一次性整体开发，语言显示可切换，不推迟任何已有功能。保留 PDF 翻译与下载、摘要、高亮、知识库、图谱、闪卡复习、JSON / Obsidian / BibTeX / CSL-JSON / CSV 导出及 agent 接口。沿用 React、TypeScript、FastAPI、SQLModel、PyMuPDF 和兼容 OpenAI 的模型配置。

## Product Principles

- 全文忠实翻译与 AI 解释分别展示，解释不能替换正文。
- 连续阅读优先于碎片化卡片；解析出的结构只服务全文搜索、证据回链和全文问答。
- 生成内容的引用指向原始文档坐标；无法验证的引用明确缺失。
- 语言切换、查询术语和阅读图表不丢失当前位置。
- 阅读进度、用户笔记和论文原件持续保存。
- 知识整理随阅读提供，用户不必离开正文才能理解一句话。

## Evidence on Hand

仓库 README、现有前后端实现和 imgs 中的历史截图。真实翻译质量须使用配置的模型与真实论文验证；测试夹具不作为质量声明。
