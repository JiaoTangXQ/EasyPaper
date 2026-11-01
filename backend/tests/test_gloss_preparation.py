from app.core.config import AppConfig, GlossWorkerConfig, LLMConfig, ProcessingConfig
from app.services.gloss_preparation import remote_worker_ready, resolve_gloss_preparation


def test_resolve_gloss_preparation_site_modes():
    base = AppConfig(llm=LLMConfig())
    base.processing = ProcessingConfig(gloss_preparation="server")
    assert resolve_gloss_preparation(base, {"reading": {"gloss": {"preparation": "remote_worker"}}}) == "server"

    base.processing.gloss_preparation = "remote_worker"
    assert resolve_gloss_preparation(base, {"reading": {"gloss": {"preparation": "server"}}}) == "remote_worker"

    base.processing.gloss_preparation = "user_choice"
    assert resolve_gloss_preparation(base, {"reading": {"gloss": {"preparation": "remote_worker"}}}) == "remote_worker"
    assert resolve_gloss_preparation(base, {"reading": {"gloss": {"preparation": "server"}}}) == "server"


def test_remote_worker_ready():
    config = AppConfig(llm=LLMConfig(), gloss_worker=GlossWorkerConfig(token="secret"))
    assert remote_worker_ready(config)
    config.gloss_worker.token = ""
    assert not remote_worker_ready(config)
