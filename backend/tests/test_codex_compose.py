from pathlib import Path

import yaml


def test_codex_compose_propagates_proxy_and_bypasses_internal_health_checks():
    compose_path = Path(__file__).parents[2] / "deploy" / "compose.codex.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    environment = compose["services"]["backend"]["environment"]

    assert environment["EASYPAPER_DOWNLOAD_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["HTTP_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["HTTPS_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["ALL_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["NO_PROXY"] == "${EASYPAPER_NO_PROXY:-localhost,127.0.0.1,db}"
    assert environment["no_proxy"] == "${EASYPAPER_NO_PROXY:-localhost,127.0.0.1,db}"


def test_production_compose_propagates_proxy_for_http_api_provider():
    compose_path = Path(__file__).parents[2] / "docker-compose.prod.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    environment = compose["services"]["backend"]["environment"]

    assert environment["EASYPAPER_DOWNLOAD_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["HTTP_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["HTTPS_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["ALL_PROXY"] == "${EASYPAPER_DOWNLOAD_PROXY:-}"
    assert environment["NO_PROXY"] == "${EASYPAPER_NO_PROXY:-localhost,127.0.0.1,db}"
    assert environment["no_proxy"] == "${EASYPAPER_NO_PROXY:-localhost,127.0.0.1,db}"
