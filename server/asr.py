"""Streaming speech recognition.

An ASR stream receives 16 kHz PCM via feed() and reports results through two
asyncio-side callbacks: on_partial(text) while speaking and on_sentence(text)
when the service detects the end of a sentence (this doubles as our VAD).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from . import config

log = logging.getLogger("asr")


class DashScopeASR:
    def __init__(self, loop: asyncio.AbstractEventLoop,
                 on_partial: Callable[[str], None], on_sentence: Callable[[str], None]):
        import dashscope
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

        dashscope.api_key = config.DASHSCOPE_API_KEY

        class _Callback(RecognitionCallback):
            def on_event(self, result: RecognitionResult) -> None:
                sentence = result.get_sentence()
                if not isinstance(sentence, dict) or not sentence.get("text"):
                    return
                text = sentence["text"]
                cb = on_sentence if RecognitionResult.is_sentence_end(sentence) else on_partial
                loop.call_soon_threadsafe(cb, text)

            def on_error(self, result: RecognitionResult) -> None:
                log.error("ASR error: %s", result.message)

        self._rec = Recognition(model=config.ASR_MODEL, format="pcm", sample_rate=16000,
                                callback=_Callback())
        self._rec.start()
        self._closed = False

    def feed(self, pcm: bytes) -> None:
        if not self._closed and pcm:
            try:
                self._rec.send_audio_frame(pcm)
            except Exception as e:  # stream may already be gone
                log.warning("ASR send failed: %s", e)
                self._closed = True

    async def close(self) -> None:
        """Flushes remaining audio; pending sentence results are delivered before returning."""
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.to_thread(self._rec.stop)
        except Exception as e:
            log.warning("ASR stop failed: %s", e)


def create_asr(loop, on_partial, on_sentence):
    if config.ASR_PROVIDER == "dashscope":
        if not config.DASHSCOPE_API_KEY:
            raise RuntimeError("DASHSCOPE_API_KEY 未设置，无法做语音识别")
        return DashScopeASR(loop, on_partial, on_sentence)
    raise ValueError(f"Unknown ASR_PROVIDER: {config.ASR_PROVIDER}")
