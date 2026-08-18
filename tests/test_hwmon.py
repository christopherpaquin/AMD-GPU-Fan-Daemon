from pathlib import Path

import pytest

from fan_daemon import hwmon


def make_hwmon_device(
    root: Path, dev_dir: str, name: str, attrs: dict[str, str] | None = None
) -> Path:
    device = root / dev_dir
    device.mkdir(parents=True)
    (device / "name").write_text(name + "\n")
    for attr, value in (attrs or {}).items():
        (device / attr).write_text(value)
    return device


def test_resolves_by_name_among_decoys(tmp_path):
    make_hwmon_device(tmp_path, "hwmon0", "acpitz")
    target = make_hwmon_device(tmp_path, "hwmon3", "amdgpu")
    make_hwmon_device(tmp_path, "hwmon5", "coretemp")

    resolved = hwmon.resolve_hwmon_path("amdgpu", root=tmp_path)

    assert resolved == target


def test_raises_when_no_match(tmp_path):
    make_hwmon_device(tmp_path, "hwmon0", "acpitz")

    with pytest.raises(hwmon.HwmonNotFoundError, match="no hwmon device"):
        hwmon.resolve_hwmon_path("amdgpu", root=tmp_path)


def test_raises_on_missing_root(tmp_path):
    missing = tmp_path / "does-not-exist"

    with pytest.raises(hwmon.HwmonNotFoundError):
        hwmon.resolve_hwmon_path("amdgpu", root=missing)


def test_raises_on_ambiguous_match(tmp_path):
    make_hwmon_device(tmp_path, "hwmon3", "amdgpu")
    make_hwmon_device(tmp_path, "hwmon7", "amdgpu")

    with pytest.raises(hwmon.HwmonNotFoundError, match="multiple hwmon devices"):
        hwmon.resolve_hwmon_path("amdgpu", root=tmp_path)


def test_read_attr_parses_int(tmp_path):
    device = make_hwmon_device(tmp_path, "hwmon3", "amdgpu", {"temp2_input": "47000\n"})

    assert hwmon.read_attr(device, "temp2_input") == 47000


def test_write_attr_writes_value(tmp_path):
    device = make_hwmon_device(tmp_path, "hwmon4", "nct6797", {"pwm2": "153"})

    hwmon.write_attr(device, "pwm2", 200)

    assert (device / "pwm2").read_text() == "200"
