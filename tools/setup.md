# 在新电脑恢复工具链

在项目根目录执行。先从 [Arduino CLI v1.6.0 发布页](https://github.com/arduino/arduino-cli/releases/tag/v1.6.0) 下载适合本机的压缩包，将解压得到的 `arduino-cli` 放到 `tools/arduino-cli`，然后：

```sh
chmod +x tools/arduino-cli
ESP32_INDEX=https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
tools/acli core update-index --additional-urls "$ESP32_INDEX"
tools/acli core install esp32:esp32@4.0.0 --additional-urls "$ESP32_INDEX"
tools/acli lib install 'phyphox BLE@2.0.0'
patch -p1 -d tools/arduino-user/libraries/phyphox_BLE < patches/phyphox_BLE-2.0.0-esp32ble4-debug.patch
```

Python 环境与串口工具：

```sh
python3.9 -m venv .venv
.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.venv/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple esptool==4.14.0
```

仅在需要运行语音服务时，参考主 README 配置本机 `.env`；不要提交凭据。
