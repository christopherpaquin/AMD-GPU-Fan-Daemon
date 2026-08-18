"""Dynamic hwmon device resolution and sysfs attribute I/O.

hwmon device numbers (``hwmon0``, ``hwmon1``, ...) are assigned by kernel
enumeration order and are not stable across reboots or module reloads. Every
lookup here resolves the current path by matching the device's ``name`` file
rather than trusting a cached/hardcoded number.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

HWMON_ROOT = Path("/sys/class/hwmon")


class HwmonNotFoundError(RuntimeError):
    """Raised when no hwmon device matches the requested chip name."""


def resolve_hwmon_path(chip_name: str, root: Path = HWMON_ROOT) -> Path:
    """Return the hwmon directory whose ``name`` file equals *chip_name*.

    Raises HwmonNotFoundError if zero or more than one device matches -
    an ambiguous match is treated as a configuration error rather than
    silently picking one, since writing to the wrong chip is a hardware-
    safety-relevant mistake.
    """
    matches = []
    if root.is_dir():
        for candidate in sorted(root.iterdir()):
            name_file = candidate / "name"
            try:
                name = name_file.read_text().strip()
            except OSError:
                continue
            if name == chip_name:
                matches.append(candidate)

    if not matches:
        raise HwmonNotFoundError(f"no hwmon device found with name '{chip_name}' under {root}")
    if len(matches) > 1:
        raise HwmonNotFoundError(
            f"multiple hwmon devices found with name '{chip_name}' under "
            f"{root}: {[str(m) for m in matches]} - refusing to guess"
        )
    return matches[0]


def read_attr(hwmon_path: Path, attr: str) -> int:
    """Read an integer-valued hwmon attribute file (e.g. temp2_input)."""
    return int((hwmon_path / attr).read_text().strip())


def write_attr(hwmon_path: Path, attr: str, value: int) -> None:
    """Write an integer value to a hwmon attribute file."""
    (hwmon_path / attr).write_text(str(value))
