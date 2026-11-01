from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import LLMConfig
from app.services.ai_client import AIClient, AIError, cursor_environment


def _fake_codex(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-codex.py"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "args=sys.argv\n"
        "out=args[args.index('--output-last-message')+1]\n"
        "sys.stdin.read()\n" + body + "\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return str(script)


def _config(executable: str) -> LLMConfig:
    return LLMConfig(provider="codex", codex={"executable": executable, "timeout_seconds": 10})


@pytest.mark.asyncio
async def test_codex_client_returns_structured_text_without_api_credentials(tmp_path, monkeypatch):
    executable = _fake_codex(
        tmp_path,
        """
print(json.dumps({'type':'thread.started','thread_id':'fixture'}))
print(json.dumps({'type':'turn.started'}))
assert '--ignore-user-config' in args and '--ignore-rules' in args and '--ephemeral' in args
assert args[args.index('--sandbox')+1] == 'read-only'
overrides = dict(args[i+1].split('=', 1) for i, arg in enumerate(args[:-1]) if arg == '--config')
for feature in ['shell_tool', 'unified_exec', 'code_mode', 'multi_agent', 'hooks', 'plugins', 'apps']:
    assert overrides['features.'+feature] == 'false'
leaked = any(os.environ.get(key) for key in ['OPENAI_API_KEY', 'EASYPAPER_SECRET_KEY', 'DATABASE_URL'])
open(out, 'w').write(json.dumps({'text': json.dumps({'answer':'ok', 'credential_leaked': leaked})}))
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'fixture'}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'cached_input_tokens':0,'output_tokens':1,'reasoning_output_tokens':0}}))
""",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("EASYPAPER_SECRET_KEY", "must-not-be-inherited")
    monkeypatch.setenv("DATABASE_URL", "must-not-be-inherited")
    result = await AIClient(_config(executable)).complete_json("Return JSON.", "hello")
    assert result == {"answer": "ok", "credential_leaked": False}


def _fake_cursor(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-cursor.py"
    script.write_text("#!/usr/bin/env python3\nimport os, sys\n" + body + "\n", encoding="utf-8")
    script.chmod(0o700)
    return str(script)


def _cursor_config(executable: str) -> LLMConfig:
    return LLMConfig(provider="cursor", cursor={"executable": executable, "timeout_seconds": 10, "model": "fixture-model"})


def test_cursor_environment_sets_user_when_missing(monkeypatch):
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    env = cursor_environment()
    assert env.get("USER")


@pytest.mark.asyncio
async def test_cursor_client_returns_text_without_application_credentials(tmp_path, monkeypatch):
    executable = _fake_cursor(
        tmp_path,
        """
args=sys.argv
assert args[1:7] == ['-p', '--mode', 'ask', '--output-format', 'text', '--sandbox']
assert args[7] == 'disabled'
assert '--force' not in args and '--yolo' not in args
assert args[args.index('--model')+1] == 'fixture-model'
assert '--workspace' in args
leaked = any(os.environ.get(key) for key in ['OPENAI_API_KEY', 'EASYPAPER_SECRET_KEY', 'DATABASE_URL', 'CURSOR_API_KEY'])
prompt = args[-1]
assert 'Return JSON.' in prompt and 'hello' in prompt
print('{"answer":"ok","credential_leaked":%s}' % ('true' if leaked else 'false'))
""",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("EASYPAPER_SECRET_KEY", "must-not-be-inherited")
    monkeypatch.setenv("DATABASE_URL", "must-not-be-inherited")
    monkeypatch.setenv("CURSOR_API_KEY", "must-not-be-inherited")
    result = await AIClient(_cursor_config(executable)).complete_json("Return JSON.", "hello")
    assert result == {"answer": "ok", "credential_leaked": False}


@pytest.mark.asyncio
async def test_cursor_client_reports_auth_failure_without_stderr(tmp_path):
    executable = _fake_cursor(
        tmp_path,
        """
print('401 secret-prompt-echo', file=sys.stderr)
sys.exit(1)
""",
    )
    with pytest.raises(AIError, match="登录失效") as caught:
        await AIClient(_cursor_config(executable)).complete("Return text.", "hello")
    assert "secret-prompt-echo" not in str(caught.value)


@pytest.mark.asyncio
async def test_codex_client_rejects_tool_events(tmp_path):
    executable = _fake_codex(
        tmp_path,
        """
print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':'echo'}}))
""",
    )
    with pytest.raises(AIError, match="终止"):
        await AIClient(_config(executable)).complete("Return text.", "hello")
