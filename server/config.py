from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


HOST = _get("HOST", "0.0.0.0")
PORT = int(_get("PORT", "8000"))
# Address the device should use to reach this server. Empty = auto-detect LAN IP.
PUBLIC_HOST = _get("PUBLIC_HOST")
# If set, devices must send "Authorization: Bearer <SERVER_TOKEN>".
SERVER_TOKEN = _get("SERVER_TOKEN")

DASHSCOPE_API_KEY = _get("DASHSCOPE_API_KEY")

ASR_PROVIDER = _get("ASR_PROVIDER", "dashscope")
ASR_MODEL = _get("ASR_MODEL", "paraformer-realtime-v2")

LLM_PROVIDER = _get("LLM_PROVIDER", "openai")  # "openai" (any compatible API) or "echo"
LLM_BASE_URL = _get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_API_KEY = _get("LLM_API_KEY") or DASHSCOPE_API_KEY
LLM_MODEL = _get("LLM_MODEL", "qwen-plus")
HISTORY_MESSAGES = int(_get("HISTORY_MESSAGES", "20"))

# "edge" (free) or "dashscope" (CosyVoice). Empty = dashscope if a key is set, else edge.
TTS_PROVIDER = _get("TTS_PROVIDER")
TTS_VOICE = _get("TTS_VOICE", "zh-CN-XiaoxiaoNeural")  # edge voice
COSYVOICE_MODEL = _get("COSYVOICE_MODEL", "cosyvoice-v2")
COSYVOICE_VOICE = _get("COSYVOICE_VOICE", "longxiaochun_v2")
TTS_SAMPLE_RATE = 24000

SYSTEM_PROMPT = _get(
    "SYSTEM_PROMPT",
    "你是小智，一个住在 ESP32 小设备里的语音助手。"
    "你的回答会被转成语音播放，所以要口语化、简短（一般不超过三句话），"
    "不要使用 Markdown、列表、表情符号或代码。",
)
