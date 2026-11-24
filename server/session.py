"""One WebSocket connection from a XiaoZhi device = one Session.

Pipeline for a reply (all three stages run concurrently, so the device starts
speaking after the first sentence instead of after the whole answer):

    LLM text deltas --split--> sentence queue --TTS--> opus queue --paced send--> device
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid

from aiohttp import WSMsgType, web

from . import config
from .asr import create_asr
from .audio import OpusDecoder, OpusEncoder
from .llm import create_llm
from .tools import ToolRegistry, register_builtin_tools, register_device_tools
from .tts import synthesize

FRAME_MS = 60
SEND_AHEAD_S = 0.3  # how far ahead of real time we push audio into the device buffer
MCP_TIMEOUT_S = 10
HISTORIES: dict[str, list[dict]] = {}  # device id -> chat history, survives reconnects

_STRONG_PUNCT = re.compile(r"[。！？!?；;\n]")
_WEAK_PUNCT = re.compile(r"[，,、：:]")
_MARKDOWN = re.compile(r"[*#`>_~]|\[\d+\]")


def _pop_sentence(buf: str, first: bool) -> tuple[str | None, str]:
    """Cuts a speakable sentence off the front of buf. The first one is cut
    earlier (at a comma) so the device starts talking sooner."""
    m = _STRONG_PUNCT.search(buf)
    if m:
        return buf[:m.end()], buf[m.end():]
    if first or len(buf) > 40:
        m = _WEAK_PUNCT.search(buf, 6 if first else 20)
        if m:
            return buf[:m.end()], buf[m.end():]
    return None, buf


def _trim_history(msgs: list[dict]) -> list[dict]:
    msgs = msgs[-config.HISTORY_MESSAGES:]
    while msgs and msgs[0]["role"] != "user":
        msgs = msgs[1:]
    return msgs


class Session:
    def __init__(self, ws: web.WebSocketResponse, request: web.Request):
        self.ws = ws
        self.device_id = request.headers.get("Device-Id", "unknown")
        self.session_id = uuid.uuid4().hex[:12]
        self.log = logging.getLogger(f"session[{self.device_id}]")
        self.loop = asyncio.get_running_loop()
        self._send_lock = asyncio.Lock()

        self.decoder = OpusDecoder(16000)
        self.llm = create_llm()
        self.tools = ToolRegistry()
        register_builtin_tools(self.tools)
        self.history = HISTORIES.setdefault(self.device_id, [])

        self.listen_mode = "auto"
        self.asr = None
        self.utterance: list[str] = []
        self.chat_task: asyncio.Task | None = None
        self.t_user_done = 0.0

        self._mcp_id = 0
        self._mcp_pending: dict[int, asyncio.Future] = {}
        self.mcp_task: asyncio.Task | None = None

    # ---------- transport ----------

    async def send_json(self, msg: dict) -> None:
        msg.setdefault("session_id", self.session_id)
        if msg.get("type") != "mcp":
            self.log.info("-> %s", json.dumps(msg, ensure_ascii=False))
        async with self._send_lock:
            if not self.ws.closed:
                await self.ws.send_str(json.dumps(msg, ensure_ascii=False))

    async def send_audio(self, packet: bytes) -> None:
        async with self._send_lock:
            if not self.ws.closed:
                await self.ws.send_bytes(packet)

    async def run(self) -> None:
        self.log.info("connected")
        try:
            async for msg in self.ws:
                if msg.type == WSMsgType.TEXT:
                    await self.on_text(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    self.on_audio(msg.data)
        finally:
            await self.cancel_chat()
            await self.stop_asr()
            for f in self._mcp_pending.values():
                f.cancel()
            self.log.info("disconnected")

    # ---------- device -> server ----------

    async def on_text(self, data: str) -> None:
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            self.log.warning("bad json: %s", data[:200])
            return
        t = msg.get("type")
        if t != "mcp":
            self.log.info("<- %s", data[:300])

        if t == "hello":
            await self.on_hello(msg)
        elif t == "listen":
            await self.on_listen(msg)
        elif t == "abort":
            await self.cancel_chat()
        elif t == "mcp":
            self.on_mcp(msg.get("payload") or {})

    async def on_hello(self, msg: dict) -> None:
        await self.send_json({
            "type": "hello",
            "transport": "websocket",
            "audio_params": {"format": "opus", "sample_rate": config.TTS_SAMPLE_RATE,
                             "channels": 1, "frame_duration": FRAME_MS},
        })
        if (msg.get("features") or {}).get("mcp") and self.mcp_task is None:
            self.mcp_task = asyncio.create_task(self.mcp_warmup())

    async def on_listen(self, msg: dict) -> None:
        state = msg.get("state")
        if state == "start":
            self.listen_mode = msg.get("mode", "auto")
            await self.start_asr()
        elif state == "stop":
            await self.stop_asr()
            self.finish_utterance()
        elif state == "detect":
            # Wake word fired; reply to it like a greeting.
            text = msg.get("text", "")
            if text:
                self.start_chat(text)

    def on_audio(self, packet: bytes) -> None:
        if self.asr is not None:
            self.asr.feed(self.decoder.decode(packet))

    # ---------- listening / ASR ----------

    async def start_asr(self) -> None:
        if self.asr is not None:
            return
        self.utterance = []
        try:
            self.asr = create_asr(self.loop, self.on_partial, self.on_sentence)
        except Exception as e:
            self.log.error("cannot start ASR: %s", e)
            await self.send_json({"type": "alert", "status": "错误", "message": str(e),
                                  "emotion": "sad"})

    async def stop_asr(self) -> None:
        asr, self.asr = self.asr, None
        if asr is not None:
            await asr.close()

    def on_partial(self, text: str) -> None:
        self.log.debug("partial: %s", text)

    def on_sentence(self, text: str) -> None:
        self.log.info("sentence: %s", text)
        if self.listen_mode == "manual":
            self.utterance.append(text)  # wait for "listen stop"
            return
        # Server-side end-of-speech detection: answer right away.
        asr, self.asr = self.asr, None
        if asr is None:
            return  # late result from a stream we already closed
        asyncio.create_task(asr.close())
        self.utterance.append(text)
        self.finish_utterance()

    def finish_utterance(self) -> None:
        text = "".join(self.utterance).strip()
        self.utterance = []
        if text:
            self.t_user_done = time.monotonic()
            self.start_chat(text)

    # ---------- replying ----------

    def start_chat(self, text: str) -> None:
        # Newest user input wins; the old reply must fully stop (and send its
        # "tts stop") before the new one sends "tts start".
        previous = self.chat_task
        self.chat_task = asyncio.create_task(self._chat_after(previous, text))

    async def _chat_after(self, previous: asyncio.Task | None, text: str) -> None:
        await self._cancel_task(previous)
        await self.chat(text)

    async def cancel_chat(self) -> None:
        task, self.chat_task = self.chat_task, None
        await self._cancel_task(task)

    @staticmethod
    async def _cancel_task(task: asyncio.Task | None) -> None:
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def chat(self, text: str) -> None:
        if not self.t_user_done:
            self.t_user_done = time.monotonic()
        await self.send_json({"type": "stt", "text": text})
        await self.send_json({"type": "llm", "emotion": "happy", "text": "🙂"})
        await self.send_json({"type": "tts", "state": "start"})

        if self.mcp_task and not self.mcp_task.done():
            # Wake word right after connecting: give the device a moment to list its tools.
            await asyncio.wait({self.mcp_task}, timeout=3)

        messages = [{"role": "system", "content": config.SYSTEM_PROMPT},
                    *self.history, {"role": "user", "content": text}]
        sentences: asyncio.Queue = asyncio.Queue()
        packets: asyncio.Queue = asyncio.Queue()
        workers = [asyncio.create_task(self._tts_worker(sentences, packets)),
                   asyncio.create_task(self._send_worker(packets))]
        ok = False
        try:
            buf, first = "", True
            async for delta in self.llm.chat(messages, self.tools):
                buf += _MARKDOWN.sub("", delta)
                while True:
                    sentence, buf = _pop_sentence(buf, first)
                    if sentence is None:
                        break
                    if sentence.strip():
                        await sentences.put(sentence.strip())
                        first = False
            if buf.strip():
                await sentences.put(buf.strip())
            await sentences.put(None)
            await asyncio.gather(*workers)
            ok = True
        except asyncio.CancelledError:
            self.log.info("reply interrupted")
            raise
        except Exception as e:
            self.log.exception("chat failed")
            await self.send_json({"type": "alert", "status": "出错了", "message": str(e)[:100],
                                  "emotion": "sad"})
        finally:
            for w in workers:
                w.cancel()
            self.history[:] = _trim_history(
                messages[1:] if ok else [*self.history, {"role": "user", "content": text}])
            self.t_user_done = 0.0
            await self.send_json({"type": "tts", "state": "stop"})

    async def _tts_worker(self, sentences: asyncio.Queue, packets: asyncio.Queue) -> None:
        encoder = OpusEncoder(config.TTS_SAMPLE_RATE, FRAME_MS)
        while (sentence := await sentences.get()) is not None:
            await packets.put(("sentence", sentence))
            try:
                async for pcm in synthesize(sentence):
                    for p in encoder.encode(pcm):
                        await packets.put(("audio", p))
            except Exception as e:  # skip this sentence, keep talking
                self.log.error("TTS failed for %r: %s", sentence, e)
            for p in encoder.flush():
                await packets.put(("audio", p))
        await packets.put(None)

    async def _send_worker(self, packets: asyncio.Queue) -> None:
        start, sent = None, 0
        while (item := await packets.get()) is not None:
            kind, data = item
            if kind == "sentence":
                await self.send_json({"type": "tts", "state": "sentence_start", "text": data})
                continue
            if start is None:
                start = time.monotonic()
                if self.t_user_done:
                    self.log.info("latency: %.2fs from end of speech to first audio",
                                  start - self.t_user_done)
            # Pace to real time so an abort takes effect quickly on the device.
            delay = start + sent * FRAME_MS / 1000 - SEND_AHEAD_S - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            await self.send_audio(data)
            sent += 1
        if start is not None:  # let the device finish playing before "tts stop"
            remaining = start + sent * FRAME_MS / 1000 - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)

    # ---------- MCP: the device's own tools (volume, screen, GPIO...) ----------

    async def mcp_request(self, method: str, params: dict | None = None) -> dict:
        self._mcp_id += 1
        fut = self.loop.create_future()
        self._mcp_pending[self._mcp_id] = fut
        await self.send_json({"type": "mcp", "payload": {
            "jsonrpc": "2.0", "id": self._mcp_id, "method": method, "params": params or {}}})
        try:
            payload = await asyncio.wait_for(fut, MCP_TIMEOUT_S)
        finally:
            self._mcp_pending.pop(self._mcp_id, None)
        if "error" in payload:
            raise RuntimeError(payload["error"].get("message", "MCP error"))
        return payload.get("result") or {}

    def on_mcp(self, payload: dict) -> None:
        fut = self._mcp_pending.get(payload.get("id"))
        if fut and not fut.done():
            fut.set_result(payload)

    async def mcp_warmup(self) -> None:
        try:
            await self.mcp_request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "my-xiaozhi-server", "version": "0.1"}})
            await self.send_json({"type": "mcp", "payload": {
                "jsonrpc": "2.0", "method": "notifications/initialized"}})
            tools, cursor = [], None
            while True:
                result = await self.mcp_request("tools/list", {"cursor": cursor} if cursor else {})
                tools += result.get("tools", [])
                cursor = result.get("nextCursor")
                if not cursor:
                    break

            async def call(name: str, args: dict) -> dict:
                return await self.mcp_request("tools/call", {"name": name, "arguments": args})

            register_device_tools(self.tools, tools, call)
            self.log.info("device tools: %s", [t["name"] for t in tools])
        except Exception as e:
            self.log.warning("MCP warmup failed (voice still works): %r", e)
