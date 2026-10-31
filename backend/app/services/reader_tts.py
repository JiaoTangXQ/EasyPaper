"""Natural speech for the reader's word and phrase lookup card."""

from __future__ import annotations

import asyncio
from collections import OrderedDict

MAX_TTS_CHARS = 240
DEFAULT_TTS_VOICE = "en-US-JennyNeural"


class ReaderTTSUnavailable(RuntimeError):
    """Raised when the online neural voice cannot be reached."""


class ReaderTTS:
    """Small bounded cache around Microsoft's Edge neural speech endpoint.

    The cache is deliberately process-local: generated audio is short, private
    to a signed-in reader, and should never become durable application data.
    """

    def __init__(self, voice: str = DEFAULT_TTS_VOICE, cache_limit: int = 128, concurrency: int = 4):
        self.voice = voice
        self.cache_limit = cache_limit
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._slots = asyncio.Semaphore(max(1, concurrency))

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(text.split())

    async def synthesize(self, text: str) -> bytes:
        text = self.normalize(text)
        if not text:
            raise ValueError("语音文本不能为空")
        if len(text) > MAX_TTS_CHARS:
            raise ValueError(f"语音文本不能超过 {MAX_TTS_CHARS} 个字符")
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            return cached

        lock = self._locks.setdefault(text, asyncio.Lock())
        async with lock:
            cached = self._cache.get(text)
            if cached is not None:
                self._cache.move_to_end(text)
                return cached
            try:
                import edge_tts

                async with self._slots:
                    speech = edge_tts.Communicate(text, voice=self.voice, rate="-8%")
                    chunks: list[bytes] = []
                    async for chunk in speech.stream():
                        if chunk["type"] == "audio":
                            chunks.append(chunk["data"])
            except ValueError:
                raise
            except Exception as exc:  # pragma: no cover - depends on external service
                raise ReaderTTSUnavailable("在线自然语音暂时不可用") from exc

            audio = b"".join(chunks)
            if not audio:
                raise ReaderTTSUnavailable("在线自然语音返回了空音频")
            self._cache[text] = audio
            self._cache.move_to_end(text)
            while len(self._cache) > self.cache_limit:
                self._cache.popitem(last=False)
            return audio
