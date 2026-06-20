# Cooler Master AIO Linux

Unofficial Linux userspace HID daemon for selected Cooler Master AIO displays.

Project codename: **CoolerKitty**

Currently tested on:

- Cooler Master **MLQ-Core-Nex-Digital-WH**
- USB/HID ID: `2516:0234`

This project writes HID reports directly to the device through Linux `hidraw`. It does not use the official Cooler Master software and it is not a kernel driver.

## Current status

This is a working proof of concept.

On my machine it currently:

- runs as a systemd service after reboot
- reads Linux sensor data directly
- updates the AIO display without the vendor app
- shows CPU usage
- shows CPU frequency
- shows CPU/GPU temperature
- shows GPU usage
- shows fan RPM
- updates the outer ring / graph

It is not a polished universal driver. It almost certainly has bugs, rough edges, missing features, and places where it can be improved.

## Project background

This project was built as an AI-assisted reverse-engineering experiment.

I am not a professional programmer. The actual coding was done with significant help from Codex, based on my testing, hardware access, observations, and requirements.

I knew what I wanted the device to do, tested the results on real hardware, captured how the display reacted, and iterated until it worked reliably enough to run as a Linux system service.

I decided to publish it because I found several people looking for Cooler Master AIO Linux display support, but I could not find a working answer for this device. So I sat down for a while, tested the HID device directly, and got something working.

Contributions, fixes, cleaner sensor handling, support for more models, and improved HID mapping are welcome.

## Device / HID notes

Known device:

Vendor/Product: 2516:0234
Device name:    MLQ-Core-Nex-Digital-WH
Report ID:      0x10
Report length:  64 bytes

Known payload map so far, bytes after the report ID:

b1        unknown / mode-ish
b2        CPU usage %, 0..100
b3-b4     CPU frequency in MHz, big-endian
b5        temperature source/icon
          0 = CPU
          1 = GPU
b6-b7     temperature value, whole degrees, big-endian
b8        temperature unit
          0 = Celsius
          1 = Fahrenheit
b9        GPU usage %, 0..100
b10-b11   fan RPM, big-endian
b12       outer ring / graph segments, 0..20
b13       unknown / no visible change observed yet

Remaining bytes:
  zero padding

Important note: the byte numbering above describes the payload after the report ID. If your write buffer includes the report ID as byte 0, shift payload offsets by +1.

Sensor sources used on my system

Current implementation uses Linux sensor data such as:

CPU temperature from k10temp
CPU usage from /proc/stat
CPU frequency from cpufreq
GPU usage from AMD gpu_busy_percent
fan RPM from nct6799 via nct6775

Fan sensor mapping is motherboard-specific.

On my system:

fan2 = AIO radiator fans
fan7 = likely pump RPM
Known limitations
Tested only on my hardware.
The small thermometer graph is not mapped yet.
Color control is not mapped.
Sensor paths may need adjustment on other systems.
Fan mapping is motherboard-specific.
Only one Cooler Master AIO HID device is currently known/tested.
This writes directly to a HID device; use at your own risk.
Disclaimer

This project is unofficial and is not affiliated with Cooler Master.

It is an experimental proof of concept, provided as-is, with no warranty. Use it, fork it, modify it, break it, fix it, or adapt it for your own hardware — but use it at your own risk.

License

MIT License.
