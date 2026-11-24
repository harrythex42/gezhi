# 任务 T5：把项目放进 git，推到 GitHub 私有仓库

你是施工者。设计者已定方案，你负责执行，**只汇报事实**。
开工前读：`AGENTS.md`、`docs/PROGRESS.md`。

## 为什么做这个

1. 版本历史：改坏了能退回去，能看清每次改了什么（T4 改了第三方库，现在只能靠文字记录）
2. 备份
3. 以后参加比赛、给别人看，发一个链接就行

## 现状

- 从项目根目录执行；任务开始时还不是 git 仓库
- 本机有 `git`（2.50.1）。用户说他已经有 GitHub 账号和命令行工具，但设计者的 shell 里 `which gh` 找不到。
  先查 `/opt/homebrew/bin/gh`、`/usr/local/bin/gh`；找不到就问用户怎么登录的（gh、SSH key 还是 GitHub Desktop），**不要自己装软件**
- 现有 `.gitignore`：`.venv/`、`.env`、`__pycache__/`、`*.wav`
- 各目录大小：`tools/` 9.3GB，`.venv/` 206MB，`firmware/` 约 101MB（大部分是编译产物，要先查清楚是哪些），`backup/` 12MB，`data/` 556KB

## 规则：哪些必须排除

| 路径 | 处理 | 原因 |
|---|---|---|
| `backup/` | **排除** | 实验室板子的原厂固件完整拷贝，可能含 WiFi 凭据，而且不是我们写的 |
| `.env` | **排除**（已经在里面） | 将来放 API Key |
| `tools/` | 排除，但**保留 `tools/acli`、`tools/plot.py`、`tools/flash.py`**（这三个是我们写的） | arduino-cli、core、库都能重新下载 |
| `.venv/` | 排除 | 用 requirements.txt 重装 |
| 编译产物 | 排除（`build/`、`*.bin`、`*.elf`、`*.map` 等，具体看 firmware/ 里实际有什么） | |
| `data/*.csv` | 排除，但保留单摆那份 `data/20261124-182841.csv`（PDF 里用到了） | |
| `firmware/libraries/GezhiOta/` | **要包含** | 我们自己写的 |
| `docs/`（包括 `docs/intro/`、`docs/tasks/`） | 要包含 | |

## 要做的

1. **保存第三方库补丁**：T4 改过 `tools/arduino-user/libraries/phyphox_BLE/src/transport/Esp32Ble4Transport.cpp`（加了 `[phyphoxBLE]` 调试打印）。tools/ 会被排除，这些改动不能丢：
   - 原版从 phyphox BLE 2.0.0 拿，比如用 `tools/acli lib download "phyphox BLE@2.0.0"` 或解压缓存的 zip。不要覆盖正在用的那份
   - 用 `diff -u` 生成 `patches/phyphox_BLE-2.0.0-esp32ble4-debug.patch`
   - 在 `patches/README.md` 里写两三行：补丁改了什么、为什么改、怎么打上
2. 更新 `.gitignore`，按上面的规则
3. 写一个 `tools/setup.md`（简短）：新电脑上怎么装回 arduino-cli 1.6.0、esp32 core 4.0.0、phyphox BLE 2.0.0，怎么打补丁，怎么 `pip install -r requirements.txt`（走清华镜像）
4. `git init`，默认分支 `main`
5. **提交前检查**，每一项都贴输出：
   - `git status --porcelain | wc -l` 和 `git add -n .` 的文件清单（如果很长就贴前 80 行和总数）
   - 将要提交的总大小，以及最大的 10 个文件。单个文件超过 5MB 就停下来问设计者
   - 搜敏感词：`git grep -nIiE "api[_-]?key|secret|password|passwd|token|sk-[a-z0-9]{10,}" -- . ':!docs/tasks'`，有命中就逐条说明是不是真的密钥
   - 确认 `backup/`、`.env`、`tools/arduino-cli`、`tools/arduino-data` 不在清单里
6. 第一次提交，提交信息：`Initial commit: Gezhi firmware, tools, docs`
7. GitHub：
   - **先问用户仓库名**（建议 `gezhi`），默认**私有**。用户确认之前不要创建仓库
   - 用户确认后创建私有仓库并 push
   - 贴 `git remote -v` 和 push 的输出，以及仓库网址
8. 在 `AGENTS.md` 的"固定约定"里加一条：项目用 git 管理，每完成一个任务就提交一次，提交前先跑上面的敏感词检查

## 不要做

- 不要推送到公开仓库
- 不要 `git add -f` 强行加入被排除的文件
- 不要改动固件、tools 下的脚本逻辑、`backup/`
- 不要自己安装 gh 或别的软件，缺什么问用户

## 汇报格式

- 新增/修改的文件
- 上面第 5、7 步的原始输出
- 仓库网址
- 没做完、或者需要用户处理的事
