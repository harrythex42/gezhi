# 格致 Gezhi · ESP32 物理测量 + 自建小智语音服务器

中文交流，回答简洁、少术语。先回答"为什么"，再谈"怎么做"。
**当前进度、硬件状态、踩过的坑都在 `docs/PROGRESS.md`，开始工作前先读它。**

## 两条线

1. **格致（当前主线）**：ESP32 + 传感器，做手机测不了的物理量（力、电流、温度、电压，加上光电门计时），用于课堂演示和随身测量。现阶段 ESP32 通过串口发数据，电脑端 `tools/plot.py` 画曲线、存 CSV（phyphox 方案已搁置，见 PROGRESS）。代码在 `firmware/`。
2. **小智语音服务器**：ESP32 刷开源小智固件，服务器用 Python 自己写。代码在 `server/`、`simulator/`，说明见 `README.md`。

## 协作方式：Claude 做设计，GPT 做施工

- **设计者（Claude，主会话）**：和用户沟通、定方案、挑硬件、判断坑（电压、量程、采样率）、拆分任务、验收结果。
- **施工者（GPT，子代理）**：执行边界清楚的任务，比如写某个 sketch、编译、烧录、跑测试。
- 派活时，任务说明要写全：背景、相关文件路径、接线和引脚、验收标准（例如"编译通过并烧录；串口出现 0x68"）。子代理看不到这段对话。
- 施工者只汇报事实：改了哪些文件、命令输出、哪些没验证。不准声称"应该可以"。
- 设计者亲自验收：自己跑一遍编译或读一次串口，再告诉用户结果。
- 子代理的模型 ID 由用户指定，不要猜。

## 固定约定

- 项目用 Git 管理，每完成一个任务就提交一次。提交前检查已暂存的敏感词：`git grep --cached -nIiE 'api[_-]?key|secret|password|passwd|token|sk-[a-z0-9]{10,}' -- . ':!docs/tasks'`，确认没有真实凭据再提交。
- Python：`.venv/bin/python`（3.9）。装包用 `.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...`（文件夹从 ESP32 改名后，`.venv/bin/pip` 等脚本里的旧路径失效了，一律用 `python -m` 的写法）
- Arduino：`tools/acli`（arduino-cli 加项目内数据目录）。板子 FQBN：
  `esp32:esp32:esp32s3:CDCOnBoot=cdc,USBMode=hwcdc,FlashSize=8M,PSRAM=opi`
- 串口：`/dev/cu.usbmodem101`（S3）
- **当前主力板是实验室蓝色普通 ESP32**：FQBN `esp32:esp32:esp32`，串口 `/dev/cu.usbserial-0001`，I2C 用 SDA=21、SCL=22。它不能自动进下载模式，烧录要用户手动把 IO0 接到 GND 再按 RST，流程见 PROGRESS。烧录前先问用户
- esptool：`.venv/bin/python -m esptool ...`。这一版的命令用下划线，比如 `flash_id`、`read_flash`
- 不帮用户下单付款；涉及钱和真实设备的操作，先问用户
