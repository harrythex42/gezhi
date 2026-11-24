# 自己写的小智服务器

ESP32 刷开源的[小智固件](https://github.com/78/xiaozhi-esp32)，**服务器完全自己写**。板子只负责听和说，"大脑"跑在这台 Mac 上。

```
ESP32 ──Opus 音频──▶ 语音识别 ──▶ 大模型(+工具) ──按句切──▶ 语音合成 ──Opus──▶ ESP32
        ◀──────────────── WebSocket（小智协议）────────────────────────────▶
```

## 目录

| 文件 | 作用 |
|---|---|
| `server/main.py` | 入口：OTA 接口 `/xiaozhi/ota/` 和 WebSocket `/xiaozhi/v1/` |
| `server/session.py` | **核心**：一台设备一个会话，处理 hello、listen、abort、mcp，以及回复流水线 |
| `server/asr.py` | 流式语音识别（百炼 paraformer），它的"一句话结束"同时用来判断你说完了 |
| `server/llm.py` | 大模型流式输出和工具调用循环（任意 OpenAI 兼容接口） |
| `server/tts.py` | 语音合成：免费的 edge-tts，或百炼 CosyVoice |
| `server/tools.py` | 大模型能用的工具：服务器上的函数，加上设备通过 MCP 上报的能力 |
| `server/audio.py` | Opus 和 MP3 的编解码（PyAV） |
| `simulator/fake_device.py` | **用 Mac 假装成 ESP32**，板子没到也能调试 |

## 跑起来

```bash
# 在项目根目录执行
cp .env.example .env              # 填上 DASHSCOPE_API_KEY
.venv/bin/python -m server.main   # 启动服务器，会打印 OTA 地址
```

另开一个终端，用模拟器跟它说话：

```bash
.venv/bin/python -m simulator.fake_device            # 按回车开始说，再按回车结束
.venv/bin/python -m simulator.fake_device --auto     # 免提，说完停顿一下就行
.venv/bin/python -m simulator.fake_device --text "现在几点了"   # 不用麦克风
```

第一次用麦克风时，macOS 会请求授权，请允许终端使用麦克风。

没有 Key 也能测链路：`LLM_PROVIDER=echo .venv/bin/python -m server.main`，再配合 `--text` 使用。

> 依赖已经装在 `.venv` 里。重装时要用国内镜像：
> `.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`

## 接真板子

1. 用[小智的网页烧录工具](https://github.com/78/xiaozhi-esp32)刷固件，板型选对，比如正点原子那款就选对应的"正点原子"型号。
2. 板子开机后会开一个热点，比如 `Xiaozhi-XXXX`。手机连上它，在弹出的配网页里填 Wi‑Fi，**展开高级选项，在 "Custom OTA URL" 里填服务器启动时打印的 OTA 地址**，例如 `http://10.165.233.127:8000/xiaozhi/ota/`。
3. 板子和 Mac 必须在**同一个 Wi‑Fi** 下。如果开了 Clash 或 Surge 这类代理，确认打印出来的不是 `198.18.x.x`；是的话，就在 `.env` 里用 `PUBLIC_HOST` 指定 Mac 的局域网 IP。
4. 第一次接入时，macOS 防火墙可能会询问是否允许 Python 接受连接，选允许。

## 协议速查（服务器视角）

| 方向 | 消息 | 含义 |
|---|---|---|
| ← | `hello` | 设备上线，告知音频参数（上行 Opus，16kHz，60ms 一帧） |
| → | `hello` | 握手确认，下行用 24kHz |
| ← | `listen start/stop/detect` | 开始收音、停止收音、检测到唤醒词 |
| ← | 二进制帧 | 麦克风 Opus 音频 |
| → | `stt` | 识别出的文字，显示在屏幕上 |
| → | `tts start / sentence_start / stop` | 开始说话、当前这句字幕、说完了 |
| → | 二进制帧 | 合成的 Opus 音频，按实时节奏发送，方便打断 |
| ← | `abort` | 用户打断 |
| ↔ | `mcp` | JSON-RPC：`initialize` → `tools/list` → `tools/call` |

## 接下来

- [x] 第 2 步：自己写服务器（就是这个仓库）
- [ ] 第 3 步：压延迟。看日志里的 `latency:` 行，目标是 1 秒左右。可以从这几处入手：换 CosyVoice、第一句更早切开、大模型换更快的版本
- [ ] 第 4 步：在 `server/tools.py` 里加你自己的工具，比如 Garmin 睡眠和心率、Obsidian 笔记、天气
- [ ] 第 5 步：自己改固件（ESP-IDF）：唤醒词、打断、自定义 MCP 工具，比如控制 GPIO
