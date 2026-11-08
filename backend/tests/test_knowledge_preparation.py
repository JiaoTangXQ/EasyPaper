from app.core.config import AppConfig, KnowledgeWorkerConfig, LLMConfig, ProcessingConfig
from app.services.knowledge_preparation import remote_worker_ready, resolve_knowledge_preparation


def test_resolve_knowledge_preparation_defaults_server():
    base = AppConfig(llm=LLMConfig())
    assert resolve_knowledge_preparation(base) == "server"
    base.processing.knowledge_preparation = "remote_worker"
    assert resolve_knowledge_preparation(base) == "remote_worker"


def test_knowledge_remote_worker_ready():
    config = AppConfig(llm=LLMConfig(), knowledge_worker=KnowledgeWorkerConfig(token="secret"))
    assert remote_worker_ready(config)
    config.knowledge_worker.token = ""
    assert not remote_worker_ready(config)
