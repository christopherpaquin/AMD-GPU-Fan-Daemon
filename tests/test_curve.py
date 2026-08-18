import pytest

from fan_daemon.curve import Ema, FanGate, clamp, interpolate, parse_curve


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


# --- parse_curve ---


def test_parse_curve_valid():
    assert parse_curve("40:64 55:115 70:191") == [(40.0, 64), (55.0, 115), (70.0, 191)]


def test_parse_curve_rejects_malformed_pair():
    with pytest.raises(ValueError, match="malformed curve breakpoint"):
        parse_curve("40-64 55:115")


def test_parse_curve_rejects_non_ascending():
    with pytest.raises(ValueError, match="strictly ascending"):
        parse_curve("55:115 40:64")


def test_parse_curve_rejects_equal_temps():
    with pytest.raises(ValueError, match="strictly ascending"):
        parse_curve("40:64 40:115")


def test_parse_curve_rejects_single_point():
    with pytest.raises(ValueError, match="at least 2 breakpoints"):
        parse_curve("40:64")


# --- interpolate ---


def test_interpolate_below_range_clamps_flat():
    curve = parse_curve("40:64 90:255")
    assert interpolate(curve, 10) == 64


def test_interpolate_above_range_clamps_flat():
    curve = parse_curve("40:64 90:255")
    assert interpolate(curve, 200) == 255


def test_interpolate_at_breakpoint():
    curve = parse_curve("40:64 90:255")
    assert interpolate(curve, 40) == 64
    assert interpolate(curve, 90) == 255


def test_interpolate_midpoint_linear():
    curve = parse_curve("40:100 60:200")
    assert interpolate(curve, 50) == 150


def test_interpolate_multi_segment_picks_correct_segment():
    curve = parse_curve("40:64 55:115 70:191 85:255")
    assert interpolate(curve, 60) == round(115 + (191 - 115) * (60 - 55) / (70 - 55))


# --- clamp ---


def test_clamp_within_range():
    assert clamp(100, 0, 255) == 100


def test_clamp_below_low():
    assert clamp(-10, 0, 255) == 0


def test_clamp_above_high():
    assert clamp(300, 0, 255) == 255


# --- Ema ---


def test_ema_first_sample_is_returned_as_is():
    ema = Ema(alpha=0.3)
    assert ema.update(50.0) == 50.0


def test_ema_smooths_towards_new_sample():
    ema = Ema(alpha=0.5)
    ema.update(40.0)
    result = ema.update(60.0)
    assert result == pytest.approx(50.0)


# --- FanGate ---


def test_gate_always_writes_first_sample():
    clock = FakeClock()
    gate = FanGate(temp_deadband_c=2, pwm_step_threshold=3, min_dwell_seconds=8, now_fn=clock)

    assert gate.should_write(driving_temp=50.0, target_pwm=150) is True


def test_gate_blocks_within_deadband_and_dwell():
    clock = FakeClock()
    gate = FanGate(temp_deadband_c=2, pwm_step_threshold=3, min_dwell_seconds=8, now_fn=clock)
    gate.should_write(50.0, 150)

    clock.advance(1)
    assert gate.should_write(51.0, 160) is False


def test_gate_blocks_pwm_change_below_step_threshold_even_after_dwell():
    clock = FakeClock()
    gate = FanGate(temp_deadband_c=2, pwm_step_threshold=3, min_dwell_seconds=8, now_fn=clock)
    gate.should_write(50.0, 150)

    clock.advance(10)
    assert gate.should_write(53.0, 151) is False


def test_gate_allows_write_after_deadband_and_dwell_and_step_satisfied():
    clock = FakeClock()
    gate = FanGate(temp_deadband_c=2, pwm_step_threshold=3, min_dwell_seconds=8, now_fn=clock)
    gate.should_write(50.0, 150)

    clock.advance(10)
    assert gate.should_write(55.0, 180) is True


def test_gate_blocks_rapid_oscillation_around_a_threshold():
    """An input flapping around a curve breakpoint must not chatter the fan."""
    clock = FakeClock()
    gate = FanGate(temp_deadband_c=2, pwm_step_threshold=3, min_dwell_seconds=8, now_fn=clock)
    gate.should_write(50.0, 150)

    writes = 0
    for i in range(20):
        clock.advance(1)
        temp = 50.0 + (2.5 if i % 2 == 0 else -2.5)
        if gate.should_write(temp, 150 + (30 if i % 2 == 0 else -30)):
            writes += 1

    assert writes <= 3
