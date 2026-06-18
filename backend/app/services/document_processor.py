"""
文档处理器 - 使用 PDFMathTranslate (pdf2zh) 进行学术论文翻译/简化
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from string import Template

from ..core.config import AppConfig
from ..models.task import TaskResult, TaskStatus
from .highlighter import HighlightService
from .task_manager import TaskManager

logger = logging.getLogger(__name__)

SIMPLIFY_PROMPT = Template(
    "You are an expert at simplifying academic English. "
    "Rewrite the following text using simple, everyday vocabulary "
    "(CEFR A2/B1 level, approximately 2000 common English words). "
    "Keep the same meaning. Keep all formula notations {v*} unchanged. "
    "Output only the rewritten text, nothing else.\n\n"
    "Source Text: $text\n\n"
    "Simplified Text:"
)


class DocumentProcessingError(RuntimeError):
    """可直接展示给任务状态的处理错误。"""


class DocumentProcessor:
    def __init__(self, config: AppConfig, task_manager: TaskManager) -> None:
        self.config = config
        self.task_manager = task_manager
        self._configure_pdf2zh_env()

    async def process(
        self, task_id: str, file_bytes: bytes, filename: str, mode: str = "translate", highlight: bool = False
    ) -> None:
        """使用 pdf2zh 处理 PDF 文档"""

        if mode == "simplify":
            self.task_manager.update_progress(task_id, TaskStatus.PARSING, 10, "正在准备简化...")
        else:
            self.task_manager.update_progress(task_id, TaskStatus.PARSING, 10, "正在准备翻译...")

        try:
            # 在线程中运行 pdf2zh（同步库）。pdf2zh 的 LLM 配置通过进程级环境变量传入，
            # 已在 __init__ 中设置好，且对所有任务一致，因此无需在每次翻译时加锁切换环境
            # （旧实现会因此把所有并发翻译串行化）。多个翻译可在此并发执行。
            result = await asyncio.to_thread(
                self._translate_with_pdf2zh,
                file_bytes,
                filename,
                task_id,
                mode,
            )

            pdf_bytes, output_filename, dual_pdf_bytes = result

            # 高亮后处理
            if highlight and pdf_bytes:
                self.task_manager.update_progress(task_id, TaskStatus.HIGHLIGHTING, 85, "正在使用 AI 标注关键句...")
                try:
                    highlight_service = HighlightService(
                        api_key=self.config.llm.api_key,
                        model=self.config.llm.model,
                        base_url=self.config.llm.base_url,
                    )
                    async with highlight_service:
                        pdf_bytes, stats, highlight_sentences = await highlight_service.highlight_pdf_with_metadata(
                            pdf_bytes
                        )
                        self.task_manager.set_highlight_result(
                            task_id,
                            stats_json=json.dumps(stats.to_dict()),
                            status=self._build_highlight_status(stats),
                            sentences_json=json.dumps(highlight_sentences, ensure_ascii=False),
                        )
                        logger.info(f"Task {task_id} 高亮完成: {stats.total} sentences highlighted")
                except Exception as exc:
                    logger.warning("Highlight post-processing failed, using non-highlighted PDF: %s", exc)
                    self.task_manager.set_highlight_result(
                        task_id,
                        stats_json=json.dumps(
                            {
                                "core_conclusions": 0,
                                "method_innovations": 0,
                                "key_data": 0,
                                "total": 0,
                                "failed_matches": 0,
                            }
                        ),
                        status="failed",
                        sentences_json="[]",
                    )

            # 生成简单的预览 HTML
            preview_html = self._build_simple_preview(mode)

            task_result = TaskResult(
                pdf_bytes=pdf_bytes,
                dual_pdf_bytes=dual_pdf_bytes,
                preview_html=preview_html,
                filename=output_filename,
            )

            self.task_manager.set_result(task_id, task_result)
            logger.info(f"Task {task_id} 处理完成 (mode={mode})")

        except DocumentProcessingError as exc:
            logger.error("处理失败: %s", exc)
            self.task_manager.set_error(task_id, str(exc))
        except Exception as exc:
            logger.exception("处理失败: %s", exc)
            self.task_manager.set_error(task_id, f"处理失败: {exc}")

    def _translate_with_pdf2zh(
        self,
        file_bytes: bytes,
        filename: str,
        task_id: str,
        mode: str = "translate",
    ) -> tuple[bytes, str, bytes | None]:
        """调用 pdf2zh 进行翻译或简化"""

        try:
            from pdf2zh import translate
            from pdf2zh.doclayout import DocLayoutModel
        except ImportError as exc:
            raise DocumentProcessingError("pdf2zh 未安装，请运行: pip install pdf2zh") from exc

        # 加载 DocLayout-YOLO 模型
        model = DocLayoutModel.load_available()

        # 根据模式设置目标语言
        lang_out = "zh" if mode == "translate" else "en"

        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            # 保存输入文件
            input_path = Path(temp_dir) / filename
            input_path.write_bytes(file_bytes)

            logger.info(f"开始处理: {input_path} (mode={mode}, lang_out={lang_out})")

            # 更新进度
            if mode == "simplify":
                self.task_manager.update_progress(task_id, TaskStatus.REWRITING, 30, "正在使用 AI 简化...")
            else:
                self.task_manager.update_progress(task_id, TaskStatus.REWRITING, 30, "正在使用 AI 翻译...")

            try:
                # 调用 pdf2zh
                results = translate(
                    files=[str(input_path)],
                    lang_in="en",
                    lang_out=lang_out,
                    service="openailiked",
                    thread=4,
                    output=temp_dir,
                    model=model,
                    prompt=SIMPLIFY_PROMPT if mode == "simplify" else None,
                    ignore_cache=mode == "simplify",
                )

                if not results or len(results) == 0:
                    raise DocumentProcessingError("pdf2zh 返回空结果")

                file_mono, file_dual = results[0]

                # 更新进度
                self.task_manager.update_progress(task_id, TaskStatus.RENDERING, 80, "正在生成 PDF...")

                # 默认使用单语版本；双语版本作为单独下载选项保存。
                output_file = file_mono if file_mono else file_dual

                if output_file and Path(output_file).exists():
                    pdf_bytes = Path(output_file).read_bytes()
                    dual_pdf_bytes = None
                    # Only translation produces a meaningful bilingual PDF; the
                    # "dual" output of simplify is English-vs-English, so skip it.
                    if (
                        mode == "translate"
                        and file_dual
                        and Path(file_dual).exists()
                        and Path(file_dual) != Path(output_file)
                    ):
                        dual_pdf_bytes = Path(file_dual).read_bytes()
                    prefix = "translated" if mode == "translate" else "simplified"
                    output_filename = f"{prefix}_{Path(filename).stem}.pdf"
                    logger.info(f"处理完成: {output_file}")
                    return pdf_bytes, output_filename, dual_pdf_bytes

                raise DocumentProcessingError("pdf2zh 输出文件不存在")

            except Exception as e:
                logger.exception(f"pdf2zh 处理失败: {e}")
                if isinstance(e, DocumentProcessingError):
                    raise
                raise DocumentProcessingError(f"pdf2zh 处理失败: {e}") from e

    def _configure_pdf2zh_env(self) -> None:
        """Publish the LLM config to the process env that pdf2zh reads.

        Set once at construction. All tasks share the same config, so there is no
        per-task variation to guard against — keeping the env stable lets multiple
        translations run concurrently (bounded by processing.max_concurrent).
        """
        os.environ["OPENAILIKED_BASE_URL"] = self.config.llm.base_url
        os.environ["OPENAILIKED_API_KEY"] = self.config.llm.api_key
        os.environ["OPENAILIKED_MODEL"] = self.config.llm.model

    def _build_simple_preview(self, mode: str = "translate") -> str:
        """生成简单的预览 HTML"""
        if mode == "simplify":
            return """
        <div style="padding: 20px; text-align: center; color: #666;">
            <p>PDF 简化完成，请下载查看。</p>
            <p style="font-size: 12px;">使用 PDFMathTranslate 技术，保留公式和布局。</p>
        </div>
        """
        return """
        <div style="padding: 20px; text-align: center; color: #666;">
            <p>PDF 翻译完成，请下载查看。</p>
            <p style="font-size: 12px;">使用 PDFMathTranslate 技术，保留公式和布局。</p>
        </div>
        """

    def _build_highlight_status(self, stats) -> str:  # noqa: ANN001
        if stats.total > 0 and stats.failed_matches == 0:
            return "success"
        if stats.total > 0:
            return "partial"
        return "failed"
