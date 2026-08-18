"""Piecewise-linear temp->PWM curves, smoothing, dead-band, and rate limiting."""

from __future__ import annotations

from dataclasses import dataclass, field


def parse_curve(spec: str) -> list[tuple[float, int]]:
    """Parse a "temp:pwm temp:pwm ..." string into ascending breakpoints.

    Raises ValueError on malformed input or non-ascending temperatures -
    a curve that isn't sorted would make interpolation ambiguous.
    """
    points: list[tuple[float, int]] = []
    for pair in spec.split():
        try:
            temp_str, pwm_str = pair.split(":")
            temp, pwm = float(temp_str), int(pwm_str)
        except ValueError as exc:
            raise ValueError(f"malformed curve breakpoint '{pair}' in '{spec}'") from exc
        if points and temp <= points[-1][0]:
            raise ValueError(
                f"curve breakpoints must be strictly ascending by temperature: " f"'{spec}'"
            )
        points.append((temp, pwm))
    if len(points) < 2:
        raise ValueError(f"curve needs at least 2 breakpoints: '{spec}'")
    return points


def interpolate(curve: list[tuple[float, int]], temp_c: float) -> int:
    """Linear interpolation over curve breakpoints, clamped flat at the ends."""
    if temp_c <= curve[0][0]:
        return curve[0][1]
    if temp_c >= curve[-1][0]:
        return curve[-1][1]
    for (t0, p0), (t1, p1) in zip(curve, curve[1:]):
        if t0 <= temp_c <= t1:
            fraction = (temp_c - t0) / (t1 - t0)
            return round(p0 + fraction * (p1 - p0))
    raise AssertionError("unreachable: temp_c not covered by curve range")


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass
class Ema:
    """Exponential moving average smoother for a single temperature stream."""

    alpha: float
    value: float | None = None

    def update(self, sample: float) -> float:
        if self.value is None:
            self.value = sample
        else:
            self.value = self.alpha * sample + (1 - self.alpha) * self.value
        return self.value


@dataclass
class FanGate:
    """Dead-band + rate-limit gate for one PWM output channel.

    Re-evaluating a curve on every noisy sample and writing every result
    would make fans audibly hunt. This gate holds back a new target until
    the driving temperature has moved meaningfully (dead-band) and enough
    time has passed since the last actual write (rate limit).
    """

    temp_deadband_c: float
    pwm_step_threshold: int
    min_dwell_seconds: float
    now_fn: callable = field(default=None, repr=False)

    _last_eval_temp: float | None = field(default=None, init=False, repr=False)
    _last_applied_pwm: int | None = field(default=None, init=False, repr=False)
    _last_write_time: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.now_fn is None:
            import time

            self.now_fn = time.monotonic

    def should_write(self, driving_temp: float, target_pwm: int) -> bool:
        """Return True (and record state) if target_pwm should be applied now."""
        now = self.now_fn()

        if self._last_applied_pwm is None:
            self._record(driving_temp, target_pwm, now)
            return True

        temp_moved = (
            self._last_eval_temp is None
            or abs(driving_temp - self._last_eval_temp) >= self.temp_deadband_c
        )
        if not temp_moved:
            return False

        pwm_changed = abs(target_pwm - self._last_applied_pwm) >= self.pwm_step_threshold
        dwell_elapsed = (
            self._last_write_time is None or (now - self._last_write_time) >= self.min_dwell_seconds
        )

        if pwm_changed and dwell_elapsed:
            self._record(driving_temp, target_pwm, now)
            return True

        # Temp moved enough to re-evaluate but the write itself is gated -
        # still remember the eval point so we don't re-trigger on every
        # sub-deadband wobble around this new position.
        self._last_eval_temp = driving_temp
        return False

    def _record(self, driving_temp: float, pwm: int, now: float) -> None:
        self._last_eval_temp = driving_temp
        self._last_applied_pwm = pwm
        self._last_write_time = now
