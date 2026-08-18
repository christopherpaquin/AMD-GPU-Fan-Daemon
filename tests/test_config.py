from pathlib import Path

import pytest

from fan_daemon.config import ConfigError, load_config, parse_dotenv

VALID_ENV = """
POLL_INTERVAL_SECONDS=2
MIN_DWELL_SECONDS=8
TEMP_DEADBAND_C=2
PWM_STEP_THRESHOLD=3
EMA_ALPHA=0.3

FAN_HEADERS="2 4 7"
PWM_MIN=64
PWM_MAX=255

CPU_CURVE="40:64 55:115 70:191 85:255"
GPU_CURVE="45:64 65:102 80:179 90:230 95:255"

CPU_HWMON_NAME=nct6797
GPU_HWMON_NAME=amdgpu
CPU_TEMP_ATTR=temp7_input
GPU_TEMP_ATTR=temp2_input

FAILSAFE_PWM_ENABLE=5
HEARTBEAT_FILE=/run/amd-gpu-fan-daemon/heartbeat
HEARTBEAT_STALE_SECONDS=30
LOG_LEVEL=INFO
"""


def write_env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text)
    return path


# --- parse_dotenv ---


def test_parse_dotenv_strips_quotes_and_comments():
    parsed = parse_dotenv('FOO="bar" # a comment\nBAZ=qux\n# full line comment\n')
    assert parsed == {"FOO": "bar", "BAZ": "qux"}


def test_parse_dotenv_rejects_line_without_equals():
    with pytest.raises(ConfigError, match="no '='"):
        parse_dotenv("NOT_A_VAR\n")


# --- load_config ---


def test_load_config_valid(tmp_path):
    config = load_config(write_env(tmp_path, VALID_ENV))

    assert config.fan_headers == (2, 4, 7)
    assert config.pwm_min == 64
    assert config.pwm_max == 255
    assert config.cpu_curve[0] == (40.0, 64)
    assert config.gpu_hwmon_name == "amdgpu"
    assert config.heartbeat_file == Path("/run/amd-gpu-fan-daemon/heartbeat")


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does-not-exist.env")


def test_load_config_missing_required_key(tmp_path):
    broken = VALID_ENV.replace('FAN_HEADERS="2 4 7"\n', "")
    with pytest.raises(ConfigError, match="FAN_HEADERS"):
        load_config(write_env(tmp_path, broken))


def test_load_config_rejects_pwm_min_above_max(tmp_path):
    broken = VALID_ENV.replace("PWM_MAX=255", "PWM_MAX=50")
    with pytest.raises(ConfigError, match="PWM_MIN"):
        load_config(write_env(tmp_path, broken))


def test_load_config_rejects_pwm_out_of_byte_range(tmp_path):
    broken = VALID_ENV.replace("PWM_MAX=255", "PWM_MAX=300")
    with pytest.raises(ConfigError, match="PWM_MIN"):
        load_config(write_env(tmp_path, broken))


def test_load_config_rejects_bad_ema_alpha(tmp_path):
    broken = VALID_ENV.replace("EMA_ALPHA=0.3", "EMA_ALPHA=1.5")
    with pytest.raises(ConfigError, match="EMA_ALPHA"):
        load_config(write_env(tmp_path, broken))


def test_load_config_rejects_nonpositive_poll_interval(tmp_path):
    broken = VALID_ENV.replace("POLL_INTERVAL_SECONDS=2", "POLL_INTERVAL_SECONDS=0")
    with pytest.raises(ConfigError, match="POLL_INTERVAL_SECONDS"):
        load_config(write_env(tmp_path, broken))


def test_load_config_rejects_malformed_curve(tmp_path):
    broken = VALID_ENV.replace('CPU_CURVE="40:64 55:115 70:191 85:255"', 'CPU_CURVE="not-a-curve"')
    with pytest.raises(ConfigError, match="invalid config value"):
        load_config(write_env(tmp_path, broken))


def test_load_config_rejects_empty_fan_headers(tmp_path):
    broken = VALID_ENV.replace('FAN_HEADERS="2 4 7"', 'FAN_HEADERS=""')
    with pytest.raises(ConfigError, match="FAN_HEADERS"):
        load_config(write_env(tmp_path, broken))
