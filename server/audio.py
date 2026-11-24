"""Opus / MP3 <-> PCM helpers built on PyAV (bundles libopus, no brew needed).

All PCM here is signed 16-bit little-endian mono bytes.
"""
from __future__ import annotations

import av
import numpy as np


def _frame_to_pcm(frames, resampler: av.AudioResampler) -> bytes:
    out = bytearray()
    for fr in frames:
        for r in resampler.resample(fr):
            out += r.to_ndarray().astype(np.int16).tobytes()
    return bytes(out)


class OpusDecoder:
    """Decodes raw Opus packets (one per WebSocket binary frame) to PCM."""

    def __init__(self, sample_rate: int = 16000):
        self.ctx = av.CodecContext.create("libopus", "r")
        self.ctx.sample_rate = sample_rate
        self.ctx.layout = "mono"
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)

    def decode(self, packet: bytes) -> bytes:
        try:
            return _frame_to_pcm(self.ctx.decode(av.Packet(packet)), self.resampler)
        except av.error.InvalidDataError:
            return b""


class OpusEncoder:
    """Encodes PCM to Opus packets of a fixed frame duration."""

    def __init__(self, sample_rate: int = 24000, frame_ms: int = 60, bitrate: int = 32000):
        self.sample_rate = sample_rate
        self.frame_samples = sample_rate * frame_ms // 1000
        self.ctx = av.CodecContext.create("libopus", "w")
        self.ctx.sample_rate = sample_rate
        self.ctx.layout = "mono"
        self.ctx.format = "s16"
        self.ctx.bit_rate = bitrate
        self.ctx.options = {"frame_duration": str(frame_ms), "application": "audio"}
        self.ctx.open()
        self._buf = bytearray()
        self._pts = 0

    def _encode_frame(self, chunk: bytes) -> list[bytes]:
        arr = np.frombuffer(chunk, dtype=np.int16).reshape(1, -1)
        fr = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
        fr.sample_rate = self.sample_rate
        fr.pts = self._pts
        self._pts += self.frame_samples
        return [bytes(p) for p in self.ctx.encode(fr)]

    def encode(self, pcm: bytes) -> list[bytes]:
        self._buf += pcm
        size = self.frame_samples * 2
        packets: list[bytes] = []
        while len(self._buf) >= size:
            packets += self._encode_frame(bytes(self._buf[:size]))
            del self._buf[:size]
        return packets

    def flush(self) -> list[bytes]:
        """Pads the remaining samples to a full frame (end of a sentence)."""
        if not self._buf:
            return []
        size = self.frame_samples * 2
        chunk = bytes(self._buf) + b"\x00" * (size - len(self._buf))
        self._buf.clear()
        return self._encode_frame(chunk)


class Mp3StreamDecoder:
    """Decodes an MP3 byte stream chunk by chunk (edge-tts output) to PCM."""

    def __init__(self, sample_rate: int = 24000):
        self.ctx = av.CodecContext.create("mp3", "r")
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)

    def feed(self, data: bytes) -> bytes:
        out = bytearray()
        for pkt in self.ctx.parse(data):
            out += _frame_to_pcm(self.ctx.decode(pkt), self.resampler)
        return bytes(out)

    def flush(self) -> bytes:
        out = bytearray()
        for pkt in self.ctx.parse(None):
            out += _frame_to_pcm(self.ctx.decode(pkt), self.resampler)
        out += _frame_to_pcm(self.ctx.decode(None), self.resampler)
        return bytes(out)
