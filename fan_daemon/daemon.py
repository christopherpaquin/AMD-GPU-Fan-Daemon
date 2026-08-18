"""Main control loop: read temps, compute PWM targets, write, self-heal."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fan_daemon import hwmon, sdnotify
from fan_daemon.config import Config
from fan_daemon.curve import Ema, FanGate, clamp, interpolate

logger = logging.getLogger(__name__)

PWM_ENABLE_MANUAL = 1

# Injected I/O so the loop is testable without a real /sys tree.
ReadFn = Callable[[str], int]
WriteFn = Callable[[str, int], None]


@dataclass
class Io:
    """Bound read/write callables plus resolved hwmon paths for one run."""

    read_cpu_temp: ReadFn
    read_gpu_temp: ReadFn
    read_pwm_enable: Callable[[int], int]
    write_pwm: Callable[[int, int], None]
    write_pwm_enable: Callable[[int, int], None]


def build_io(config: Config) -> Io:
    """Resolve real hwmon paths and bind real sysfs read/write callables."""
    cpu_path = hwmon.resolve_hwmon_path(config.cpu_hwmon_name)
    gpu_path = hwmon.resolve_hwmon_path(config.gpu_hwmon_name)

    def read_cpu_temp() -> int:
        return hwmon.read_attr(cpu_path, config.cpu_temp_attr)

    def read_gpu_temp() -> int:
        return hwmon.read_attr(gpu_path, config.gpu_temp_attr)

    def read_pwm_enable(header: int) -> int:
        return hwmon.read_attr(cpu_path, f"pwm{header}_enable")

    def write_pwm(header: int, value: int) -> None:
        hwmon.write_attr(cpu_path, f"pwm{header}", value)

    def write_pwm_enable(header: int, value: int) -> None:
        hwmon.write_attr(cpu_path, f"pwm{header}_enable", value)

    return Io(
        read_cpu_temp=read_cpu_temp,
        read_gpu_temp=read_gpu_temp,
        read_pwm_enable=read_pwm_enable,
        write_pwm=write_pwm,
        write_pwm_enable=write_pwm_enable,
    )


def revert_to_auto(config: Config, io: Io) -> None:
    """Hand every configured header back to hardware/BIOS auto control.

    Best-effort across headers: one header's write failing (missing path,
    permission error, chip in a bad state) must not prevent reverting the
    others - this is the daemon's ultimate safety fallback and a partial
    failure here would be worse than a logged-and-continued one.
    """
    for header in config.fan_headers:
        try:
            io.write_pwm_enable(header, config.failsafe_pwm_enable)
            logger.info("reverted pwm%d_enable to %d (auto)", header, config.failsafe_pwm_enable)
        except OSError:
            logger.exception("failed to revert pwm%d_enable to auto", header)


@dataclass
class LoopState:
    cpu_ema: Ema
    gpu_ema: Ema
    gates: dict[int, FanGate]


def build_loop_state(config: Config, now_fn: Callable[[], float] | None = None) -> LoopState:
    gates = {
        header: FanGate(
            temp_deadband_c=config.temp_deadband_c,
            pwm_step_threshold=config.pwm_step_threshold,
            min_dwell_seconds=config.min_dwell_seconds,
            now_fn=now_fn,
        )
        for header in config.fan_headers
    }
    return LoopState(
        cpu_ema=Ema(alpha=config.ema_alpha),
        gpu_ema=Ema(alpha=config.ema_alpha),
        gates=gates,
    )


def run_iteration(config: Config, io: Io, state: LoopState) -> dict[int, int]:
    """Run one control-loop pass. Returns headers actually written this pass."""
    try:
        cpu_temp_c = io.read_cpu_temp() / 1000.0
        cpu_ema = state.cpu_ema.update(cpu_temp_c)
    except OSError:
        logger.warning("failed to read CPU temp; holding last known value", exc_info=True)
        cpu_ema = state.cpu_ema.value

    try:
        gpu_temp_c = io.read_gpu_temp() / 1000.0
        gpu_ema = state.gpu_ema.update(gpu_temp_c)
    except OSError:
        logger.warning("failed to read GPU temp; holding last known value", exc_info=True)
        gpu_ema = state.gpu_ema.value

    if cpu_ema is None or gpu_ema is None:
        logger.warning("no temperature reading available yet; skipping this iteration")
        return {}

    cpu_pwm = interpolate(config.cpu_curve, cpu_ema)
    gpu_pwm = interpolate(config.gpu_curve, gpu_ema)
    driving_temp = max(cpu_ema, gpu_ema)
    target = clamp(max(cpu_pwm, gpu_pwm), config.pwm_min, config.pwm_max)

    written = {}
    for header in config.fan_headers:
        # Self-heal must run before the pwm write, not after: the chip
        # rejects direct pwm writes with EBUSY while pwm*_enable is still
        # in an auto mode (e.g. right after install, before the first
        # manual-mode write lands) - writing the value first and fixing
        # the mode second guarantees that race on every fresh start.
        try:
            if io.read_pwm_enable(header) != PWM_ENABLE_MANUAL:
                io.write_pwm_enable(header, PWM_ENABLE_MANUAL)
                logger.info("self-heal: re-asserted pwm%d_enable=manual", header)
        except OSError:
            logger.exception("failed to self-heal pwm%d_enable", header)

        gate = state.gates[header]
        if gate.should_write(driving_temp, target):
            try:
                io.write_pwm(header, target)
                written[header] = target
            except OSError:
                logger.exception("failed to write pwm%d", header)

    return written


class ShutdownRequested(Exception):
    """Raised from the loop when a termination signal has been received."""


def make_signal_handler(flag: dict) -> Callable[[int, object], None]:
    def _handler(signum: int, _frame: object) -> None:
        flag["shutdown"] = True

    return _handler


def run_loop(
    config: Config,
    io: Io,
    shutdown_flag: dict,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Run iterations until shutdown_flag["shutdown"] is set, then revert.

    Split out from run_forever so tests can drive the shutdown/revert path
    deterministically (mutate shutdown_flag, inject a fake sleep_fn) without
    needing real OS signals or threads.
    """
    state = build_loop_state(config)
    sdnotify.notify("READY=1")
    logger.info("daemon started; managing headers %s", config.fan_headers)

    try:
        while not shutdown_flag["shutdown"]:
            run_iteration(config, io, state)
            _touch_heartbeat(config.heartbeat_file)
            sdnotify.notify("WATCHDOG=1")
            sleep_fn(config.poll_interval_seconds)
    finally:
        logger.info("shutting down; reverting all headers to auto")
        sdnotify.notify("STOPPING=1")
        revert_to_auto(config, io)


def run_forever(config: Config, io: Io) -> None:
    """Run the control loop until a shutdown signal is received."""
    shutdown_flag = {"shutdown": False}
    handler = make_signal_handler(shutdown_flag)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    run_loop(config, io, shutdown_flag)


def _touch_heartbeat(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()))
    except OSError:
        logger.exception("failed to write heartbeat file %s", path)
