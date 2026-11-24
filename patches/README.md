# 第三方库补丁

BLE 2.0.0 的补丁为 ESP32 core 4.x 增加分段启动日志，并检查广播启动与传输任务创建是否成功，用于定位 T4 的蓝牙启动卡点。
安装原版后，在项目根目录运行：
`patch -p1 -d tools/arduino-user/libraries/phyphox_BLE < patches/phyphox_BLE-2.0.0-esp32ble4-debug.patch`
