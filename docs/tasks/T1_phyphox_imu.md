# 任务 T1：firmware/phyphox_imu —— 打通 ESP32-S3 → BLE → 手机 phyphox

你是施工者。设计者已定方案，你负责写代码、编译、烧录、读串口，**只汇报事实**。
开工前读：`AGENTS.md`、`docs/PROGRESS.md`、`firmware/imu_test/imu_test.ino`。

## 为什么做这个

手机自己就有加速度计，所以这个 sketch 本身不是成品。它的目的是**验证管道**：
phyphox BLE 库在 ESP32-S3 上只做过编译测试、没上板跑过。先用手头的板子把
"ESP32 → BLE → phyphox 画曲线"跑通，以后测力计（HX711）、电流（INA226）直接复用这套骨架。

## 环境（固定约定）

- 从项目根目录运行以下命令
- arduino-cli：`tools/acli`（已装 esp32 core 4.0.0、phyphox BLE 2.0.0，库在 `tools/arduino-user/libraries/phyphox_BLE`）
- FQBN：`esp32:esp32:esp32s3:CDCOnBoot=cdc,USBMode=hwcdc,FlashSize=8M,PSRAM=opi`
- 串口：`/dev/cu.usbmodem101`
- Python：`.venv/bin/python`（自带 pyserial、esptool）。装包必须加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- 读串口：用 pyserial 打开端口，拉一下 RTS 让板子复位，然后读 8 秒左右
- **禁止**：改 `backup/` 下任何文件；接线建议里用 GPIO33–37（被 PSRAM 占用）

## 硬件

- ESP32-S3（N8R8），原生 USB 口
- MPU6050（GY-521）**目前还没接线**。将来接法：VCC→3V3、GND→GND、SDA→GPIO8、SCL→GPIO9
- MPU6050 可能是仿制片，WHO_AM_I 不一定是 0x68，**不要因为 WHO_AM_I 不对就拒绝工作**。
  照搬 `imu_test.ino` 的直接读寄存器写法，不要引入第三方 MPU 库

## 要做的

新建 `firmware/phyphox_imu/phyphox_imu.ino`：

1. 启动时 I2C 扫描 0x68/0x69。
   - 找到 MPU：按 imu_test 的配置（±8g、DLPF ~44Hz）读加速度
   - **找不到 MPU：进入"测试信号"模式**，发一个合成信号（例如 ax=sin(2π·0.5·t)、ay=0、az=1、|a| 照算），
     这样没接传感器也能验证 BLE 管道。每 3 秒重扫一次，接上后自动切到真实数据
2. BLE 设备名 `Gezhi-IMU`。用 phyphox BLE 2.0 的 API（参考库里 `examples/CreateExperiment`、`multigraph`），
   在固件里定义实验（手机连上后自动出界面，不需要手动导入）：
   - 每帧发送：t(s)、ax、ay、az、|a|（单位 g）
   - 图 1：|a| 随 t；图 2：ax、ay、az 随 t（如果库不支持一图多线，就拆成多个图，在汇报里说明）
   - 实验标题 "格致 · 加速度"，分类 "格致 Gezhi"
3. 采样/发送频率 50 Hz（用 millis 节拍，不要用 delay 堵塞）
4. 串口同时打印：启动信息、当前模式（MPU / 测试信号）、BLE 名称；之后每秒打印一行摘要（帧数、最新 |a|），不要每帧都打
5. 不要动 RGB 灯（引脚还没查清，那是另一个任务）

代码风格参考 imu_test：短、注释少、用英文注释。

## 验收标准（每条都要给出原始输出作为证据）

1. `tools/acli compile --fqbn <FQBN> firmware/phyphox_imu` 通过，贴出最后几行（含 Flash/RAM 占用）
2. 烧录成功：`tools/acli upload -p /dev/cu.usbmodem101 --fqbn <FQBN> firmware/phyphox_imu`，贴出输出
3. 串口读 8 秒，贴原文。应看到：I2C 扫描结果（此时应为找不到）、"测试信号"模式、BLE 名 `Gezhi-IMU`、每秒摘要行
4. 手机端 phyphox 能否连上**你验证不了**，在汇报里明确写"未验证，需用户用手机测"

## 汇报格式

- 新增/修改的文件列表
- 上面 3 条命令的原始输出
- 编译警告（如有）
- 没验证的事项、你做过的取舍、遇到的库 API 问题
- 不要写"应该可以""理论上没问题"
