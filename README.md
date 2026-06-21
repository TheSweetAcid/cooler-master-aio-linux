# Cooler Master AIO Linux

Unofficial Linux userspace HID daemon for selected Cooler Master AIO displays.

Project codename: **CoolerKitty**

Currently tested on:

- Cooler Master **MLQ-Core-Nex-Digital-WH**
- USB/HID ID: `2516:0234`

This project writes HID reports directly to the device through Linux `hidraw`. It does not use the official Cooler Master software and it is not a kernel driver.

> [!WARNING]
> This is an unofficial experimental proof of concept. It is not affiliated with Cooler Master. Use it at your own risk.

## Files

```text
coolerkitty.py   Main userspace daemon that feeds live Linux sensor values to the AIO display.
cm-aio-map.py    Interactive mapper/debug tool for testing the HID payload manually.
README.md        This file.
```

That is intentionally all for now. No installer, no packaged service unit, no distribution-specific setup.

## Current status

On my machine this currently:

- runs as a systemd service after reboot
- reads Linux sensor data directly
- updates the AIO display without the vendor app
- shows CPU usage
- shows CPU frequency
- shows CPU/GPU temperature
- shows GPU usage
- shows fan RPM
- updates the outer ring / graph

The repository only includes the Python scripts and this README. My local systemd setup is intentionally not included because paths, users, groups, udev rules, and fan sensor mapping can be distribution- and motherboard-specific.

This is not a polished universal driver. It almost certainly has bugs, rough edges, missing features, and places where it can be improved.

## Project background

This project was built as an AI-assisted reverse-engineering experiment.

I am not a professional programmer. The actual coding was done with significant help from Codex, based on my testing, hardware access, observations, and requirements.

I knew what I wanted the device to do, tested the results on real hardware, captured how the display reacted, and iterated until it worked reliably enough to run as a Linux system service on my own machine.

I decided to publish it because I found several people looking for Cooler Master AIO Linux display support, but I could not find a working answer for this device. So I sat down for a while, tested the HID device directly, and got something working.

Contributions, fixes, cleaner sensor handling, support for more models, and improved HID mapping are welcome.

## Quick test

Run the daemon once with verbose output:

```bash
python3 ./coolerkitty.py --verbose --once
```

Run it continuously from the checkout:

```bash
python3 ./coolerkitty.py --verbose
```

Run the interactive mapper:

```bash
python3 ./cm-aio-map.py
```

Do not run `coolerkitty.py` and `cm-aio-map.py` at the same time. Both write to the same HID device.

## Configuration defaults

The daemon keeps the common defaults near the top of `coolerkitty.py`:

```python
DEFAULT_INTERVAL = 5.0
DEFAULT_RING = "gpu"
DEFAULT_TEMP_MODE = "cycle"
DEFAULT_TEMP_UNIT = "c"
DEFAULT_TEMP_SWITCH = 15.0
DEFAULT_CPU_MAX_TEMP = 95.0
DEFAULT_GPU_MAX_TEMP = 110.0
DEFAULT_HIGH_TEMP = 85.0
DEFAULT_SMOOTH = 0.25
DEFAULT_PUMP_RPM_INPUT = "fan7_input"
DEFAULT_PUMP_MAX_RPM = 3200.0
```

Those defaults are meant to be readable and easy to adjust for experiments. Runtime overrides are still available through command-line arguments, for example:

```bash
python3 ./coolerkitty.py --cpu-max-temp 90 --gpu-max-temp 105 --ring gpu --temp-switch 15 --temp-unit c
python3 ./coolerkitty.py --ring pump --pump-max-rpm 3200
```

Sensor discovery is intentionally still dynamic. Avoid hard-coding paths like `hwmon3/temp1_input` for shared use because Linux `hwmon` numbers can change after reboot and differ between systems.

`DEFAULT_HIGH_TEMP` is reserved for a future alert policy. The current renderer does not trigger special alert animation yet.

## Device / HID notes

Known device:

```text
Vendor/Product: 2516:0234
Device name:    MLQ-Core-Nex-Digital-WH
Manufacturer:   CoolerMaster
Report ID:      0x10
Report length:  64 bytes
Useful payload: first 13 bytes after report ID
Padding:         remaining bytes are zero
```

Report sent to `hidraw`:

```text
byte 0:     report ID 0x10
byte 1..13: payload
byte 14..63: zero padding
```

## Known payload map

Payload positions below are 1-based and exclude the report ID.

```text
b1       unknown / mode-ish; no useful confirmed role yet
b2       CPU usage percent, 0..100
w3-b4    CPU frequency in MHz, big-endian
b5       temperature icon/source: 0 = CPU icon, 1 = GPU icon
w6-b7    temperature in whole degrees, big-endian
b8       temperature unit: 0 = Celsius, 1 = Fahrenheit
b9       thermometer mini graph, 0..10
w10-b11  fan RPM, big-endian
b12      outer ring segment count, 0..20
b13      unknown / no visible change observed yet
```

Important note: the byte numbering above describes the payload after the report ID. If your write buffer includes the report ID as byte `0`, shift payload offsets by `+1`.

GPU usage is currently used as a source for the outer ring through b12, scaled from 0..100% to 0..20 segments.
The outer ring can also use CPU usage, displayed fan RPM, or pump RPM with `--ring cpu|gpu|rpm|pump`.

## Sensor sources used on my system

The current implementation reads Linux sensor data such as:

- CPU temperature from `k10temp`
- CPU usage from `/proc/stat`
- CPU frequency from `cpufreq`
- GPU usage from AMD `gpu_busy_percent`
- GPU temperature from `amdgpu`
- fan RPM from `nct6799` via `nct6775`

Fan sensor mapping is motherboard-specific.

On my system:

```text
fan2 = AIO radiator fans
fan7 = likely pump RPM
```

Pump RPM can be used as the outer ring source on systems where the pump is exposed as a motherboard fan input:

```bash
python3 ./coolerkitty.py --ring pump --pump-rpm-path /sys/class/hwmon/hwmonX/fan7_input --pump-max-rpm 3200
```

## Known limitations / scope

* Tested only on my hardware.
* Sensor paths may need adjustment on other systems.
* Fan mapping is motherboard-specific.
* Only one Cooler Master AIO HID device is currently known/tested.
* This writes directly to a HID device.
* This project only targets the segment LCD telemetry display.
* ARGB, lighting effects, color control, fan curves, pump curves, profiles, and other Cooler Master software features are out of scope.
* Color control is not mapped and will not be handled by this Python script.
* Installation, systemd service setup, udev rules, packaging, and distribution-specific integration are not included and are intentionally out of scope for this repository.

## Disclaimer

This project is unofficial and is not affiliated with Cooler Master.

It is an experimental proof of concept, provided as-is, with no warranty. Use it, fork it, modify it, break it, fix it, or adapt it for your own hardware — but use it at your own risk.

## License

MIT License.
