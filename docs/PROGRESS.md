# 进度与交接（更新于 2026-11-24）

## 硬件现状

**实验室借来的 ESP32-S3（已连电脑，正在用）**
- ESP32-S3 (QFN56) rev v0.2，Flash 8MB，封装内带 8MB PSRAM
- 插在原生 USB 口（USB-Serial/JTAG），串口 `/dev/cu.usbmodem101`，不用装驱动
- **GPIO33 到 37 被内置 PSRAM 占用，不要接线**
- 原固件已完整备份：`backup/lab_s3_original_8MB.bin`。还原：`.venv/bin/python -m esptool --port /dev/cu.usbmodem101 write_flash 0 backup/lab_s3_original_8MB.bin`
- 现在烧的是 `firmware/imu_test`，编译、烧录、串口输出都正常
- ⚠️ 用户**没看到**开机时 RGB 灯闪三下。可能是灯接在 GPIO38 而不是 48，也可能这块板没有 RGB 灯。**待查**
- 实验室还有一块 MPU6050（GY-521），**还没接线**。接法：VCC→3V3、GND→GND、SDA→GPIO8、SCL→GPIO9

**蓝色 ESP32（D1 mini32 样式，ESP32-WROOM-32 普通版，非 S3）——当前主力板，实验室已送给用户**
- 实验室建议换这块：排针已焊好。上面那块 S3 很小，焊着别人的电池线，接传感器不方便
- USB 芯片 CP2102，串口 `/dev/cu.usbserial-0001`，macOS 自带驱动
- 3V3 实测约 3.3V，红色电源灯。按 RST 能正常启动（`ets Jul 29 2019 ... POWERON_RESET`），里面的原程序不往串口输出
- ⚠️ **自动下载电路不工作**：DTR/RTS 怎么切都不能复位它，esptool 连不上。烧录要手动：杜邦线把 IO0 接到 GND，按 RST，烧完拔线再按 RST
- 芯片 ESP32-D0WD-V3 rev v3.1，Flash 4MB。FQBN `esp32:esp32:esp32`
- I2C 用 SDA=21、SCL=22
- 原固件已备份并校验通过（verify_flash OK）：`backup/lab_blue_esp32_original_4MB.bin`
- **当前烧的是 T4 的旧版 `phyphox_imu`**，停在 `Mode: MPU`，OTA 探测无回复。已编译带 OTA 启动窗口和 BLE 分段日志的恢复版，待用户能接 IO0 后手动恢复一次。之前的 `imu_test v4` 已通过串口 OTA 验收
- 手动烧录流程：IO0 接 GND → 按 RST → 先 `tools/acli compile --fqbn esp32:esp32:esp32 --output-dir <目录> <sketch>`，再 `esptool --chip esp32 --before no_reset --after no_reset --baud 460800 write_flash 0x1000 bootloader 0x8000 partitions 0xe000 boot_app0 0x10000 app` → 拔线 → 按 RST
- 串口只能被一个程序占用。后台监听没关时 plot.py 会报 "returned no data"
- CP2102 偶尔会卡住，打开端口报 `termios.error 22`，拔插一次就好

**MPU6050（GY-521）**：排针没焊，用户自己练习焊接（教程已给）。焊完先用万用表确认 VCC 和 GND 之间不导通，再通电

**已购硬件**
- 按用户 11/24 发来的订单截图核对过：大富瑞 INA226 ×1（¥15.38）、大富瑞槽型光耦测速模块 ×2、登仕唐 HX711 + 5kg 圆形秤架（已组装，厨房秤那种圆盘，只能测压力和重量）×1（¥33.20）、登仕唐 DS18B20 1 米防水探头 ×2、登仕唐 BH1750（GY-302）×1（¥5.80）
- **没有买**：ZAVE ESP32-S3 开发板、第二块 MPU6050（之前记成"已买"是错的）。MPU6050 用的是实验室那块
- 正点原子 ESP32-S3 BOX 开发板（触屏版，¥122.90，11/23 下单），给小智用
- 万用表、电烙铁、面包板、杜邦线、C 对 C 线：实验室都有。用户有 3D 打印机，朋友能帮忙焊接
- 便携盒子的主板还没买，候选 XIAO ESP32S3

## 软件现状

- `tools/`：arduino-cli 1.6.0、esp32 core 4.0.0、phyphox BLE 2.0.0（库已装，见 T1）
- `firmware/imu_test/`：闪 RGB 灯 → I2C 扫描 → 直接读 MPU6050 寄存器（±8g、±500°/s、20Hz 串口输出）。故意不用现成库，因为仿制芯片的 WHO_AM_I 不是 0x68，很多库会直接拒绝工作
- `server/` 和 `simulator/`：小智协议服务器。不用 Key 的 echo 测试模式验证过：OTA、hello、MCP 工具发现、工具调用、按句流式合成、打断。**真实的百炼 ASR 和 CosyVoice 还没测**（用户还没申请 `DASHSCOPE_API_KEY`）
- 如果移动项目目录，请检查本机 `tools/arduino-data/arduino-cli.yaml` 是否仍引用过时的绝对路径
- 任务单放在 `docs/tasks/`
  - T1 `firmware/phyphox_imu`：GPT 已写好，设计者复编译通过、读过代码。**按决定暂不烧录，搁置备用**
  - T4 在蓝板上跑通 phyphox 蓝牙（`docs/tasks/T4_phyphox_blue.md`）：真板读到 `POWERON_RESET`、地址 `0x68`、`Mode: MPU`；其后无输出，未见崩溃回溯，连续 10 次无写入 OTA 探测无回复。旧程序在 `startBle()` 返回后才处理 OTA。离线编译通过的恢复版先处理 OTA、给 BLE 留 3.5 秒延迟，并在独立任务中分段记录启动；蓝板编译为 1,252,441 / 1,310,720 B（95%）。蓝牙内部卡点、两轮 OTA 和手机端仍未验证；今日未写入真板，不改分区。设计者复核：恢复版思路正确（loop 先跑 OTA，3.5 秒后再在独立任务里启动 BLE，loop 只在 BLE Ready 后才调 PhyphoxBLE），代码已读过。⚠️ GPT 在第三方库 `tools/arduino-user/libraries/phyphox_BLE/src/transport/Esp32Ble4Transport.cpp` 里加了 `[phyphoxBLE]` 调试打印，库已不是原版，查清后要删掉或另存成补丁。**明天手动烧录时顺便换成 `PartitionScheme=min_spiffs`**（反正都要插 IO0 线，手动烧录会重写分区表；两个 OTA 区各 1.875MB，可以解决 95% 太满的问题；我们不用文件区）。换完之后，flash.py 的默认 FQBN 和 AGENTS.md 都要改成 `esp32:esp32:esp32:PartitionScheme=min_spiffs`，否则 OTA 会按旧分区编译
  - T3 串口自升级（`firmware/libraries/GezhiOta` + `tools/flash.py`）：蓝板手动装入 v2，再经 USB 串口连续升级到 v3、v4（39.7 秒、39.5 秒）。错误 MD5 被真板拒绝，v4 继续扫描；无升级标记的旧固件在电脑端被拒绝。S3 仅编译通过，未烧录。**设计者复验：自己跑了一次 flash.py，升级成功（SW_CPU_RESET 后出现 v4 banner），退出码 0。** 可优化：传输时把波特率切到 921600，耗时能从约 40 秒降到约 5 秒（还没做）
  - T2 `tools/plot.py`：电脑端串口实时曲线 + 存 CSV。GPT 已完成，设计者复测：假数据 5 秒 246 行、真板 8 秒正常退出（无 MPU，0 行）。设计者改了一处：CSV 固定存到项目根目录 `data/`，不随当前目录变。**实时窗口待用户看**：`.venv/bin/python tools/plot.py --fake`
- 读串口的小办法：用 pyserial（esptool 依赖里自带），先拉一下 RTS 让板子复位，再读几秒

## 下一步（按顺序）

1. ✅ MPU6050 已焊好（别人帮焊的），接在蓝板上（VCC→3V3、GND→GND、SCL→22、SDA→21）。2026-11-24 实测：地址 0x68，WHO_AM_I=0x68（像正品），20Hz；静止时 |a|=0.963g（偏低约 4%，以后可以把六个面各朝下放一次来校准），噪声约 3mg，陀螺零偏约 1~2°/s。待用户看实时窗口
2. 查清 RGB 灯的引脚（38 还是 48）
3. T2：`tools/plot.py` 电脑端画曲线、存 CSV（所有传感器共用）
4. 京东的货到了以后：测力计 `firmware/force`，读 HX711，用砝码标定，串口输出接 plot.py
5. 以后要随身用：给 ESP32 加小屏显示读数（方案 B，还没选型）
6. 小智板到了以后：用网页烧录小智固件（必须用 Chrome 或 Edge，Firefox 不支持网页串口），配网时在 Custom OTA URL 填服务器打印的地址；用户申请百炼 Key，测真实语音

## 已定的设计决策

- 手机已经能测的（加速度、磁场、光强）不重复做，除非手机不方便，比如要绑在小车上、要测碰撞时的高 g、要多点同时测
- ESP32 只负责测量，通过串口发"表头 + 数字行"（Tab 或逗号分隔）
- **以后所有固件的第一列必须是板子自己的时间 `t(s)`**（用 micros() 算）。原因：电脑收到数据的时刻不准，实测 macOS 会把后台进程的定时器拖到 20 到 120ms（要求 20ms），数据会一阵一阵地到。plot.py 看到第一列名以 t 开头，就会自动用它当横轴
- 显示和记录：**现阶段用电脑**（方案 A，`tools/plot.py`），课堂投屏。理由：用户不想要"ESP32 + 手机"两台设备。随身用以后加小屏（方案 B）。phyphox（方案 C）代码留着，不删
- 电脑端串口工具默认**不复位**板子，免得打断正在进行的测量
- **方向调整（2026-11-24）：做"便携 + 便宜"。** 理由：朗威 DISLab 是一大箱，不便携；PASCO 和 Vernier 的无线传感器虽然小巧，但单个约 $119–124。便携就意味着不能依赖电脑：要内置电池、手机（phyphox 蓝牙）或小屏显示、免焊接。T1 的 phyphox 程序重新变成重点。电脑 + plot.py 保留，用于课堂投屏和调试
- 便携主机候选（价格是网上查到的，国内价没核实）：M5StickC Plus2（经典 ESP32，屏 1.14 寸，内置电池，有 IMU 和 Grove 口，约 $20–30）；M5StickS3（ESP32-S3 新款，屏 1.14 寸，电池 250mAh）；XIAO ESP32S3（21×17.8mm，带锂电池充电，约 ¥55，没有屏）；LILYGO T-Display-S3（1.9 寸屏，有电池接口和 Qwiic 口，约 $13–14，电池和外壳要另配）；AtomS3R（24mm 见方，屏只有 0.85 寸）。等用户选
- **便携盒子设计（讨论中，2026-11-24）**：
  - 结构：一个"核心盒"（主板 + 电池 + 充电 + MPU6050 + BH1750，屏幕可选），侧面留统一的外接口，接温度探头、光电门、测力件。理由：温度、电流接线柱、光电门、称重件都必须碰到被测物，放不进盒子里
  - 壳子用 3D 打印（用户有打印机）。内部做卡槽，传感器电路板滑进去卡住；MPU6050 必须拧紧或压紧，否则测到的是零件晃动。盒盖做两版：带屏幕窗口的和平的。BH1750 要开透光窗
  - 打算用 OpenSCAD 参数化建模：设计者定尺寸和结构，GPT 写代码、导出 STL。各模块的实际尺寸要等到货后用尺子量
  - 不买 M5StickC：它自带外壳，和自己做壳的思路重复。主板候选 XIAO ESP32S3，配带保护板的 3.7V 锂电池（300–500mAh）、开关，OLED 可选
  - 顺序：① 在蓝板上跑通 phyphox 蓝牙（T4），不通的话便携方案要重想，**通了再买 XIAO** ② 第一个盒子只做"运动盒子"（XIAO + 电池 + MPU6050），不需要外接口 ③ 再加外接口，接温度和光电门 ④ 最后做测力（外形最复杂；圆形秤只能测压力，测拉力以后可能要配 S 型称重元件）
  - 用户还没确认第一个盒子做"运动盒子"
- AI 用在"实验后分析数据"（拟合、解释误差），不做"小智现在多少牛"这种问答

## 已知的坑

- ESP32 的引脚只能接 3.3V。HX711 也要用 3.3V 供电，不然 DOUT 会输出 5V 信号
- HX711 绿色小板默认每秒采样 10 次，改 RATE 脚接 VCC 才能到 80 次；测碰撞要换 ADS1220 或 NAU7802
- HX711 商品标题里出现过 "ZY-HX710A"，到货后看芯片丝印，确认是不是 HX711
- INA226 的排针是散的要焊；采样电阻 0.1Ω，量程约 0.8A；只测低压直流
- DS18B20 裸探头要接 4.7kΩ 上拉电阻；读一次约 750ms，比较慢
- 实验室 S3 开机时会报 `esp_core_dump_flash: Core dump data check failed`。原因是崩溃记录区里没有有效数据，不影响运行，不用管
- 开发板比较宽，要两块面包板并排插
- 网络：PyPI 要走清华镜像。电脑开着代理（TUN 网段 198.18.x.x），服务器已经改成优先用 en0 的 IP
