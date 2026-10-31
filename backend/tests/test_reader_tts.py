import sys
from types import SimpleNamespace

import pytest

from app.services.reader_tts import ReaderTTS, ReaderTTSUnavailable


@pytest.mark.asyncio
async def test_reader_tts_streams_audio_and_reuses_the_bounded_cache(monkeypatch):
    calls = []

    class FakeCommunicate:
        def __init__(self, text, voice, rate):
            calls.append((text, voice, rate))

        async def stream(self):
            yield {"type": "WordBoundary", "data": b"ignored"}
            yield {"type": "audio", "data": b"ID3"}
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))
    tts = ReaderTTS(cache_limit=1)

    assert await tts.synthesize("  adequate  ") == b"ID3audio"
    assert await tts.synthesize("adequate") == b"ID3audio"
    assert calls == [("adequate", "en-US-JennyNeural", "-8%")]


@pytest.mark.asyncio
async def test_reader_tts_wraps_provider_failures(monkeypatch):
    class BrokenCommunicate:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("network down")

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=BrokenCommunicate))
    with pytest.raises(ReaderTTSUnavailable):
        await ReaderTTS().synthesize("word")


@pytest.mark.asyncio
async def test_reader_tts_rejects_empty_and_oversized_text():
    tts = ReaderTTS()
    with pytest.raises(ValueError):
        await tts.synthesize(" \n ")
    with pytest.raises(ValueError):
        await tts.synthesize("x" * 241)
