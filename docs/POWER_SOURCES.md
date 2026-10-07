# Power sources: how to add one

This document is the same in the two repositories (driveragent on the board, driveragent-agx on the AGX).

The power log measures and shows. It does not save power. Each machine logs the power that its own sources give.
The pages (rk console **Power**, AGX dashboard **System > Power log**) read the log. They do not know which source
gave a value. Thus a new source needs no change to a page.

## 1. The parts of the power log

| Part | DA01 (board) | AGX02 |
|---|---|---|
| Log core: SQLite file, energy, events, before and after | `rk/common/powerlog.py` | `common/powerlog.py` (the same file) |
| Sources | `rk/console/rkconsole/power.py` | `common/power_sources.py` |
| Logger (one sample each second) | rk console, task in `Runtime` | agx-dashboard, `dashboard/power_log.py` |
| Log file | `<data drive>/console/power.sqlite` | `data/power.sqlite` |
| Core test | `python3 rk/common/tests/test_powerlog.py` | `tests/test_powerlog.py` |

The two copies of the core must stay identical. After a change, copy the file to the other repository and run the
two core tests.

## 2. The labels (rule W2)

Each value on a page has one label:

- `SENSOR`: a sensor on the machine reads the value now. Only `SENSOR` values go into the log samples and into the
  "System total".
- `MANUAL`: the owner typed a meter reading. The page shows its time. It is never a present value and it is never in
  the "System total".
- `NO SENSOR`: no source gives a value for this part.

`ESTIMATE` is used only for "time on a full battery".

Do not calculate a power value from the CPU load, the temperature or other signs. If a source cannot read a value,
it gives `NO SENSOR` with the reason.

## 3. The interface

A source is one Python class:

```python
from powerlog import PowerSource, Reading, SENSOR, NO_SENSOR   # AGX02: from common.powerlog import ...

class MySource(PowerSource):
    name = "my_source"                    # [a-z][a-z0-9_]*, shown on the page as the source

    def read(self, now: float) -> list[Reading]:
        # One Reading for each part that the source measures. Do not raise: on an error, return
        # Reading(part, None, NO_SENSOR, now, self.name, "<reason in plain words>").
        return [Reading(part="da01", watts=12.3, label=SENSOR, t=now, source=self.name,
                        what="supply input of DA01 (12 V)", rails={})]

    def probe(self) -> dict:
        # What the source found on this machine and why it is or is not used (shown on the page).
        return {"source": self.name, "used": True, "note": "..."}
```

- `part` is one of `da01`, `agx02`, `router`, `screen`, `other` (rk console). A rail of a part is in `rails`
  (name to watts); the log keeps each rail as the series `<part>:<rail>`.
- `what` tells the owner what the value measures (for example "sum of the module rails; the supply input is not
  measured"). Write it in plain words.
- `t` is the time of the reading on this machine. A `SENSOR` value older than 3 s is not a present value.
- The logger calls `read()` one time each second at most (rule W3). Keep it cheap: read sysfs files, or keep a socket
  open and give the last value. Do not start a process each second. Do a slow read in a thread and give the last
  value.

## 4. Steps to add a source

1. Write the class (Section 3) in `rk/console/rkconsole/power.py` (board) or `common/power_sources.py` (AGX).
2. Add its settings to the configuration: `[console.power]` in `rk/config/rk.toml` (board) or `power_log` in
   `config/dashboard.yaml` (AGX). Do not put an address or a channel number in the code.
3. Add the source to the list of sources that the logger reads (the place where the existing sources are made).
4. Write a test with recorded values (fake sysfs files, a recorded frame or message). Do not touch the hardware in a
   test.
5. Run the full test suite of the repository.
6. Restart the logger process (rk console or agx-dashboard). The part card then shows the new label and the source.
7. Compare the value with an external meter: type a manual reading for the same part. The page shows the ratio meter
   / sensor. Set the correction factor if necessary.

## 5. Sources for later (not written now)

| Source | Where the value comes from | Notes |
|---|---|---|
| Sensor on the I2C bus (INA219, INA226, INA3221) | The kernel hwmon driver: `/sys/class/hwmon/hwmonN/in*_input` (mV) and `curr*_input` (mA), or `power*_input` (µW) | On the board, the `hwmon` source reads it already: put the two paths and their units in `[console.power] hwmon`. Install the sensor and its device-tree entry first (owner work). Do not read the I2C bus directly from the console. |
| Meter with a serial interface | A serial device (`/dev/ttyUSB*`) | Read it in a thread with a time-out. Keep the last value and its time. Give `NO SENSOR` when the last value is older than 3 s. |
| Meter with a network interface (Modbus TCP, HTTP) | A local network address | Read it in a thread, one request each second at most, time-out below 1 s. Put the address in the settings. |
| PCB controller on the CAN bus | A CAN frame decoded by rk-cantap from the DBC | Read the decoded signal from the rk-cantap status file, as the Battery card does. The console does not send on a CAN interface (rule B2). Mark the value unverified until the DBC signal is confirmed. |

## 6. What each machine can measure now

- **AGX02**: `jetson_rails` reads the four INA3221 rails of the module (VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V0,
  VDDQ_VDD2_1V8AO). There is no VDD_IN rail, so the supply input of the carrier board is not measured. The total is
  the sum of the rails and reads less than a meter at the supply input. The owner sets a correction factor.
- **DA01**: `NO SENSOR`. The board has no sensor of the supply input voltage and current. The only power-supply
  device, `tcpm-source-psy-5-004e` (hwmon7, chip husb311), is the USB-C port that gives power to the screen (power
  role "source"); it shows 0 V and 0 A. `vcc12v_dcin` is a fixed regulator value (12 V), not a measurement. hwmon0 to
  hwmon6 are temperatures and hwmon8 is the fan.
- **Router, screen, other**: no source. Use manual readings.
