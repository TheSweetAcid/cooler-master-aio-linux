#!/usr/bin/env python3
import argparse
import glob
import os
import signal
import sys
import time


REPORT_ID = 0x10
REPORT_LEN = 64
VENDOR_ID = "2516"
PRODUCT_ID = "0234"

# User-tunable defaults. Keep sensor discovery dynamic; hwmon numbers can change
# after reboot and between systems.
DEFAULT_INTERVAL = 5.0  # seconds between display refreshes
DEFAULT_RING = "gpu"  # outer ring source: cpu, gpu, rpm, pump
DEFAULT_TEMP_MODE = "cycle"  # temperature page: cpu, gpu, cycle
DEFAULT_TEMP_UNIT = "c"  # displayed temperature unit: c, f
DEFAULT_TEMP_SWITCH = 15.0  # seconds per CPU/GPU page when temp mode is cycle
DEFAULT_CPU_MAX_TEMP = 95.0  # C value that maps CPU tempbar to 10/10
DEFAULT_GPU_MAX_TEMP = 110.0  # C value that maps GPU tempbar to 10/10
DEFAULT_HIGH_TEMP = 85.0  # C threshold for optional alert renderer
DEFAULT_ALERT_EFFECT = "blink"  # hot ring effect: blink, scan
DEFAULT_ALERT_BLINK_HALF_PERIOD = 0.1  # seconds between full/off blink states
DEFAULT_ALERT_SCAN_STEP = 0.025  # seconds per 0->20->0 scan step
DEFAULT_ALERT_SWITCH = 3.0  # seconds per CPU/GPU page when both are hot
DEFAULT_SMOOTH = 0.25  # EMA alpha for percentages; lower = calmer, 1.0 = raw
DEFAULT_RPM_HWMON = "nct6799"  # hwmon chip name for radiator fan RPM
DEFAULT_RPM_INPUT = "fan2_input"  # motherboard-specific fan input
DEFAULT_PUMP_RPM_INPUT = "fan7_input"  # motherboard-specific pump input
DEFAULT_PUMP_MAX_RPM = 3200.0  # pump RPM that maps outer ring to 100%
DEFAULT_CPU_TEMP_HWMON = "k10temp"  # CPU temperature hwmon chip
DEFAULT_CPU_TEMP_LABEL = "Tctl"  # preferred CPU temperature label
DEFAULT_GPU_HWMON = "amdgpu"  # AMD GPU hwmon chip
DEFAULT_GPU_TEMP_LABEL = "edge"  # preferred GPU temperature label

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


def clamp(value, low, high):
    return max(low, min(high, value))


def read_text(path):
    try:
        with open(path, "r", encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


def read_int(path):
    text = read_text(path)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
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
            vendor = (read_text(os.path.join(current, "idVendor")) or "").lower()
            product = (read_text(os.path.join(current, "idProduct")) or "").lower()
            if vendor == VENDOR_ID and product == PRODUCT_ID:
                return os.path.join("/dev", name)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return None


def hwmons_by_name(name):
    result = []
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if read_text(os.path.join(hwmon, "name")) == name:
            result.append(hwmon)
    return result


def find_labeled_input(hwmon, prefix, wanted_label):
    for label_path in glob.glob(os.path.join(hwmon, f"{prefix}*_label")):
        label = read_text(label_path)
        if label == wanted_label:
            input_path = label_path[:-6] + "_input"
            if os.path.exists(input_path):
                return input_path
    return None


def find_cpu_temp_path():
    for hwmon in hwmons_by_name(DEFAULT_CPU_TEMP_HWMON):
        path = find_labeled_input(hwmon, "temp", DEFAULT_CPU_TEMP_LABEL)
        if path:
            return path
        fallback = os.path.join(hwmon, "temp1_input")
        if os.path.exists(fallback):
            return fallback
    return None


def find_rpm_path(input_name=DEFAULT_RPM_INPUT):
    for hwmon in hwmons_by_name(DEFAULT_RPM_HWMON):
        path = os.path.join(hwmon, input_name)
        if os.path.exists(path):
            return path
    return None


def find_gpu_busy_path():
    candidates = []
    for path in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        driver = os.path.basename(os.path.realpath(os.path.join(os.path.dirname(path), "driver")))
        score = 0 if driver == "amdgpu" else 1
        candidates.append((score, path))
    if not candidates:
        return None
    return sorted(candidates)[0][1]


def find_gpu_temp_path():
    for hwmon in hwmons_by_name(DEFAULT_GPU_HWMON):
        path = find_labeled_input(hwmon, "temp", DEFAULT_GPU_TEMP_LABEL)
        if path:
            return path
        fallback = os.path.join(hwmon, "temp1_input")
        if os.path.exists(fallback):
            return fallback
    return None


def smooth(prev, value, alpha):
    if prev is None:
        return value
    return prev + (value - prev) * alpha


def cpu_times():
    try:
        with open("/proc/stat", "r", encoding="ascii") as f:
            line = f.readline().strip()
    except OSError:
        return None
    if not line.startswith("cpu "):
        return None
    values = [int(x) for x in line.split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def cpu_usage(prev):
    now = cpu_times()
    if prev is None or now is None:
        return 0, now
    idle_delta = now[0] - prev[0]
    total_delta = now[1] - prev[1]
    if total_delta <= 0:
        return 0, now
    usage = round((1.0 - idle_delta / total_delta) * 100)
    return clamp(usage, 0, 100), now


def cpu_ghz_milli():
    values = []
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
        value = read_int(path)
        if value:
            values.append(value)
    if not values:
        return 0
    return clamp(round(sum(values) / len(values) / 1000), 0, 9999)


def build_frame(cpu_pct, ghz_milli, temp_value, temp_unit, rpm, gpu_pct, ring_pct):
    frame = [0] * 13
    frame[0] = 0x01
    frame[1] = clamp(round(cpu_pct), 0, 100)
    frame[2] = (ghz_milli >> 8) & 0xff
    frame[3] = ghz_milli & 0xff
    frame[4] = 0x00
    display_temp = clamp(round(temp_value), 0, 999)
    frame[5] = (display_temp >> 8) & 0xff
    frame[6] = display_temp & 0xff
    frame[7] = 0x01 if temp_unit == "f" else 0x00
    frame[8] = 0
    rpm_value = clamp(round(rpm), 0, 9999)
    frame[9] = (rpm_value >> 8) & 0xff
    frame[10] = rpm_value & 0xff
    frame[11] = clamp(round(ring_pct / 5), 0, 20)
    frame[12] = 0x0d
    data = [REPORT_ID] + frame
    data.extend([0] * (REPORT_LEN - len(data)))
    return bytes(data), frame


def frame_bytes(frame):
    return bytes([REPORT_ID] + frame + [0] * (REPORT_LEN - 1 - len(frame)))


def temp_bar(temp_c, max_temp_c):
    if max_temp_c <= 0:
        return 0
    return clamp(round(temp_c / max_temp_c * 10), 0, 10)


def display_temp(temp_c, unit):
    if unit == "f":
        return temp_c * 9 / 5 + 32
    return temp_c


def fmt_frame(frame):
    return " ".join(f"{b:02x}" for b in frame)


def alert_ring_sequence(effect):
    if effect == "scan":
        return list(range(21)) + list(range(19, -1, -1))
    return [20, 0]


def main():
    parser = argparse.ArgumentParser(description="Cooler Master AIO display userspace feeder")
    parser.add_argument("--dev", default=None, help="default: auto-detect 2516:0234")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--rpm-path", default=None, help=f"default: {DEFAULT_RPM_HWMON} {DEFAULT_RPM_INPUT}")
    parser.add_argument("--pump-rpm-path", default=None, help=f"default: {DEFAULT_RPM_HWMON} {DEFAULT_PUMP_RPM_INPUT}")
    parser.add_argument("--pump-max-rpm", type=float, default=DEFAULT_PUMP_MAX_RPM, help="pump RPM that maps outer ring to 100%%")
    parser.add_argument("--ring", choices=["cpu", "gpu", "rpm", "pump"], default=DEFAULT_RING)
    parser.add_argument("--temp-mode", choices=["cpu", "gpu", "cycle"], default=DEFAULT_TEMP_MODE)
    parser.add_argument("--temp-unit", choices=["c", "f"], default=DEFAULT_TEMP_UNIT, help="displayed temperature unit")
    parser.add_argument("--temp-switch", type=float, default=DEFAULT_TEMP_SWITCH, help="seconds per CPU/GPU temp page in cycle mode")
    parser.add_argument("--cpu-max-temp", type=float, default=DEFAULT_CPU_MAX_TEMP, help="CPU temp in C that maps thermometer mini graph b9 to 10/10")
    parser.add_argument("--gpu-max-temp", type=float, default=DEFAULT_GPU_MAX_TEMP, help="GPU temp in C that maps thermometer mini graph b9 to 10/10")
    parser.add_argument("--alert-enable", action="store_true", help="enable high-temperature alert renderer")
    parser.add_argument("--high-temp", type=float, default=DEFAULT_HIGH_TEMP, help="temperature in C that triggers alert renderer")
    parser.add_argument("--alert-effect", choices=["blink", "scan"], default=DEFAULT_ALERT_EFFECT, help="ring animation used while hot")
    parser.add_argument("--alert-blink-half-period", type=float, default=DEFAULT_ALERT_BLINK_HALF_PERIOD, help="seconds between full/off blink states")
    parser.add_argument("--alert-scan-step", type=float, default=DEFAULT_ALERT_SCAN_STEP, help="seconds per 0..20..0 scan step")
    parser.add_argument("--alert-switch", type=float, default=DEFAULT_ALERT_SWITCH, help="seconds per CPU/GPU page when both are hot")
    parser.add_argument("--smooth", type=float, default=DEFAULT_SMOOTH, help="EMA alpha for percentage displays; 1 disables smoothing")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    dev = args.dev or find_hidraw()
    if dev is None:
        print(f"ERR: nenasel jsem Cooler Master HID {VENDOR_ID}:{PRODUCT_ID}", file=sys.stderr)
        return 2

    cpu_temp_path = find_cpu_temp_path()
    gpu_temp_path = find_gpu_temp_path()
    rpm_path = args.rpm_path or find_rpm_path()
    pump_rpm_path = args.pump_rpm_path or find_rpm_path(DEFAULT_PUMP_RPM_INPUT)
    gpu_busy_path = find_gpu_busy_path()
    if args.verbose:
        print(f"dev={dev}")
        print(f"cpu_temp={cpu_temp_path}")
        print(f"gpu_temp={gpu_temp_path}")
        print(f"rpm={rpm_path}")
        print(f"pump_rpm={pump_rpm_path}")
        print(f"gpu_busy={gpu_busy_path}")

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    prev_cpu = cpu_times()
    start_time = time.monotonic()
    cpu_pct_s = None
    gpu_pct_s = None
    ring_pct_s = None
    while running:
        now = time.monotonic()
        cpu_pct, prev_cpu = cpu_usage(prev_cpu)
        gpu_pct = read_int(gpu_busy_path) if gpu_busy_path else 0
        cpu_pct_s = smooth(cpu_pct_s, cpu_pct, args.smooth)
        gpu_pct_s = smooth(gpu_pct_s, gpu_pct or 0, args.smooth)

        cpu_temp_raw = read_int(cpu_temp_path) if cpu_temp_path else None
        gpu_temp_raw = read_int(gpu_temp_path) if gpu_temp_path else None
        cpu_temp_c = (cpu_temp_raw / 1000.0) if cpu_temp_raw is not None else 0
        gpu_temp_c = (gpu_temp_raw / 1000.0) if gpu_temp_raw is not None else 0
        cpu_hot = args.alert_enable and cpu_temp_raw is not None and cpu_temp_c >= args.high_temp
        gpu_hot = args.alert_enable and gpu_temp_raw is not None and gpu_temp_c >= args.high_temp
        alert_active = cpu_hot or gpu_hot

        if cpu_hot and gpu_hot:
            page = int(now // max(args.alert_switch, 1.0)) % 2
            temp_source = "gpu" if page else "cpu"
        elif gpu_hot:
            temp_source = "gpu"
        elif cpu_hot:
            temp_source = "cpu"
        else:
            temp_source = args.temp_mode

        if temp_source == "cycle":
            page = int((now - start_time) // max(args.temp_switch, 1.0)) % 2
            temp_source = "gpu" if page and gpu_temp_path else "cpu"

        if temp_source == "gpu" and gpu_temp_raw is not None:
            temp_c = gpu_temp_c
            temp_icon = 1
        else:
            temp_c = cpu_temp_c
            temp_icon = 0
        max_temp_c = args.gpu_max_temp if temp_icon else args.cpu_max_temp
        ghz_milli = cpu_ghz_milli()
        rpm = read_int(rpm_path) if rpm_path else 0
        pump_rpm = read_int(pump_rpm_path) if pump_rpm_path else 0
        if args.ring == "gpu":
            ring_pct = gpu_pct_s
        elif args.ring == "rpm":
            ring_pct = clamp((rpm or 0) / 2000 * 100, 0, 100)
        elif args.ring == "pump":
            ring_pct = clamp((pump_rpm or 0) / args.pump_max_rpm * 100, 0, 100)
        else:
            ring_pct = cpu_pct_s
        ring_pct_s = smooth(ring_pct_s, ring_pct, args.smooth)

        temp_display = display_temp(temp_c, args.temp_unit)
        data, frame = build_frame(cpu_pct_s, ghz_milli, temp_display, args.temp_unit, rpm or 0, gpu_pct_s, ring_pct_s)
        frame[4] = temp_icon
        frame[8] = temp_bar(temp_c, max_temp_c)
        data = frame_bytes(frame)
        if args.verbose:
            print(
                f"alert={str(alert_active).lower()} cpu={cpu_pct_s:5.1f}% temp={temp_c:5.1f}C/{temp_source} "
                f"display={temp_display:5.1f}{args.temp_unit.upper()} "
                f"tempbar={frame[8]:2d}/10 "
                f"ghz={ghz_milli/1000:.2f} rpm={rpm or 0:4d} pump={pump_rpm or 0:4d} gpu={gpu_pct_s:5.1f}% "
                f"ring={ring_pct_s:5.1f}% frame={fmt_frame(frame)}",
                flush=True,
            )
        with open(dev, "wb", buffering=0) as f:
            if alert_active:
                step = args.alert_scan_step if args.alert_effect == "scan" else args.alert_blink_half_period
                for segment in alert_ring_sequence(args.alert_effect):
                    frame[11] = segment
                    f.write(frame_bytes(frame))
                    if args.once:
                        break
                    if not running:
                        break
                    time.sleep(max(step, 0.01))
            else:
                f.write(data)
        if args.once:
            break
        if not alert_active:
            time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
