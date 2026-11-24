# 任务 T4：在蓝色 ESP32 上跑通 phyphox 蓝牙（firmware/phyphox_imu）

你是施工者。设计者已定方案，你负责排查、修改、上板验证，**只汇报事实**。
开工前读：`AGENTS.md`、`docs/PROGRESS.md`、`docs/tasks/T1_phyphox_imu.md`（原始需求）、
`firmware/phyphox_imu/phyphox_imu.ino`、`firmware/libraries/GezhiOta/`、`tools/flash.py`。

## 为什么做这个

方向改成了"便携 + 便宜"：不带电脑时，用手机 phyphox 通过蓝牙看曲线。先在手头的蓝板上验证这条路，
**通了用户才会买便携主机**（候选 M5StickC Plus2 等）。所以这一步要回答的是：
ESP32 → BLE → phyphox 到底能不能稳定工作，每秒能发多少帧。

## 现状（设计者已做的，2026-11-24）

- `phyphox_imu.ino` 已改成按芯片选引脚（S3 用 8/9，普通 ESP32 用 21/22），并接入了 GezhiOta（`GezhiOta::begin` 和 `GezhiOta::poll`）
- 编译：`tools/acli compile --fqbn esp32:esp32:esp32 --libraries firmware/libraries firmware/phyphox_imu`
  通过，**但程序空间已用 95%**（1251497 / 1310720 字节）。core 4.0.0 的 BLE 库很大
- 已用 `tools/flash.py firmware/phyphox_imu` 经串口 OTA 烧入，成功（耗时 120 秒）
- **问题**：开机串口输出停在下面这里，之后既没有 `BLE: Gezhi-IMU (started)`，也没有每秒摘要行：
  ```
  === Gezhi IMU / phyphox BLE ===
  SDA=21 SCL=22
  I2C scan: 0x68 / 0x69
    Found 0x68, WHO_AM_I=0x68
  Mode: MPU
  ```
  也就是说卡在、或者崩在 `startBle()` 里。原因未查
- 另外观察到：用 pyserial 打开端口时，有一次板子出现了 `rst:0x1 (POWERON_RESET)`，原因不明（之前的测试里 DTR/RTS 是复位不了它的）。可能和供电或 BLE 启动时的电流尖峰有关，请留意

## 硬件和环境

- 蓝板：ESP32-D0WD-V3，4MB Flash，CP2102，`/dev/cu.usbserial-0001`，FQBN `esp32:esp32:esp32`
- MPU6050 已接好：SDA=21、SCL=22，地址 0x68
- **烧录只用 `tools/flash.py`（串口 OTA）**。蓝板的自动下载电路坏了，`--manual` 需要用户插 IO0 线，非必要不要用
- **任何烧进去的固件都必须带 GezhiOta**，否则板子就失去无线升级能力（flash.py 会检查标记）。如果新固件一开机就崩溃，OTA 也救不回来，只能让用户插 IO0 线手动烧。所以：**改动 BLE 初始化之前，先确认 `GezhiOta::begin` 和 `poll` 在 BLE 初始化之前就能工作**（比如在 setup 里先等 3 秒、期间一直调 poll，再启动 BLE），给自己留一条退路
- 串口同一时间只能被一个程序占用。用完要关掉
- Python：`.venv/bin/python`。phyphox BLE 库在 `tools/arduino-user/libraries/phyphox_BLE`（2.0.0，core 4.x 走 `Esp32Ble4Transport`）

## 要做的

1. 查清 `startBle()` 卡在哪里或者为什么崩溃。可以用分段打印，或者打开 core debug 日志（`--build-property` 或 FQBN 选项 `DebugLevel=verbose`）、看崩溃回溯（backtrace）。先读串口，看有没有 Guru Meditation 或者反复重启
2. 修好，让串口出现 `BLE: Gezhi-IMU (started)` 和每秒摘要行（`mode=MPU frames=50 ...`）
3. 程序空间 95% 太紧，后面还要加传感器。调查并汇报几种办法的代价，**先汇报，不要自己改分区表**：
   - 换分区方案，例如 `PartitionScheme=min_spiffs`（两个 1.9MB 的 OTA 区）。**改分区表必须手动烧录**，要用户插 IO0 线，所以先问设计者
   - 编译优化选项，去掉没用的库
   - 有没有更小的 BLE 栈可用（比如 NimBLE），phyphox 库支不支持
4. 不要改 `tools/plot.py`、`backup/`、`server/`、`simulator/`

## 验收标准（每条都要贴原始输出）

1. 编译输出的最后两行（Flash / RAM 占用）
2. flash.py 上传成功的输出
3. 开机后串口读 10 秒的原文：要有 `BLE: Gezhi-IMU (started)`，以及至少 5 行每秒摘要，帧数在 50 左右
4. 再用 flash.py 升级一次（比如改个版本号），证明带 BLE 的固件仍然能无线升级
5. 手机端 phyphox 能不能连上、能不能看到曲线，**你验证不了**。写明"需用户用手机测"，并给用户写好操作步骤：phyphox 首页 → "+" → 添加蓝牙实验 → 选 `Gezhi-IMU`
6. 第 3 项"程序空间"的调查结论

## 汇报格式

- 修改的文件
- 根本原因（找到的证据，比如日志、回溯）
- 上面各条的原始输出
- 没验证的事项
- 不要写"应该可以""理论上没问题"
