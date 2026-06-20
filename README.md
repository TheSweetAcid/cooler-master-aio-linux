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
