"""Plot and record newline-delimited sensor readings from an ESP32."""

import argparse
from collections import deque
import csv
from datetime import datetime
import glob
from itertools import count
import math
from pathlib import Path
import threading
import time

import serial


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IMU_HEADER = "ax(g)\tay(g)\taz(g)\t|a|(g)\tgx\tgy\tgz (deg/s)"


def log(line):
    print(line, flush=True)


class Recorder:
    def __init__(self, window):
        self.window = window
        self.columns = ()
        self.pending = deque()
        self.samples = deque()
        self.lock = threading.Lock()
        self.revision = 0
        self.stem = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.file = None
        self.file_index = 0
        DATA_DIR.mkdir(exist_ok=True)
        self.open_csv()

    def open_csv(self):
        while True:
            suffix = f"-{self.file_index}" if self.file_index else ""
            self.path = DATA_DIR / f"{self.stem}{suffix}.csv"
            self.file_index += 1
            try:
                self.file = self.path.open("x", encoding="utf-8", newline="")
                break
            except FileExistsError:
                continue
        self.writer = csv.writer(self.file)
        self.rows = 0
        self.write_header(())

    def write_header(self, columns):
        self.file.seek(0)
        self.writer.writerow(("host_t(s)", *columns))
        self.file.truncate()
        self.file.flush()

    def close_csv(self):
        self.file.close()
        log(f"CSV: {self.path} ({self.rows} data rows)")

    def finish(self):
        self.flush_pending()
        self.close_csv()

    def flush_pending(self, width=0):
        columns = None
        while self.pending:
            line, fields = self.pending.popleft()
            if fields and len(fields) == width:
                columns = fields
            else:
                log(line)
        return columns

    def receive(self, line, host_t):
        fields = tuple(s.strip() for s in line.split("\t" if "\t" in line else ","))
        try:
            values = tuple(float(s) for s in fields)
        except ValueError:
            # Keep the latest possible header of each width until the next row.
            if line.strip():
                for i, (old_line, old_fields) in enumerate(self.pending):
                    if old_fields and len(old_fields) == len(fields):
                        self.pending[i] = old_line, None
                        break
            self.pending.append((line, fields if line.strip() else None))
            while self.pending and (self.pending[0][1] is None or len(self.pending) > 128):
                log(self.pending.popleft()[0])
            return

        columns = self.flush_pending(len(values))
        if not columns:
            columns = self.columns
            if len(columns) != len(values):
                columns = tuple(f"c{i + 1}" for i in range(len(values)))

        changed = columns != self.columns
        if changed:
            if self.rows:
                self.close_csv()
                self.open_csv()
            self.write_header(columns)
        self.writer.writerow((f"{host_t:.6f}", *fields))
        self.file.flush()
        self.rows += 1

        # A lone column is a reading, not an x axis with nothing to plot.
        x = values[0] if uses_device_time(columns) else host_t
        with self.lock:
            if changed:
                self.columns = columns
                self.samples.clear()
            if math.isfinite(x):
                if self.samples and x < self.samples[-1][0]:
                    self.samples.clear()
                self.samples.append((x, *values))
                while self.samples[0][0] < x - self.window:
                    self.samples.popleft()
            self.latest = values
            self.revision += 1

    def snapshot(self, revision):
        with self.lock:
            if revision == self.revision:
                return None
            return self.revision, self.columns, list(self.samples), self.latest


def uses_device_time(columns):
    return len(columns) > 1 and columns[0].lower().startswith("t")


def fake_source(receive, stop, started):
    receive(IMU_HEADER)
    for i in count():
        t = i / 50
        if stop.wait(max(0, started + t - time.monotonic())):
            return
        if i in (50, 125, 200):
            receive("fake: simulated read warning")
        angle = math.tau * t
        ax, ay = 0.1 * math.sin(angle), 0.1 * math.cos(angle)
        az = 1 + 0.2 * math.sin(angle)
        magnitude = math.sqrt(ax * ax + ay * ay + az * az)
        receive(f"{ax:.3f}\t{ay:.3f}\t{az:.3f}\t{magnitude:.3f}\t"
                f"{5*ax:.1f}\t{5*ay:.1f}\t{5*(az-1):.1f}")


def serial_source(args, receive, flush_pending, stop):
    reset_pending = args.reset
    while not stop.is_set():
        handle = serial.Serial(baudrate=args.baud, timeout=0.1)
        handle.dtr = False
        handle.rts = False
        handle.port = args.port
        error = None
        try:
            try:
                handle.open()
                log(f"Serial: {args.port} @ {args.baud}")
                if reset_pending:
                    reset_pending = False
                    handle.rts = True
                    try:
                        stop.wait(0.1)
                    finally:
                        handle.rts = False
            except OSError as exc:
                error = exc

            pending = b""
            while error is None and not stop.is_set():
                try:
                    chunk = handle.read(handle.in_waiting or 1)
                except OSError as exc:
                    error = exc
                    break
                if chunk:
                    *lines, pending = (pending + chunk).split(b"\n")
                    for line in lines:
                        receive(line.removesuffix(b"\r").decode("utf-8", errors="replace"))
        finally:
            try:
                handle.close()
            except OSError as exc:
                error = error or exc
        if error is not None:
            flush_pending()
            if not stop.is_set():
                log(f"Serial unavailable: {error}; retrying in 1 s")
        stop.wait(1)


class Plot:
    def __init__(self, args, plt):
        self.args = args
        self.fig, self.ax = plt.subplots(figsize=(10, 5))
        self.fig.subplots_adjust(top=0.86)
        self.ax.set_xlabel("host_t(s)")
        self.ax.set_title("Waiting for sensor data")
        self.ax.grid(True)
        self.revision = 0
        self.columns = ()

    def refresh(self, recorder):
        snapshot = recorder.snapshot(self.revision)
        if snapshot is None:
            return False
        self.revision, columns, samples, latest = snapshot
        if columns != self.columns:
            self.columns = columns
            self.ax.clear()
            device_time = uses_device_time(columns)
            self.ax.set_xlabel(columns[0] if device_time else "host_t(s)")
            self.ax.grid(True)
            self.lines = [
                (i, self.ax.plot([], [], label=name)[0])
                for i, name in enumerate(columns)
                if not (device_time and i == 0)
                and (not self.args.cols or name in self.args.cols)
            ]
            if self.lines:
                self.ax.legend(loc="upper left")

        if samples:
            axes = list(zip(*samples))
            for i, line in self.lines:
                line.set_data(axes[0], axes[i + 1])
            self.ax.set_xlim(axes[0][-1] - self.args.window, axes[0][-1])
            self.ax.relim()
            self.ax.autoscale_view(scalex=False)
        readings = [f"{columns[i]}: {latest[i]:.4g}" for i, _ in self.lines]
        self.ax.set_title("\n".join("   ".join(readings[i:i+4])
                                    for i in range(0, len(readings), 4))
                          or "No selected measurement columns")
        return True


def positive_seconds(text):
    seconds = float(text)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of seconds")
    return seconds


def default_port():
    ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/cu.usbmodem*"))
    return ports[0] if ports else "/dev/cu.usbmodem101"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=default_port())
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--cols", type=lambda s: {name.strip() for name in s.split(",")})
    parser.add_argument("--window", type=positive_seconds, default=10)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--seconds", type=positive_seconds)
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--png", type=Path)
    parser.add_argument("--reset", action="store_true", help="pulse RTS once after opening")
    args = parser.parse_args()

    if not args.no_gui or args.png:
        if args.no_gui:
            import matplotlib
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plot = Plot(args, plt)

    recorder = Recorder(args.window)
    stop = threading.Event()
    done = threading.Event()
    errors = []
    started = time.monotonic()
    deadline = started + args.seconds if args.seconds is not None else math.inf

    def receive(line):
        now = time.monotonic()
        if now < deadline and not stop.is_set():
            recorder.receive(line, now - started)

    def collect():
        try:
            if args.fake:
                fake_source(receive, stop, started)
            else:
                serial_source(args, receive, recorder.flush_pending, stop)
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=collect, name="sensor-reader")
    worker.start()
    try:
        if args.no_gui:
            done.wait(args.seconds)
        else:
            plt.show(block=False)
            while not done.is_set() and time.monotonic() < deadline \
                    and plt.fignum_exists(plot.fig.number):
                frame = time.monotonic()
                if plot.refresh(recorder):
                    plot.fig.canvas.draw_idle()
                plt.pause(max(0.001, 0.05 - (time.monotonic() - frame)))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join()
        recorder.finish()

    if errors:
        parser.exit(1, f"Recording failed: {errors[0]}\n")
    if args.png:
        plot.refresh(recorder)
        plot.fig.savefig(args.png)
        log(f"PNG: {args.png}")


if __name__ == "__main__":
    main()
