# 任务 T3：串口自我升级（Serial OTA）—— 烧程序不再插 IO0 线

你是施工者。设计者已定方案，你负责写代码、编译、上板测试，**只汇报事实**。
开工前读：`AGENTS.md`、`docs/PROGRESS.md`（重点看"实验室蓝色 ESP32"一节）、`firmware/imu_test/imu_test.ino`、`tools/plot.py`。

## 为什么做这个

主力板是蓝色普通 ESP32（CP2102 USB 转串口）。它的自动下载电路不工作：DTR/RTS 怎么切都复位不了芯片，
esptool 连不上。现在每次烧录都得让用户手动把 IO0 接到 GND、按 RST，烧完再拔线、再按 RST。

问题出在"让芯片进入下载模式"这一步，那就**绕开它**：让正在运行的程序自己从串口接收新固件，
用 ESP32 的 `Update` 库写进另一个 OTA 分区，校验通过后重启。电脑端一条命令完成，不插线、不按键。
默认分区表本来就有 app0/app1 两个 OTA 分区，不用改分区。

## 环境（固定约定）

- 从项目根目录运行以下命令
- arduino-cli：`tools/acli`，esp32 core 4.0.0
- 蓝板：FQBN `esp32:esp32:esp32`，串口 `/dev/cu.usbserial-0001`，115200。Flash 4MB
- S3 板（备用）：FQBN `esp32:esp32:esp32s3:CDCOnBoot=cdc,USBMode=hwcdc,FlashSize=8M,PSRAM=opi`。只要求能编译通过，不用上板
- Python：`.venv/bin/python`（有 pyserial、esptool）。装包用 `.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...`
- 串口同一时间只能被一个程序打开。测试前确认没有别的进程占着端口（`lsof /dev/cu.usbserial-0001`）
- CP2102 偶尔会卡住，打开时报 `termios.error 22`，这时请用户拔插 USB
- 板子上现在烧的是 `imu_test`（不含升级功能）。原厂固件备份在 `backup/lab_blue_esp32_original_4MB.bin`，**不要改 `backup/`**

## 要做的

### 1. 设备端库：`firmware/libraries/GezhiOta/`

标准 Arduino 库结构（`library.properties` + `src/GezhiOta.h` + `src/GezhiOta.cpp`）。编译时用 `--libraries firmware/libraries` 引入。

API：
```cpp
GezhiOta::begin(115200);  // 代替 Serial.begin：先 Serial.setRxBufferSize(足够大，例如 8192)，再 Serial.begin
GezhiOta::poll();         // 放在 loop() 开头，不阻塞；收到升级命令后才阻塞直到完成或失败
```
- 固件里要嵌入一个标记字符串（例如 `"GZOTA1-CAPABLE"`），用 `volatile`/`__attribute__((used))` 等方式确保链接器不会删掉。电脑端靠它判断新固件是否还带升级功能
- 协议自己定，要求如下：
  - 所有协议回复都以 `GZOTA ` 开头，单独占一行。电脑端要忽略其他行，因为传感器输出可能夹在中间
  - 电脑先发一行命令（含魔术字、固件大小、MD5）→ 设备 `Update.begin(size)` + `Update.setMD5(md5)` → 回复 READY
  - 分块传输，**每块等设备回 ACK 再发下一块**（流量控制）。块大小不能超过接收缓冲区
  - 收完后 `Update.end(true)`：MD5 不对、或镜像不合法（不是 ESP32 app），回复错误、`Update.abort()`，**继续运行旧程序，不重启**
  - 成功则回复 DONE，flush 后 `ESP.restart()`
  - 任一步骤超过 5 秒没收到数据：abort，回复超时错误，继续运行旧程序
- 约定：用了这个库的 sketch 不再自己读 Serial（poll 会吃掉串口输入）。写在头文件注释里
- 普通 ESP32（UART）和 S3（HWCDC 的 Serial）都要能编译。S3 上 `setRxBufferSize` 的写法如有不同，用条件编译处理

### 2. 电脑端：`tools/flash.py`

```
.venv/bin/python tools/flash.py firmware/imu_test             # 编译 + 串口 OTA 上传
.venv/bin/python tools/flash.py firmware/imu_test --manual    # 兜底：提示用户插 IO0 线、按 RST，然后用 esptool 全量烧录
.venv/bin/python tools/flash.py --bin xxx.bin                 # 直接上传现成的 app bin（OTA 方式）
```
- 默认 FQBN `esp32:esp32:esp32`，端口沿用 `tools/plot.py` 的自动探测逻辑（usbserial 优先），都可以用参数覆盖
- 编译：`tools/acli compile --fqbn <FQBN> --libraries firmware/libraries --output-dir <临时目录> <sketch>`
- **上传前检查新 bin 里有没有那个标记字符串，没有就拒绝上传**，并说明原因：上传后会失去无线升级能力，下次只能插线。加 `--force` 才放行
- 打开串口**不要复位板子**（DTR/RTS 保持 False）
- 显示进度和耗时。成功后继续读串口约 5 秒，打印新程序的开机输出
- 失败时打印设备的错误回复，退出码非 0
- `--manual` 模式：烧 bootloader(0x1000)、partitions(0x8000)、boot_app0.bin(0xe000)、app(0x10000)，参数用 `--before no_reset --after no_reset --baud 460800`。
  **必须写 boot_app0**：OTA 之后，otadata 可能指向 app1，只写 0x10000 会出现"烧进去了但还在跑旧程序"。
  boot_app0.bin 在 `tools/arduino-data/packages/esp32/hardware/esp32/4.0.0/` 下面，自己 find 一下

### 3. 把 `firmware/imu_test` 接入

- `Serial.begin(115200)` 换成 `GezhiOta::begin(115200)`，`loop()` 开头加 `GezhiOta::poll()`
- 开机 banner 里加一个版本号常量，比如 `=== IMU test v2 (SDA=21, SCL=22) ===`，用来证明新程序真的跑起来了
- imu_test 现在的 `loop()` 没找到 MPU 时直接 return，确保 poll 在 return 之前调用
- 其他逻辑不改

## 上板测试需要用户配合一次

带升级功能的第一版只能用 `--manual` 烧进去。这一步**你要先停下来，告诉用户**：
"请用杜邦线把 IO0 接到 GND，按一下 RST，好了告诉我"。用户确认后再烧；
烧完请用户拔掉 IO0 线，再按一次 RST。之后的测试全部不需要用户动手。

## 验收标准（每条都要贴原始输出）

1. 两块板的 FQBN 编译 imu_test 都通过（贴最后两行）
2. `--manual` 烧录成功，串口能看到 `v2` 的 banner
3. 把版本号改成 v3，`flash.py firmware/imu_test` 无线升级成功：贴进度、耗时、升级后的 banner（应为 v3）
4. 再改回 v4 升级一次，证明连续升级没问题。这次是从 app1 升回 app0 的方向
5. 反面测试 a：把一个合法 bin 的 MD5 故意传错（可以加一个隐藏的测试参数），设备应拒绝，并继续以旧版本运行（贴设备回复，以及之后仍在输出的旧 banner 或扫描行）
6. 反面测试 b：拿一个不含标记字符串的 bin（例如没接入库之前编译的 imu_test），`flash.py --bin` 应拒绝上传（贴提示）
7. 最后板子上停在最新版 imu_test（带升级功能），端口释放

## 汇报格式

- 新增/修改的文件列表
- 协议简述（几行就够）
- 上面各条的原始输出、上传耗时
- 没验证的事项（例如 S3 只编译未上板）、做过的取舍
- 不要写"应该可以""理论上没问题"
