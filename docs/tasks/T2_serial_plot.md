# 任务 T2：tools/plot.py —— 电脑端串口实时曲线 + 存 CSV

你是施工者。设计者已定方案，你负责写代码、测试，**只汇报事实**。
开工前读：`AGENTS.md`、`docs/PROGRESS.md`、`firmware/imu_test/imu_test.ino`（看它的串口输出格式）。

## 为什么做这个

已决定：现阶段不用手机 phyphox，显示和记录交给电脑（方案 A）。ESP32 只管测量、往串口打数，
电脑负责画曲线、存数据，课堂上直接投屏。以后测力、测电流、测温度都复用这个脚本，所以它
**不能写死成只认 MPU6050**，要按"表头 + 数字行"的通用格式工作。存下来的 CSV 之后用来做拟合分析。

## 环境（固定约定）

- 从项目根目录运行以下命令
- Python：`.venv/bin/python`（3.9，macOS 系统自带那份）。现有 pyserial、numpy，**没有 matplotlib**
- 装包：`.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple matplotlib`
  （不要用 `.venv/bin/pip`，文件夹改过名，那个脚本路径坏了）。装完把 matplotlib 加进 `requirements.txt`
- 串口：`/dev/cu.usbmodem101`，115200。板子上现在跑的是 `imu_test`，MPU6050 **还没接**，所以串口只会周期性输出 "nothing found" 之类的文字
- 不要改 `firmware/`、`server/`、`simulator/`、`backup/` 下的任何文件

## 串口数据格式约定（脚本按这个解析）

- 一行用 Tab 或逗号分隔
- **数据行**：每一列都能转成浮点数
- **表头行**：不是数据行，且下一条数据行的列数和它相同 → 作为列名（例：imu_test 的
  `ax(g)\tay(g)\taz(g)\t|a|(g)\tgx\tgy\tgz (deg/s)`）
- 其他行（启动信息、"read failed" 等）：原样打印到终端，不画图、不存
- 没收到表头就来数据：列名用 `c1, c2, ...`
- 时间轴：如果第一列名以 `t` 开头（如 `t(s)`），用它作 x 轴；否则用电脑收到该行的时间（从开始记录算起，秒）
- 列数中途变了（比如固件重启换了格式）：开一个新的 CSV 文件，图也重建

## 要做的

新建 `tools/plot.py`，命令行用法：

```
.venv/bin/python tools/plot.py                     # 默认 /dev/cu.usbmodem101，开窗口实时画
.venv/bin/python tools/plot.py --port /dev/xxx
.venv/bin/python tools/plot.py --cols "|a|(g)"     # 只画指定列（逗号分隔，按列名），默认画全部
.venv/bin/python tools/plot.py --window 10         # 图上显示最近 10 秒，默认 10
.venv/bin/python tools/plot.py --fake              # 不接板子，内置假数据源（自测用）
.venv/bin/python tools/plot.py --seconds 5 --no-gui --png out.png   # 跑 5 秒后退出，不开窗口，存一张图
```

功能要求：
1. 打开串口时**不要**复位板子（打开后 DTR/RTS 保持不动）。加 `--reset` 参数时才拉一下 RTS 复位
2. 每次运行都把数据存成 `data/YYYYMMDD-HHMMSS.csv`（第一列是电脑时间 `host_t(s)`，然后是各列），每行写完立刻 flush，Ctrl+C 或关窗口时安全收尾，终端打印 CSV 路径和行数
3. 实时图：每列一条线，或每列一个子图（你选一种，汇报里说明）；刷新 ≥10 次/秒；50 Hz 数据不卡
4. 窗口里或终端显示当前最新值（课堂上要能看到读数，不只是曲线）
5. 串口断开（拔线）时不崩溃：打印提示，每秒尝试重连
6. `--fake`：生成和 imu_test 格式一样的数据（带表头），50 Hz，比如 az=1+0.2·sin(2π·1·t)，中间夹几行非数据文字，用来测试解析
7. 读串口用单独线程，画图在主线程（macOS 上 matplotlib 窗口必须在主线程）
8. 代码简短，只依赖 pyserial、numpy、matplotlib

## 验收标准（每条都要给出原始输出作为证据）

1. `.venv/bin/python -m pip install ...` 的最后几行输出
2. `.venv/bin/python tools/plot.py --fake --seconds 5 --no-gui --png "${TMPDIR:-/tmp}/fake.png"`：
   贴终端输出；贴生成 CSV 的前 5 行和总行数（50 Hz × 5 秒，应在 250 左右）；确认 PNG 生成了（贴文件大小）
3. 接真板：`.venv/bin/python tools/plot.py --seconds 8 --no-gui --reset`：贴终端输出。现在没接 MPU，预期看到 imu_test 的启动文字和"nothing found"之类被原样打印，CSV 为 0 行，程序正常退出不报错
4. 窗口模式（不加 `--no-gui`）**你看不到画面**，在汇报里写明"未验证，需用户看窗口"

## 汇报格式

- 新增/修改的文件列表
- 上面各条的原始输出
- 做过的取舍（子图还是同图、刷新方式等）
- 没验证的事项
- 不要写"应该可以""理论上没问题"
