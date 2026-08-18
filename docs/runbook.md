# Runbook — AMD-GPU-Fan-Daemon

Operational reference for anyone (including future-you) running this
unattended. See `README.md` for install/uninstall/config; this is about
day-2 operation and the real-hardware verification steps CI can't run.

## Real-machine smoke test (do this after any change, on the target box)

Run every step below, in order, before trusting the daemon on a machine you
care about. None of this runs in CI — CI only proves the pure logic (curve
math, config parsing, revert-to-auto) is correct against fakes.

1. **Dry run first.** `python3 -m fan_daemon --dry-run` and compare the
   printed target PWM against what `sensors | grep -A2 nct6797` currently
   shows for `fanN` RPM - sanity-check before trusting a real write.

2. **Start and confirm manual mode.**

   ```bash
   sudo ./install.sh
   for h in 2 4 7; do cat /sys/class/hwmon/hwmon*/pwm${h}_enable; done  # expect 1
   ```

3. **Load the GPU independent of the CPU** (e.g. a GPU compute/graphics
   stress tool while the CPU stays idle) and confirm `fanN_input` RPM rises
   - this is the actual feature working, not just the service being up.

4. **Clean stop reverts control.**

   ```bash
   sudo systemctl stop amd-gpu-fan-daemon
   for h in 2 4 7; do cat /sys/class/hwmon/hwmon*/pwm${h}_enable; done  # expect 5
   sensors  # BIOS curve should be visibly responding to CPU temp again
   sudo systemctl start amd-gpu-fan-daemon
   ```

5. **Crash recovery.**

   ```bash
   sudo systemctl kill -s SIGKILL amd-gpu-fan-daemon
   sleep 6
   systemctl is-active amd-gpu-fan-daemon  # expect active (Restart=on-failure)
   ```

6. **Healthcheck in both states.**

   ```bash
   ./healthcheck.sh; echo "exit: $?"           # expect OK / 0
   sudo systemctl stop amd-gpu-fan-daemon
   ./healthcheck.sh; echo "exit: $?"           # expect UNHEALTHY / 1
   sudo systemctl start amd-gpu-fan-daemon
   ```

7. **Suspend/resume**, if the machine ever suspends: after resume, confirm
   `pwm*_enable` returns to `1` within one `POLL_INTERVAL_SECONDS` (the
   daemon's self-heal step, not a dedicated sleep hook - see README
   "Known limitations").

## Reading logs

```bash
journalctl -u amd-gpu-fan-daemon -f          # live tail
journalctl -u amd-gpu-fan-daemon --since today
```

## Tuning the curves

Edit `CPU_CURVE` / `GPU_CURVE` in `.env` (format: ascending
`temp_c:pwm` pairs, linear interpolation between points, clamped flat
outside the range), then `sudo systemctl restart amd-gpu-fan-daemon`. No
code change or rebuild needed.

## If something looks wrong

See README.md "Troubleshooting" first. If fans seem stuck at a fixed
speed regardless of temp, check `pwm*_enable` is `1` (self-heal should
correct this within one poll interval if the chip reset it) and that the
service is actually active - a stopped/crashed service should have already
reverted to `5` via `ExecStopPost`, not left fans stuck manual.
