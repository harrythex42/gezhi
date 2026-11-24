"""Text-to-speech. synthesize() yields 24 kHz PCM chunks as they arrive.

Providers:
  edge       free Microsoft Edge voices, no key, but unofficial and sometimes rate-limited
  dashscope  Alibaba CosyVoice, uses DASHSCOPE_API_KEY, more stable and lower latency
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import edge_tts

from . import config
from .audio import Mp3StreamDecoder

log = logging.getLogger("tts")
RETRIES = 3


async def _edge(text: str) -> AsyncIterator[bytes]:
    for attempt in range(1, RETRIES + 1):
        decoder = Mp3StreamDecoder(config.TTS_SAMPLE_RATE)
        got_audio = False
        try:
            async for chunk in edge_tts.Communicate(text, config.TTS_VOICE).stream():
                if chunk["type"] == "audio":
                    pcm = decoder.feed(chunk["data"])
                    if pcm:
                        got_audio = True
                        yield pcm
            tail = decoder.flush()
            if tail:
                yield tail
            return
        except Exception as e:
            if got_audio or attempt == RETRIES:
                raise
            log.warning("edge-tts failed (%s), retry %d/%d", e, attempt, RETRIES - 1)
            await asyncio.sleep(0.3 * attempt)


async def _dashscope(text: str) -> AsyncIterator[bytes]:
    import dashscope
    from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer

    dashscope.api_key = config.DASHSCOPE_API_KEY
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    put = lambda item: loop.call_soon_threadsafe(queue.put_nowait, item)  # noqa: E731

    class _Callback(ResultCallback):
        def on_data(self, data: bytes) -> None:
            put(bytes(data))

        def on_complete(self) -> None:
            put(None)

        def on_error(self, message) -> None:
            put(RuntimeError(f"CosyVoice error: {message}"))

    synth = SpeechSynthesizer(model=config.COSYVOICE_MODEL, voice=config.COSYVOICE_VOICE,
                              format=AudioFormat.PCM_24000HZ_MONO_16BIT, callback=_Callback())

    def run() -> None:
        try:
            synth.call(text)
        except Exception as e:
            put(e)

    asyncio.get_running_loop().run_in_executor(None, run)
    while True:
        item = await queue.get()
        if item is None:
            return
        if isinstance(item, Exception):
            raise item
        yield item


def provider() -> str:
    if config.TTS_PROVIDER:
        return config.TTS_PROVIDER
    return "dashscope" if config.DASHSCOPE_API_KEY else "edge"


async def synthesize(text: str) -> AsyncIterator[bytes]:
    gen = _dashscope(text) if provider() == "dashscope" else _edge(text)
    async for pcm in gen:
        yield pcm
