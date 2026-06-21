#!/usr/bin/env python3
import argparse
import os
import sys
import threading
import time


DEFAULT_FRAME = [0x01, 0x2a, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x04, 0xd2, 0x0c, 0x0d]
REPORT_ID = 0x10
REPORT_LEN = 64
VENDOR_ID = "2516"
PRODUCT_ID = "0234"

# Payload map, 1-based positions after report ID 0x10:
# b1       unknown / mode-ish
# b2       CPU usage percent, 0..100
# w3-b4    CPU frequency in MHz, big-endian
# b5       temperature icon/source: 0 = CPU, 1 = GPU
# w6-b7    temperature in whole degrees C/F, big-endian
# b8       temperature unit: 0 = C, 1 = F
# b9       thermometer mini graph, 0..10
# w10-b11  fan RPM, big-endian
# b12      outer ring segment count, 0..20
# b13      unknown


def parse_int(text):
    text = text.strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    return int(text, 10)


def fmt_frame(frame):
    return " ".join(f"{b:02x}" for b in frame)


def read_sys_text(path):
    try:
        with open(path, "r", encoding="ascii") as f:
            return f.read().strip().lower()
    except OSError:
        return None


def find_hidraw():
    root = "/sys/class/hidraw"
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None

    for name in names:
        dev_root = os.path.realpath(os.path.join(root, name, "device"))
        current = dev_root
        for _ in range(8):
            vendor = read_sys_text(os.path.join(current, "idVendor"))
            product = read_sys_text(os.path.join(current, "idProduct"))
            if vendor == VENDOR_ID and product == PRODUCT_ID:
                return os.path.join("/dev", name)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return None


class PumpMapper:
    def __init__(self, dev, interval):
        self.dev = dev
        self.interval = interval
        self.frame = DEFAULT_FRAME[:]
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.scene = "BASE"
        self.writes = 0
        self.last_error = None

    def payload(self):
        with self.lock:
            data = [REPORT_ID] + self.frame[:]
            data.extend([0x00] * (REPORT_LEN - len(data)))
            return bytes(data)

    def set_scene(self, scene):
        with self.lock:
            self.scene = scene

    def set_byte(self, pos, value):
        if not 1 <= pos <= 13:
            raise ValueError("b pozice musi byt 1..13")
        if not 0 <= value <= 255:
            raise ValueError("byte hodnota musi byt 0..255")
        with self.lock:
            self.frame[pos - 1] = value
            self.scene = f"B{pos}={value}"

    def set_word(self, pos, value):
        if not 1 <= pos <= 12:
            raise ValueError("w pozice musi byt 1..12")
        if not 0 <= value <= 65535:
            raise ValueError("word hodnota musi byt 0..65535")
        with self.lock:
            self.frame[pos - 1] = (value >> 8) & 0xff
            self.frame[pos] = value & 0xff
            self.scene = f"W{pos}-{pos + 1}={value}"

    def reset(self):
        with self.lock:
            self.frame = DEFAULT_FRAME[:]
            self.scene = "BASE"

    def status(self):
        with self.lock:
            return self.scene, self.frame[:], self.writes, self.last_error

    def writer(self):
        while not self.stop.is_set():
            data = self.payload()
            try:
                with open(self.dev, "wb", buffering=0) as f:
                    f.write(data)
                with self.lock:
                    self.writes += 1
                    self.last_error = None
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
            self.stop.wait(self.interval)


def print_help():
    print(
        """
Commands / Prikazy:
  show                 print current scene and 13 payload bytes / vypise scenu a payload
  base                 reset known baseline / vrati znamy baseline
  bN VALUE             set one byte, e.g. b3 65 or b3 0x41 / nastavi byte
  wN VALUE             set big-endian word from N, e.g. w10 1234 / nastavi dvojici
  cpu VALUE            alias for b2 VALUE; 0..100 / zkratka pro CPU %
  ghz VALUE            alias for w3 VALUE*1000, e.g. ghz 4.20 / CPU frekvence
  temp VALUE           alias for w6 VALUE, e.g. temp 65 / teplota
  temp-src cpu|gpu     alias for b5 0/1 / ikonka zdroje teploty
  unit c|f             alias for b8 0/1 / jednotka teploty
  tempbar VALUE        alias for b9 VALUE; 0..10 / mini graf u teplomeru
  rpm VALUE            alias for w10 VALUE / otacky
  ring VALUE           alias for b12 VALUE; 0..20 / vnejsi kruh
  scene NAME           rename current scene only / prejmenuje scenu pro poznamky
  help                 show this help / tahle napoveda
  quit                 exit / konec

Payload positions are 1..13 and do not include report ID 0x10.
Pozice jsou payload pozice 1..13, bez report ID 0x10.
""".strip()
    )


def main():
    parser = argparse.ArgumentParser(description="Interactive Cooler Master AIO HID mapper")
    parser.add_argument("--dev", default=None, help="default: auto-detect 2516:0234")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.dev is None:
        args.dev = find_hidraw()
        if args.dev is None:
            print(f"ERR: nenasel jsem Cooler Master HID {VENDOR_ID}:{PRODUCT_ID}; pouzij --dev /dev/hidrawX", file=sys.stderr)
            return 2

    mapper = PumpMapper(args.dev, args.interval)
    thread = threading.Thread(target=mapper.writer, daemon=True)
    thread.start()

    print(f"Writing keepalive to {args.dev} every {args.interval:.2f}s")
    print_help()
    scene, frame, _, _ = mapper.status()
    print(f"[{scene}] {fmt_frame(frame)}")

    while True:
        try:
            line = input("cm-map> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        try:
            if cmd in ("q", "quit", "exit"):
                break
            if cmd in ("h", "help", "?"):
                print_help()
                continue
            if cmd == "show":
                pass
            elif cmd == "base":
                mapper.reset()
            elif cmd == "scene":
                if len(parts) < 2:
                    raise ValueError("scene potrebuje jmeno")
                mapper.set_scene(" ".join(parts[1:]))
            elif cmd == "cpu":
                if len(parts) != 2:
                    raise ValueError("cpu VALUE")
                mapper.set_byte(2, parse_int(parts[1]))
            elif cmd == "ghz":
                if len(parts) != 2:
                    raise ValueError("ghz VALUE")
                mapper.set_word(3, round(float(parts[1].replace(",", ".")) * 1000))
                mapper.set_scene(f"GHz={parts[1]}")
            elif cmd == "temp":
                if len(parts) != 2:
                    raise ValueError("temp VALUE")
                mapper.set_word(6, parse_int(parts[1]))
                mapper.set_scene(f"TEMP={parts[1]}")
            elif cmd == "temp-src":
                if len(parts) != 2:
                    raise ValueError("temp-src cpu|gpu")
                value = parts[1].lower()
                if value == "cpu":
                    mapper.set_byte(5, 0)
                elif value == "gpu":
                    mapper.set_byte(5, 1)
                else:
                    raise ValueError("temp-src cpu|gpu")
                mapper.set_scene(f"TEMP_SRC={value}")
            elif cmd == "unit":
                if len(parts) != 2:
                    raise ValueError("unit c|f")
                value = parts[1].lower()
                if value == "c":
                    mapper.set_byte(8, 0)
                elif value == "f":
                    mapper.set_byte(8, 1)
                else:
                    raise ValueError("unit c|f")
                mapper.set_scene(f"UNIT={value.upper()}")
            elif cmd == "tempbar":
                if len(parts) != 2:
                    raise ValueError("tempbar VALUE")
                mapper.set_byte(9, parse_int(parts[1]))
                mapper.set_scene(f"TEMPBAR={parts[1]}")
            elif cmd == "rpm":
                if len(parts) != 2:
                    raise ValueError("rpm VALUE")
                mapper.set_word(10, parse_int(parts[1]))
            elif cmd == "ring":
                if len(parts) != 2:
                    raise ValueError("ring VALUE")
                mapper.set_byte(12, parse_int(parts[1]))
                mapper.set_scene(f"RING={parts[1]}")
            elif cmd.startswith("b"):
                if len(parts) != 2:
                    raise ValueError("bN VALUE")
                mapper.set_byte(parse_int(cmd[1:]), parse_int(parts[1]))
            elif cmd.startswith("w"):
                if len(parts) != 2:
                    raise ValueError("wN VALUE")
                mapper.set_word(parse_int(cmd[1:]), parse_int(parts[1]))
            else:
                raise ValueError("neznamy prikaz, dej help")
        except Exception as exc:
            print(f"ERR: {exc}")
            continue

        scene, frame, writes, err = mapper.status()
        print(f"[{scene}] writes={writes} payload={fmt_frame(frame)}")
        if err:
            print(f"last error: {err}")

    mapper.stop.set()
    thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
