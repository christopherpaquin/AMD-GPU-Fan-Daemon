from pathlib import Path

import pytest

from fan_daemon.config import Config


def _make_config(fan_headers=(2, 4, 7)) -> Config:
    return Config(
        poll_interval_seconds=2,
        min_dwell_seconds=8,
        temp_deadband_c=2,
        pwm_step_threshold=3,
        ema_alpha=0.3,
        fan_headers=fan_headers,
        pwm_min=64,
        pwm_max=255,
        cpu_curve=[(40.0, 64), (85.0, 255)],
        gpu_curve=[(45.0, 64), (95.0, 255)],
        cpu_hwmon_name="nct6797",
        gpu_hwmon_name="amdgpu",
        cpu_temp_attr="temp7_input",
        gpu_temp_attr="temp2_input",
        failsafe_pwm_enable=5,
        heartbeat_file=Path("/run/amd-gpu-fan-daemon/heartbeat"),
        heartbeat_stale_seconds=30,
    )


@pytest.fixture
def make_config():
    return _make_config
