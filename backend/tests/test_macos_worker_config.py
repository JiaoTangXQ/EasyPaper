from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_macos_worker_defaults_to_api_provider() -> None:
    run_script = (ROOT / "deploy/macos/gloss-worker-run.sh").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy/macos/gloss-worker.env.example").read_text(encoding="utf-8")

    assert 'EASYPAPER_AI_PROVIDER="${EASYPAPER_AI_PROVIDER:-api}"' in run_script
    assert "EASYPAPER_AI_PROVIDER=api" in env_example
