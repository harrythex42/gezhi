"""Pretends to be a XiaoZhi ESP32 board, using the Mac's mic and speaker.

It speaks exactly the same protocol as the real firmware (OTA -> WebSocket
hello -> listen/Opus audio -> tts/MCP), so the server can be built and tested
before the board arrives.

    .venv/bin/python -m simulator.fake_device                 # Enter to talk, Enter to stop
    .venv/bin/python -m simulator.fake_device --auto          # hands-free, server detects end of speech
    .venv/bin/python -m simulator.fake_device --text "你好"    # no mic needed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import uuid
import wave

import aiohttp

from server.audio import OpusDecoder, OpusEncoder

DEVICE_ID = "02:00:00:00:00:01"
CLIENT_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "fake-xiaozhi"))
FAKE_TOOLS = [{
    "name": "self.audio_speaker.set_volume",
    "description": "Set the volume of the audio speaker (0-100).",
    "inputSchema": {"type": "object", "properties": {
        "volume": {"type": "integer", "minimum": 0, "maximum": 100}}, "required": ["volume"]},
}, {
    "name": "self.light.set_on",
    "description": "Turn the LED light on the device on or off.",
    "inputSchema": {"type": "object", "properties": {"on": {"type": "boolean"}},
                    "required": ["on"]},
}]


class Speaker:
    """Plays 24 kHz PCM through the Mac speaker (or collects it into a wav)."""

    def __init__(self, play: bool):
        self.buf = bytearray()
        self.all = bytearray()
        self.lock = threading.Lock()
        self.stream = None
        if play:
            import sounddevice as sd
            self.stream = sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16",
                                             callback=self._callback)
            self.stream.start()

    def _callback(self, outdata, frames, _time, _status):
        n = frames * 2
        with self.lock:
            chunk = bytes(self.buf[:n])
            del self.buf[:n]
        outdata[:] = chunk + b"\x00" * (n - len(chunk))

    def write(self, pcm: bytes) -> None:
        with self.lock:
            self.buf += pcm
        self.all += pcm

    def clear(self) -> None:
        with self.lock:
            self.buf.clear()

    def save(self, path: str) -> None:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(bytes(self.all))


class FakeDevice:
    def __init__(self, args):
        self.args = args
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.session_id = ""
        self.speaker = Speaker(play=not args.no_play)
        self.decoder = OpusDecoder(24000)
        self.encoder = OpusEncoder(16000, 60, 24000)
        self.mic_on = False
        self.state = "idle"
        self.tts_stopped: asyncio.Event | None = None  # created inside the running loop (py3.9)
        self.audio_frames = 0

    async def send(self, msg: dict) -> None:
        msg.setdefault("session_id", self.session_id)
        await self.ws.send_str(json.dumps(msg, ensure_ascii=False))

    async def ota(self, http: aiohttp.ClientSession) -> tuple[str, str]:
        body = {"version": 2, "uuid": CLIENT_ID, "mac_address": DEVICE_ID,
                "chip_model_name": "esp32s3", "application": {"name": "xiaozhi", "version": "2.0.0"},
                "board": {"type": "fake-mac", "name": "fake-mac"},
                "protocol": {"features": {"mcp": True}}}
        headers = {"Device-Id": DEVICE_ID, "Client-Id": CLIENT_ID,
                   "User-Agent": "fake-mac/2.0.0", "Activation-Version": "1"}
        async with http.post(self.args.ota, json=body, headers=headers) as r:
            r.raise_for_status()
            cfg = await r.json()
        print(f"[ota] websocket = {cfg['websocket']['url']}")
        return cfg["websocket"]["url"], cfg["websocket"].get("token", "")

    async def run(self) -> None:
        self.tts_stopped = asyncio.Event()
        async with aiohttp.ClientSession() as http:
            url, token = await self.ota(http)
            if self.args.local:
                url = url.split("://", 1)[0] + "://127.0.0.1:" + url.rsplit(":", 1)[1]
            headers = {"Protocol-Version": "1", "Device-Id": DEVICE_ID, "Client-Id": CLIENT_ID}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            async with http.ws_connect(url, headers=headers) as ws:
                self.ws = ws
                await self.send({"type": "hello", "version": 1, "features": {"mcp": True},
                                 "transport": "websocket",
                                 "audio_params": {"format": "opus", "sample_rate": 16000,
                                                  "channels": 1, "frame_duration": 60}})
                receiver = asyncio.create_task(self.receive())
                try:
                    if self.args.text:
                        await self.text_mode()
                    else:
                        await self.voice_mode()
                finally:
                    receiver.cancel()
        if self.args.no_play:
            self.speaker.save(self.args.save)
            print(f"[audio] saved {len(self.speaker.all) / 48000:.1f}s to {self.args.save}")

    async def receive(self) -> None:
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                self.audio_frames += 1
                if self.state == "speaking":
                    self.speaker.write(self.decoder.decode(msg.data))
                continue
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            t = m.get("type")
            if t == "hello":
                self.session_id = m.get("session_id", "")
                print(f"[hello] server audio_params={m.get('audio_params')}")
            elif t == "stt":
                print(f"\n你  > {m['text']}")
            elif t == "tts":
                if m["state"] == "start":
                    self.state, self.mic_on = "speaking", False
                    self.tts_stopped.clear()
                elif m["state"] == "sentence_start":
                    print(f"小智 > {m['text']}")
                elif m["state"] == "stop":
                    self.state = "idle"
                    self.tts_stopped.set()
            elif t == "mcp":
                await self.on_mcp(m["payload"])
            elif t == "alert":
                print(f"[alert] {m.get('status')}: {m.get('message')}")

    async def on_mcp(self, p: dict) -> None:
        method, pid = p.get("method"), p.get("id")
        if pid is None:
            return  # notification
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake-mac", "version": "2.0.0"}}
        elif method == "tools/list":
            result = {"tools": FAKE_TOOLS}
        elif method == "tools/call":
            print(f"[mcp] 设备执行工具 {p['params']['name']} {p['params'].get('arguments')}")
            result = {"content": [{"type": "text", "text": "true"}], "isError": False}
        else:
            await self.send({"type": "mcp", "payload": {
                "jsonrpc": "2.0", "id": pid, "error": {"code": -32601, "message": "Method not found"}}})
            return
        await self.send({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": pid, "result": result}})

    async def text_mode(self) -> None:
        # Real firmware sends "detect" with the wake word text; we reuse it to inject any text.
        await self.send({"type": "listen", "state": "detect", "text": self.args.text})
        await asyncio.wait_for(self.tts_stopped.wait(), 120)
        await asyncio.sleep(0.5)
        print(f"[done] received {self.audio_frames} opus frames")

    async def voice_mode(self) -> None:
        import sounddevice as sd

        loop = asyncio.get_running_loop()
        mic: asyncio.Queue = asyncio.Queue()

        def on_mic(indata, _frames, _time, _status):
            loop.call_soon_threadsafe(mic.put_nowait, bytes(indata))

        async def pump_mic():
            while True:
                pcm = await mic.get()
                if self.mic_on:
                    for p in self.encoder.encode(pcm):
                        await self.ws.send_bytes(p)

        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=960,
                               callback=on_mic):
            pump = asyncio.create_task(pump_mic())
            try:
                if self.args.auto:
                    await self.auto_loop()
                else:
                    await self.manual_loop()
            finally:
                pump.cancel()

    async def manual_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, input, "\n[回车] 开始说话（Ctrl+C 退出）")
            if self.state == "speaking":
                self.speaker.clear()
                await self.send({"type": "abort", "reason": "button"})
            await self.send({"type": "listen", "state": "start", "mode": "manual"})
            self.state, self.mic_on = "listening", True
            await loop.run_in_executor(None, input, "正在听…… [回车] 说完了")
            self.mic_on = False
            await self.send({"type": "listen", "state": "stop"})
            self.state = "idle"

    async def auto_loop(self) -> None:
        print("\n免提模式：直接说话，说完停顿一下即可（Ctrl+C 退出）")
        while True:
            await self.send({"type": "listen", "state": "start", "mode": "auto"})
            self.state, self.mic_on = "listening", True
            self.tts_stopped.clear()
            await self.tts_stopped.wait()  # server detects end of speech, replies, then stops
            await asyncio.sleep(0.3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--ota", default="http://127.0.0.1:8000/xiaozhi/ota/")
    ap.add_argument("--text", help="send this text instead of using the microphone")
    ap.add_argument("--auto", action="store_true", help="hands-free mode (server-side VAD)")
    ap.add_argument("--no-play", action="store_true", help="don't play audio, save it to --save")
    ap.add_argument("--save", default="reply.wav")
    ap.add_argument("--local", action="store_true", help="connect WebSocket via 127.0.0.1")
    args = ap.parse_args()
    try:
        asyncio.run(FakeDevice(args).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
