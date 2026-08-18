"""Parse and validate the daemon's .env configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fan_daemon.curve import parse_curve


class ConfigError(ValueError):
    """Raised for missing, malformed, or out-of-range configuration."""


REQUIRED_KEYS = (
    "POLL_INTERVAL_SECONDS",
    "MIN_DWELL_SECONDS",
    "TEMP_DEADBAND_C",
    "PWM_STEP_THRESHOLD",
    "EMA_ALPHA",
    "FAN_HEADERS",
    "PWM_MIN",
    "PWM_MAX",
    "CPU_CURVE",
    "GPU_CURVE",
    "CPU_HWMON_NAME",
    "GPU_HWMON_NAME",
    "CPU_TEMP_ATTR",
    "GPU_TEMP_ATTR",
    "FAILSAFE_PWM_ENABLE",
    "HEARTBEAT_FILE",
    "HEARTBEAT_STALE_SECONDS",
)


@dataclass(frozen=True)
class Config:
    poll_interval_seconds: float
    min_dwell_seconds: float
    temp_deadband_c: float
    pwm_step_threshold: int
    ema_alpha: float
    fan_headers: tuple[int, ...]
    pwm_min: int
    pwm_max: int
    cpu_curve: list[tuple[float, int]]
    gpu_curve: list[tuple[float, int]]
    cpu_hwmon_name: str
    gpu_hwmon_name: str
    cpu_temp_attr: str
    gpu_temp_attr: str
    failsafe_pwm_enable: int
    heartbeat_file: Path
    heartbeat_stale_seconds: float
    log_level: str = "INFO"


def parse_dotenv(text: str) -> dict[str, str]:
    """Minimal KEY=VALUE parser - no interpolation, no export keyword.

    Supports optional single/double quoting and '#' comments on their own
    line or trailing after a value. Deliberately simple: this project's
    .env only ever holds plain scalars, not shell expressions.
    """
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"malformed .env line (no '='): '{raw_line}'")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value[:1] in ('"', "'"):
            quote = value[0]
            end = value.find(quote, 1)
            if end == -1:
                raise ConfigError(f"unterminated quote in .env line: '{raw_line}'")
            value = value[1:end]
        elif "#" in value:
            value = value.split("#", 1)[0].strip()
        values[key] = value
    return values


def load_config(env_path: Path) -> Config:
    """Load and validate configuration from an .env-style file.

    Fails loudly with a specific message identifying the missing or
    invalid key, rather than proceeding with a partial/default config -
    silent defaults on a hardware-control daemon are a correctness risk.
    """
    if not env_path.is_file():
        raise ConfigError(f".env file not found: {env_path}")

    raw = parse_dotenv(env_path.read_text())

    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise ConfigError(f"missing required config key(s): {', '.join(missing)}")

    try:
        fan_headers = tuple(int(n) for n in raw["FAN_HEADERS"].split())
        if not fan_headers:
            raise ConfigError("FAN_HEADERS must list at least one header number")

        pwm_min = int(raw["PWM_MIN"])
        pwm_max = int(raw["PWM_MAX"])
        if not (0 <= pwm_min <= pwm_max <= 255):
            raise ConfigError(
                f"PWM_MIN/PWM_MAX must satisfy 0 <= PWM_MIN <= PWM_MAX <= 255, "
                f"got PWM_MIN={pwm_min} PWM_MAX={pwm_max}"
            )

        cpu_curve = parse_curve(raw["CPU_CURVE"])
        gpu_curve = parse_curve(raw["GPU_CURVE"])

        poll_interval_seconds = float(raw["POLL_INTERVAL_SECONDS"])
        min_dwell_seconds = float(raw["MIN_DWELL_SECONDS"])
        temp_deadband_c = float(raw["TEMP_DEADBAND_C"])
        pwm_step_threshold = int(raw["PWM_STEP_THRESHOLD"])
        ema_alpha = float(raw["EMA_ALPHA"])
        if not (0.0 < ema_alpha <= 1.0):
            raise ConfigError(f"EMA_ALPHA must be in (0, 1], got {ema_alpha}")
        if poll_interval_seconds <= 0:
            raise ConfigError(
                f"POLL_INTERVAL_SECONDS must be positive, got {poll_interval_seconds}"
            )

        failsafe_pwm_enable = int(raw["FAILSAFE_PWM_ENABLE"])
        heartbeat_stale_seconds = float(raw["HEARTBEAT_STALE_SECONDS"])
    except ValueError as exc:
        raise ConfigError(f"invalid config value: {exc}") from exc

    return Config(
        poll_interval_seconds=poll_interval_seconds,
        min_dwell_seconds=min_dwell_seconds,
        temp_deadband_c=temp_deadband_c,
        pwm_step_threshold=pwm_step_threshold,
        ema_alpha=ema_alpha,
        fan_headers=fan_headers,
        pwm_min=pwm_min,
        pwm_max=pwm_max,
        cpu_curve=cpu_curve,
        gpu_curve=gpu_curve,
        cpu_hwmon_name=raw["CPU_HWMON_NAME"],
        gpu_hwmon_name=raw["GPU_HWMON_NAME"],
        cpu_temp_attr=raw["CPU_TEMP_ATTR"],
        gpu_temp_attr=raw["GPU_TEMP_ATTR"],
        failsafe_pwm_enable=failsafe_pwm_enable,
        heartbeat_file=Path(raw["HEARTBEAT_FILE"]),
        heartbeat_stale_seconds=heartbeat_stale_seconds,
        log_level=raw.get("LOG_LEVEL", "INFO"),
    )
