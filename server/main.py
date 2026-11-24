"""Self-hosted XiaoZhi-compatible server.

    POST /xiaozhi/ota/   device asks where the WebSocket server is
    GET  /xiaozhi/v1/    WebSocket: hello / listen / audio / tts / mcp

Run:  .venv/bin/python -m server.main
"""
from __future__ import annotations

import logging
import socket
import subprocess
import time

from aiohttp import web

from . import config, tts
from .session import Session

log = logging.getLogger("server")
WS_PATH = "/xiaozhi/v1/"


def lan_ip() -> str:
    # Prefer the Wi-Fi/Ethernet interface: proxy tools (Clash, Surge...) add a
    # virtual 198.18.x.x route that the ESP32 cannot reach.
    for iface in ("en0", "en1"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True,
                                text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ip = ""
        if ip:
            return ip
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))  # no packet is sent; just picks the outbound interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ws_url() -> str:
    return f"ws://{config.PUBLIC_HOST or lan_ip()}:{config.PORT}{WS_PATH}"


async def ota(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.Response(text=f"OTA OK. WebSocket: {ws_url()}\n")
    try:
        body = await request.json()
    except Exception:
        body = {}
    version = (body.get("application") or {}).get("version", "0.0.0")
    log.info("OTA from %s (%s, fw %s)", request.headers.get("Device-Id"),
             (body.get("board") or {}).get("name", "?"), version)
    # No "mqtt" key -> the device uses WebSocket. No "activation" -> already bound.
    return web.json_response({
        "websocket": {"url": ws_url(), "token": config.SERVER_TOKEN},
        "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 480},
        "firmware": {"version": version, "url": ""},
    })


async def websocket(request: web.Request) -> web.StreamResponse:
    if config.SERVER_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth.removeprefix("Bearer ").strip() != config.SERVER_TOKEN:
            log.warning("rejected device %s: bad token", request.headers.get("Device-Id"))
            raise web.HTTPUnauthorized()
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4 * 1024 * 1024)
    await ws.prepare(request)
    await Session(ws, request).run()
    return ws


def make_app() -> web.Application:
    app = web.Application()
    for path in ("/xiaozhi/ota/", "/xiaozhi/ota"):
        app.router.add_route("*", path, ota)
    app.router.add_get(WS_PATH, websocket)
    app.router.add_get(WS_PATH.rstrip("/"), websocket)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("dashscope", "httpx", "openai", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print(f"\n  OTA 地址（填到设备里）: http://{config.PUBLIC_HOST or lan_ip()}:{config.PORT}/xiaozhi/ota/")
    print(f"  WebSocket 地址:          {ws_url()}")
    tts_name = (f"cosyvoice {config.COSYVOICE_VOICE}" if tts.provider() == "dashscope"
                else f"edge-tts {config.TTS_VOICE}")
    print(f"  LLM: {config.LLM_PROVIDER} / {config.LLM_MODEL}   ASR: {config.ASR_PROVIDER}   "
          f"TTS: {tts_name}\n")
    if not config.DASHSCOPE_API_KEY:
        print("  ⚠ 没有设置 DASHSCOPE_API_KEY：语音识别不可用，只能用 --text 测试\n")
    web.run_app(make_app(), host=config.HOST, port=config.PORT, print=None)


if __name__ == "__main__":
    main()
