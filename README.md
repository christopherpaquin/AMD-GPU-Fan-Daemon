# AMD-GPU-Fan-Daemon

![License](https://img.shields.io/badge/license-Apache--2.0-blue)
![Platform](https://img.shields.io/badge/platform-Linux%20%2F%20systemd-informational)
![Status](https://img.shields.io/badge/status-experimental-orange)

A small root-privileged systemd daemon that watches AMD GPU temperature and
drives motherboard fan headers in response — closing the gap where case
fans only ever react to CPU heat, even when a hot GPU is what actually
needs the airflow.

## 📋 Table of contents

- [🎯 Overview](#-overview)
- [⚠️ Status: experimental](#️-status-experimental)
- [📦 Requirements](#-requirements)
- [🏗️ Architecture](#️-architecture)
- [🚀 Installation](#-installation)
- [🗑️ Uninstall](#️-uninstall)
- [▶️ Usage](#️-usage)
- [⚙️ Configuration](#️-configuration)
- [🩺 Troubleshooting](#-troubleshooting)
- [🔒 Security notes](#-security-notes)
- [📚 Documentation](#-documentation)
- [License](#license)

## 🎯 Overview

Most motherboards' fan headers are only wired, via BIOS/Super-I/O firmware,
to CPU temperature. On a system with a hot discrete GPU, the case fans that
help exhaust that heat never actually respond to it — only the GPU's own
onboard fan does. This daemon polls both CPU and GPU temperature directly
from Linux `hwmon` sysfs, computes a target PWM per fan header as
`max(cpu_curve(cpu_temp), gpu_curve(gpu_temp))`, and writes it — so the
case fans ramp up under GPU load exactly as they already do under CPU load,
without regressing the existing CPU-driven behavior.

It was built for one specific machine (an MSI Z390-A PRO with an AMD
Radeon AI PRO R9700), but the hwmon paths, curve breakpoints, and managed
fan headers are all `.env`-configurable — it should work on any board with
an `nct6775`-family Super I/O chip and an `amdgpu` GPU, with config changes.

## ⚠️ Status: experimental

This is a young, single-machine-tested project that runs as root and
writes directly to hardware fan controllers. Read
[🔒 Security notes](#-security-notes) and run the full
[real-machine smoke test](docs/runbook.md) before trusting it unattended.

## 📦 Requirements

| Requirement | Notes |
|---|---|
| Linux with systemd | Tested on Ubuntu 24.04 |
| Python ≥ 3.9 | Stdlib only — no runtime pip dependencies |
| `amdgpu` kernel driver loaded | Provides the GPU's `hwmon` temperature sensors |
| `nct6775` kernel driver loaded | Or another chip your board's `.env` is pointed at |
| root / `sudo` | Required to write `pwm*`/`pwm*_enable` sysfs files |

## 🏗️ Architecture

```text
┌─────────────────────┐     ┌─────────────────────┐
│   amdgpu hwmon       │     │   nct6797 hwmon      │
│   temp2_input        │     │   temp7_input (PECI) │
│   (GPU junction)      │     │   (CPU package)       │
└──────────┬───────────┘     └──────────┬───────────┘
           │                             │
           ▼                             ▼
     ┌───────────┐                 ┌───────────┐
     │ GPU curve │                 │ CPU curve │
     └─────┬─────┘                 └─────┬─────┘
           │                             │
           └───────────┬─────────────────┘
                        ▼
              target = max(gpu_pwm, cpu_pwm)
                        │
          dead-band + rate-limit gate (anti-chatter)
                        │
                        ▼
        ┌───────────────────────────────┐
        │ pwm2 / pwm4 / pwm7 (nct6797)  │
        │ each case-fan header           │
        └───────────────────────────────┘

  On stop / crash / SIGTERM → every header reverts to
  pwm*_enable=5 (hardware Smart-Fan-IV / BIOS auto curve)
```

See [fan_daemon/daemon.py](fan_daemon/daemon.py) for the control loop and
[fan_daemon/curve.py](fan_daemon/curve.py) for the interpolation/dead-band
math.

## 🚀 Installation

```bash
git clone https://github.com/christopherpaquin/AMD-GPU-Fan-Daemon.git
cd AMD-GPU-Fan-Daemon
./install.sh
```

- [x] Checks Python ≥ 3.9, `systemctl`, `sudo` are present
- [x] Confirms `amdgpu` and your configured CPU chip (`nct6797` by default)
      are visible in `/sys/class/hwmon`
- [x] Creates `.env` from `.env-template` (only if `.env` doesn't exist yet)
- [x] Validates config and hwmon resolution with a dry run before installing
- [x] Installs, enables, and (re)starts the `amd-gpu-fan-daemon` systemd unit

Re-running `./install.sh` is safe — it won't overwrite an existing `.env`,
and re-applies the unit file / enable / start idempotently.

## 🗑️ Uninstall

```bash
./uninstall.sh
```

- [x] Stops the service (its own `ExecStopPost` already reverts every fan
      header to hardware auto control as part of that stop)
- [x] Disables and removes the systemd unit
- [x] Explicitly re-reverts every configured header to
      `FAILSAFE_PWM_ENABLE` (5) as a second safety net, even if the service
      was already stopped or broken
- [x] Leaves `.env` and the cloned repo in place — delete the directory
      yourself if you want it fully gone

## ▶️ Usage

```bash
# One-shot: log computed targets without writing anything
python3 -m fan_daemon --dry-run

# Force every configured header back to hardware auto control
python3 -m fan_daemon --revert-to-auto

# Show which hwmon device path each configured chip resolved to
python3 -m fan_daemon --print-hwmon-paths

# Normal operation (this is what the systemd unit runs)
sudo systemctl status amd-gpu-fan-daemon
journalctl -u amd-gpu-fan-daemon -f
```

## ⚙️ Configuration

All runtime behavior lives in `.env` (created from `.env-template` on
first install) — no code change or rebuild needed, just
`sudo systemctl restart amd-gpu-fan-daemon` after editing.

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `2` | How often temps are sampled |
| `MIN_DWELL_SECONDS` | `8` | Minimum seconds between two writes to the same header |
| `TEMP_DEADBAND_C` | `2` | Minimum temp movement (°C) before re-evaluating a target |
| `PWM_STEP_THRESHOLD` | `3` | Minimum PWM-count change before a write happens |
| `EMA_ALPHA` | `0.3` | Smoothing factor for temp readings, in (0, 1] |
| `FAN_HEADERS` | `"2 4 7"` | Space-separated nct6797 PWM channel numbers to manage |
| `PWM_MIN` / `PWM_MAX` | `64` / `255` | Output clamp range (0-255 scale) |
| `CPU_CURVE` / `GPU_CURVE` | see `.env-template` | `temp_c:pwm` breakpoint pairs, ascending |
| `CPU_HWMON_NAME` / `GPU_HWMON_NAME` | `nct6797` / `amdgpu` | Chip names to resolve via `hwmon`'s `name` file |
| `CPU_TEMP_ATTR` / `GPU_TEMP_ATTR` | `temp7_input` / `temp2_input` | Which sysfs attribute holds each temp |
| `FAILSAFE_PWM_ENABLE` | `5` | `pwm*_enable` value written on any stop/crash |
| `HEARTBEAT_FILE` / `HEARTBEAT_STALE_SECONDS` | `/run/amd-gpu-fan-daemon/heartbeat` / `30` | Used by `healthcheck.sh` |

Find your own board's chip names and channel numbers with:

```bash
for f in /sys/class/hwmon/*/name; do echo "$f: $(cat "$f")"; done
sensors   # shows fanN RPM per populated header
```

## 🩺 Troubleshooting

- [ ] **Service won't start** — `journalctl -u amd-gpu-fan-daemon -e`
  first; usually a missing `.env` key or an unresolvable hwmon chip name.
- [ ] **Fans never ramp up under GPU load** — confirm
  `pwm*_enable` reads `1` (manual) for your configured headers, and that
  `GPU_TEMP_ATTR` on this board really is the junction sensor (`sensors`
  output labels it).
- [ ] **Fans stuck at a fixed speed** — check the service is actually
  active; a stopped/crashed daemon should have already reverted to
  `pwm*_enable=5`, not left a stale manual value. See
  [docs/runbook.md](docs/runbook.md).
- [ ] **`install.sh` dies on hwmon detection** — the `amdgpu` or
  `nct6775`-family kernel module likely isn't loaded; `lsmod | grep -e amdgpu -e nct6775`.
- [ ] Full step-by-step real-hardware verification: see
  [docs/runbook.md](docs/runbook.md).

## 🔒 Security notes

- The systemd unit runs `ExecStart`/`ExecStopPost` **as root** — raw sysfs
  PWM writes aren't gated by a discrete Linux capability, so there's no
  meaningful non-root alternative short of a persistent udev rule
  re-owning the exact `pwmN*` files (more moving parts, no real gain).
- Root is compensated with `ProtectSystem=strict` +
  `ReadWritePaths=/sys/class/hwmon` (write access confined to the hwmon
  class tree only — every other filesystem sandboxing directive systemd
  offers is also enabled; see `systemd/amd-gpu-fan-daemon.service.template`).
- `ProtectKernelTunables` is explicitly left **unset** — setting it to
  `yes` makes `/sys` read-only and breaks the PWM writes entirely (this is
  a known systemd/lm-sensors interaction, not an oversight).
- On any stop — clean, crashed, or killed — every configured header is
  reverted to hardware auto control (`pwm*_enable=5`) via `ExecStopPost`,
  so the failure mode of this daemon misbehaving is "case fans follow the
  BIOS's own CPU curve again," never "fans stuck low forever."
- No secrets, credentials, or network access are involved anywhere in this
  project — it only reads/writes local `hwmon` sysfs files.

### Known limitations

- Suspend/resume relies on the control loop's self-heal step (re-asserting
  `pwm*_enable=1` if the chip reset it), not a dedicated `systemd-sleep`
  hook — recovery happens within one `POLL_INTERVAL_SECONDS` after resume,
  not instantly.
- A genuinely hung sysfs write is caught by the systemd watchdog
  (`WatchdogSec=30`), not a per-write timeout — worst case a header can
  sit at a stale PWM value for up to 30s before the daemon is restarted.

## 📚 Documentation

- [docs/runbook.md](docs/runbook.md) — real-hardware smoke test, log
  reading, curve tuning, day-2 operations.

## License

[Apache License 2.0](LICENSE)
