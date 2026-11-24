"""Compile and upload a Gezhi ESP32 sketch over serial."""

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import serial

from plot import default_port


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FQBN = "esp32:esp32:esp32"
BOOT_APP0 = ROOT / "tools/arduino-data/packages/esp32/hardware/esp32/4.0.0/tools/partitions/boot_app0.bin"
CAPABLE = b"GZOTA1-CAPABLE"
BAUD = 115200
TIMEOUT = 5
PROBE = b"\nGZOTA1 0 00000000000000000000000000000000\n"
PROBE_REPLY = "GZOTA ERR invalid size"


class FlashError(Exception):
    pass


class DeviceError(FlashError):
    pass


def compile_sketch(sketch, fqbn, output):
    subprocess.run(
        [str(ROOT / "tools/acli"), "compile", "--fqbn", fqbn,
         "--libraries", str(ROOT / "firmware/libraries"),
         "--build-path", str(output / "build"), "--output-dir", str(output),
         str(sketch)],
        cwd=ROOT, check=True,
    )
    return output / f"{sketch.name}.ino.bin"


def open_serial(port):
    handle = serial.Serial(baudrate=BAUD, timeout=0.1, write_timeout=TIMEOUT, exclusive=True)
    handle.dtr = False
    handle.rts = False
    handle.port = port
    handle.open()
    return handle


class Replies:
    def __init__(self, handle):
        self.handle = handle
        self.pending = bytearray()

    def line(self, deadline):
        while time.monotonic() < deadline:
            self.pending.extend(self.handle.read_until(size=1024))
            if self.pending.endswith(b"\n"):
                line = self.pending.decode("utf-8", errors="replace").rstrip("\r\n")
                self.pending.clear()
                return line
            if len(self.pending) > 4096:
                self.pending.clear()
        return None

    def expect(self, what, timeout=TIMEOUT):
        deadline = time.monotonic() + timeout
        while (line := self.line(deadline)) is not None:
            if what == "READY" and line == PROBE_REPLY:
                continue  # A delayed reply to one of the harmless probes.
            if line.startswith("GZOTA ERR "):
                raise DeviceError(line)
            if line.startswith("GZOTA "):
                if not line.removeprefix("GZOTA ").startswith(what):
                    raise FlashError(f"Expected {what}; device replied: {line}")
                return line
        raise FlashError(f"Timed out waiting for {what}. If OTA is not installed, use --manual.")

    def synchronize(self):
        # Zero size is rejected before Update.begin(), including by the v2 bootstrap.
        # The board may still be booting or in the sketch's USB attach delay.
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            self.handle.write(PROBE)
            attempt = min(deadline, time.monotonic() + 1)
            while (line := self.line(attempt)) is not None:
                if line == PROBE_REPLY:
                    return
        raise FlashError("Board did not answer the OTA probe. Check the port or use --manual.")

    def monitor(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if not self.handle.is_open:
                    self.handle.open()
                line = self.line(deadline)
                if line is not None:
                    print(line, flush=True)
            except OSError:
                self.handle.close()
                self.pending.clear()
                time.sleep(0.1)


def upload(image, port, bad_md5):
    digest = hashlib.md5(image).hexdigest()
    if bad_md5:
        digest = ("0" if digest[0] != "0" else "1") + digest[1:]
    started = time.monotonic()
    with open_serial(port) as handle:
        print(f"Serial: {port} @ {BAUD} (no reset)", flush=True)
        replies = Replies(handle)
        replies.synchronize()
        # Leading newline drops any unfinished command from a previous session.
        handle.write(f"\nGZOTA1 {len(image)} {digest}\n".encode("ascii"))
        try:
            ready = replies.expect("READY")
            match = re.fullmatch(r"GZOTA READY ([0-9]{1,4}) GZOTA1-CAPABLE", ready)
            if not match or not 0 < (block_size := int(match[1])) <= 8192:
                raise FlashError(f"Invalid READY reply: {ready}")
            print(ready, flush=True)
            progress = -10
            for offset in range(0, len(image), block_size):
                chunk = image[offset:offset + block_size]
                if handle.write(chunk) != len(chunk):
                    raise FlashError("Short serial write")
                total = offset + len(chunk)
                ack = replies.expect("ACK")
                if ack != f"GZOTA ACK {total}":
                    raise FlashError(f"Expected ACK {total}; device replied: {ack}")
                percent = 100 * total // len(image)
                if percent >= progress + 10 or percent == 100:
                    print(f"{percent:3}%  {total}/{len(image)} bytes", flush=True)
                    progress = percent
            done = replies.expect("DONE")
            if done != "GZOTA DONE":
                raise FlashError(f"Invalid DONE reply: {done}")
        except DeviceError as exc:
            print(str(exc), file=sys.stderr, flush=True)
            replies.monitor()
            return 1
        print(f"{done} ({time.monotonic() - started:.1f} s)", flush=True)
        replies.monitor()
    return 0


def manual_flash(app, port):
    basename = app.name.removesuffix(".bin")
    images = {
        "0x1000": app.with_name(f"{basename}.bootloader.bin"),
        "0x8000": app.with_name(f"{basename}.partitions.bin"),
        "0xe000": BOOT_APP0,
        "0x10000": app,
    }
    for file in images.values():
        if not file.is_file():
            raise FlashError(f"Missing image: {file}")
    input("把 IO0 接到 GND，按一下 RST。确认进入下载模式后按回车：")
    started = time.monotonic()
    subprocess.run(
        [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", port,
         "--before", "no_reset", "--after", "no_reset", "--baud", "460800", "write_flash",
         *(part for address, path in images.items() for part in (address, str(path)))],
        cwd=ROOT, check=True,
    )
    print(f"烧录完成（{time.monotonic() - started:.1f} s）。拔掉 IO0 接地线，再按一下 RST。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("sketch", nargs="?", type=Path)
    source.add_argument("--bin", type=Path, dest="binary")
    parser.add_argument("--fqbn", default=DEFAULT_FQBN)
    parser.add_argument("--port", default=default_port())
    parser.add_argument("--manual", action="store_true", help="bootstrap a classic ESP32 with esptool")
    parser.add_argument("--force", action="store_true", help="allow a bin without the OTA marker")
    parser.add_argument("--bad-md5", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.manual and (args.binary or args.fqbn != DEFAULT_FQBN or args.bad_md5):
        parser.error("--manual requires a sketch and the default ESP32 FQBN (no --bad-md5)")

    try:
        with tempfile.TemporaryDirectory(prefix="gezhi-flash-") as output:
            app = (args.binary or compile_sketch(args.sketch.resolve(), args.fqbn, Path(output)))
            image = app.read_bytes()
            if CAPABLE not in image:
                warning = "固件没有 GZOTA1-CAPABLE 标记；烧录后将失去串口自升级，下次只能接 IO0 线。"
                if not args.force:
                    raise FlashError(f"拒绝上传：{warning} 确认要继续时加 --force。")
                print(f"警告：{warning}", file=sys.stderr)
            if not image or image[0] != 0xE9:
                raise FlashError("不是 ESP32 app bin")
            if args.manual:
                manual_flash(app, args.port)
                return 0
            return upload(image, args.port, args.bad_md5)
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except (FlashError, OSError, subprocess.CalledProcessError, EOFError) as exc:
        print(f"Flash error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
