"""CLI entry point: normal run, --dry-run, --revert-to-auto, --print-hwmon-paths."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fan_daemon import daemon, hwmon
from fan_daemon.config import Config, ConfigError, load_config
from fan_daemon.curve import Ema, interpolate


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fan_daemon",
        description="GPU-aware motherboard fan control daemon.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path.cwd() / ".env",
        help="Path to the .env config file (default: ./.env in the working directory)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Log computed PWM targets once without writing anything, then exit.",
    )
    mode.add_argument(
        "--revert-to-auto",
        action="store_true",
        help="Write the failsafe pwm_enable value to every configured header, then exit.",
    )
    mode.add_argument(
        "--print-hwmon-paths",
        action="store_true",
        help="Resolve and print the CPU/GPU hwmon paths, then exit.",
    )
    return parser.parse_args(argv)


def _load_config_or_die(env_file: Path) -> Config:
    try:
        return load_config(env_file)
    except ConfigError as exc:
        print(f"fan_daemon: configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config = _load_config_or_die(args.env_file)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.print_hwmon_paths:
        cpu_path = hwmon.resolve_hwmon_path(config.cpu_hwmon_name)
        gpu_path = hwmon.resolve_hwmon_path(config.gpu_hwmon_name)
        print(f"CPU ({config.cpu_hwmon_name}): {cpu_path}")
        print(f"GPU ({config.gpu_hwmon_name}): {gpu_path}")
        return 0

    io = daemon.build_io(config)

    if args.revert_to_auto:
        daemon.revert_to_auto(config, io)
        return 0

    if args.dry_run:
        cpu_temp = io.read_cpu_temp() / 1000.0
        gpu_temp = io.read_gpu_temp() / 1000.0
        cpu_pwm = interpolate(config.cpu_curve, Ema(alpha=1.0).update(cpu_temp))
        gpu_pwm = interpolate(config.gpu_curve, Ema(alpha=1.0).update(gpu_temp))
        target = max(cpu_pwm, gpu_pwm)
        print(f"CPU temp: {cpu_temp:.1f}C -> curve {cpu_pwm}")
        print(f"GPU temp: {gpu_temp:.1f}C -> curve {gpu_pwm}")
        print(f"Target PWM for headers {list(config.fan_headers)}: {target}")
        return 0

    daemon.run_forever(config, io)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
