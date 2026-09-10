"""
PDF 翻译服务 - 使用 PDFMathTranslate (pdf2zh) 进行学术论文翻译
保留公式、图片、布局
"""

from __future__ import annotations

import logging
import os
import tempfile

from ..core.config import LLMConfig
from .pdf2zh_codex import PDFTranslationAbort, pdf2zh_backend

logger = logging.getLogger(__name__)


class PDFTranslator:
    """使用 pdf2zh 进行 PDF 翻译"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.zhizengzeng.com/v1",
        model: str = "gemini-2.5-flash",
        lang_in: str = "en",
        lang_out: str = "zh",
        thread: int = 4,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.lang_in = lang_in
        self.lang_out = lang_out
        self.thread = thread
        self.llm_config = llm_config or LLMConfig(api_key=api_key, base_url=base_url, model=model)

        # 设置环境变量供 pdf2zh 使用
        if self.llm_config.provider == "api":
            os.environ["OPENAILIKED_BASE_URL"] = base_url
            os.environ["OPENAILIKED_API_KEY"] = api_key
            os.environ["OPENAILIKED_MODEL"] = model

    def translate_pdf(
        self,
        input_path: str,
        output_dir: str | None = None,
    ) -> tuple[str | None, str | None]:
        """
        翻译 PDF 文件

        Args:
            input_path: 输入 PDF 文件路径
            output_dir: 输出目录，默认为临时目录

        Returns:
            (mono_path, dual_path): 单语版本和双语版本的路径
        """
        try:
            from pdf2zh import translate
        except ImportError:
            logger.error("pdf2zh 未安装，请运行: pip install pdf2zh")
            return None, None

        if output_dir is None:
            output_dir = tempfile.mkdtemp()

        try:
            logger.info(f"开始翻译 PDF: {input_path}")

            # 调用 pdf2zh 翻译
            with pdf2zh_backend(self.llm_config) as backend:
                results = translate(
                    files=[input_path],
                    lang_in=self.lang_in,
                    lang_out=self.lang_out,
                    thread=self.thread,
                    output=output_dir,
                    **backend,
                )

            if results and len(results) > 0:
                file_mono, file_dual = results[0]
                logger.info(f"翻译完成: mono={file_mono}, dual={file_dual}")
                return str(file_mono) if file_mono else None, str(file_dual) if file_dual else None

            logger.warning("翻译返回空结果")
            return None, None

        except (Exception, PDFTranslationAbort) as e:
            logger.error(f"PDF 翻译失败: {e}")
            return None, None

    def translate_pdf_stream(
        self,
        pdf_bytes: bytes,
    ) -> tuple[bytes | None, bytes | None]:
        """
        翻译 PDF 字节流

        Args:
            pdf_bytes: PDF 文件的字节内容

        Returns:
            (mono_bytes, dual_bytes): 单语版本和双语版本的字节内容
        """
        try:
            from pdf2zh import translate_stream
        except ImportError:
            logger.error("pdf2zh 未安装，请运行: pip install pdf2zh")
            return None, None

        try:
            logger.info("开始翻译 PDF 流")

            # 调用 pdf2zh 流式翻译
            with pdf2zh_backend(self.llm_config) as backend:
                stream_mono, stream_dual = translate_stream(
                    stream=pdf_bytes,
                    lang_in=self.lang_in,
                    lang_out=self.lang_out,
                    thread=self.thread,
                    **backend,
                )

            logger.info("PDF 流翻译完成")
            return stream_mono, stream_dual

        except (Exception, PDFTranslationAbort) as e:
            logger.error(f"PDF 流翻译失败: {e}")
            return None, None


def create_translator_from_config(config) -> PDFTranslator:
    """从配置创建翻译器"""
    return PDFTranslator(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        llm_config=config.llm,
    )
