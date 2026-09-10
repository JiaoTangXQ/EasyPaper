"""Translation records must include cache hits and remain isolated between jobs."""

from concurrent.futures import ThreadPoolExecutor
from types import ModuleType, SimpleNamespace

from app.core.config import LLMConfig
from app.services.pdf2zh_codex import pdf2zh_backend


def test_records_cached_translation_and_isolates_concurrent_documents(monkeypatch):
    import sys

    class Translator:
        name = "openailiked"

        def __init__(self, *args, **kwargs):
            self.cache = {}

        def translate(self, text):
            return self.cache.setdefault(text, text + " translated")

    class Converter:
        def __init__(self, translator):
            self.translator = translator

        def receive_layout(self, page):
            return self.translator.translate(page.text)

    converter = SimpleNamespace(OpenAIlikedTranslator=Translator, TranslateConverter=Converter)
    package, translators = ModuleType("pdf2zh"), ModuleType("pdf2zh.translator")
    package.converter = converter
    translators.BaseTranslator = object
    monkeypatch.setitem(sys.modules, "pdf2zh", package)
    monkeypatch.setitem(sys.modules, "pdf2zh.translator", translators)
    records_a, records_b = [], []
    with (
        pdf2zh_backend(LLMConfig(api_key="fixture"), records=records_a) as a,
        pdf2zh_backend(LLMConfig(api_key="fixture"), records=records_b) as b,
    ):
        one = Converter(converter.OpenAIlikedTranslator("en", "zh", "test", envs=a["envs"]))
        two = Converter(converter.OpenAIlikedTranslator("en", "zh", "test", envs=b["envs"]))
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(one.receive_layout, SimpleNamespace(pageid=2, text="First paper"))
            second = pool.submit(two.receive_layout, SimpleNamespace(pageid=7, text="Second paper"))
            assert first.result() == "First paper translated"
            assert second.result() == "Second paper translated"
        # A later page uses a cached paragraph: it must still be recorded on that page.
        one.receive_layout(SimpleNamespace(pageid=3, text="First paper"))
    assert records_a == [{"source": "First paper", "target": "First paper translated", "page": str(p)} for p in (2, 3)]
    assert records_b == [{"source": "Second paper", "target": "Second paper translated", "page": "7"}]
