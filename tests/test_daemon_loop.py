import dataclasses

from fan_daemon.daemon import (
    Io,
    build_loop_state,
    make_signal_handler,
    run_iteration,
    run_loop,
)


class FakeSensors:
    """Scriptable fake sysfs: temps come from a sequence, pwm/enable are recorded."""

    def __init__(
        self,
        cpu_temps_c: list[float],
        gpu_temps_c: list[float],
        simulate_busy_until_manual: bool = False,
    ):
        self._cpu_temps = iter(cpu_temps_c)
        self._gpu_temps = iter(gpu_temps_c)
        self.pwm_writes: list[tuple[int, int]] = []
        self.pwm_enable: dict[int, int] = {}
        self.simulate_busy_until_manual = simulate_busy_until_manual

    def read_cpu_temp(self) -> int:
        return int(next(self._cpu_temps) * 1000)

    def read_gpu_temp(self) -> int:
        return int(next(self._gpu_temps) * 1000)

    def read_pwm_enable(self, header: int) -> int:
        return self.pwm_enable.get(header, 1)

    def write_pwm(self, header: int, value: int) -> None:
        # Real nct6775 hardware rejects a direct pwm write with EBUSY while
        # pwm*_enable is still in an auto mode - mirrors that here so tests
        # can catch a write-before-self-heal ordering regression.
        if self.simulate_busy_until_manual and self.pwm_enable.get(header) != 1:
            raise OSError(16, "Device or resource busy")
        self.pwm_writes.append((header, value))

    def write_pwm_enable(self, header: int, value: int) -> None:
        self.pwm_enable[header] = value

    def io(self) -> Io:
        return Io(
            read_cpu_temp=self.read_cpu_temp,
            read_gpu_temp=self.read_gpu_temp,
            read_pwm_enable=self.read_pwm_enable,
            write_pwm=self.write_pwm,
            write_pwm_enable=self.write_pwm_enable,
        )


def test_run_iteration_writes_gpu_driven_target_when_gpu_hotter(make_config):
    config = make_config(fan_headers=(2,))
    sensors = FakeSensors(cpu_temps_c=[40.0], gpu_temps_c=[95.0])
    state = build_loop_state(config)

    written = run_iteration(config, sensors.io(), state)

    assert written == {2: 255}
    assert sensors.pwm_writes == [(2, 255)]


def test_run_iteration_writes_cpu_driven_target_when_cpu_hotter(make_config):
    config = make_config(fan_headers=(2,))
    sensors = FakeSensors(cpu_temps_c=[85.0], gpu_temps_c=[45.0])
    state = build_loop_state(config)

    written = run_iteration(config, sensors.io(), state)

    assert written == {2: 255}


def test_run_iteration_self_heals_pwm_enable(make_config):
    config = make_config(fan_headers=(2, 4))
    sensors = FakeSensors(cpu_temps_c=[40.0], gpu_temps_c=[45.0])
    sensors.pwm_enable = {2: 5, 4: 5}  # simulate BIOS auto mode still active
    state = build_loop_state(config)

    run_iteration(config, sensors.io(), state)

    assert sensors.pwm_enable == {2: 1, 4: 1}


def test_run_iteration_self_heals_before_writing_pwm(make_config):
    """Regression test: on a fresh install (or after a BIOS reset), the chip
    rejects a direct pwm write with EBUSY while pwm_enable is still in an
    auto mode - self-heal must flip it to manual before the write is
    attempted, not after, or the very first control-loop pass always fails."""
    config = make_config(fan_headers=(2,))
    sensors = FakeSensors(cpu_temps_c=[40.0], gpu_temps_c=[45.0], simulate_busy_until_manual=True)
    sensors.pwm_enable = {2: 5}  # BIOS auto mode, as it is right after install
    state = build_loop_state(config)

    written = run_iteration(config, sensors.io(), state)

    assert sensors.pwm_enable == {2: 1}
    assert written == {2: 64}
    assert sensors.pwm_writes == [(2, 64)]


def test_run_iteration_holds_last_known_temp_on_read_failure(make_config):
    config = make_config(fan_headers=(2,))
    sensors = FakeSensors(cpu_temps_c=[40.0, 40.0], gpu_temps_c=[45.0])
    state = build_loop_state(config)
    run_iteration(config, sensors.io(), state)  # seed EMA state

    def failing_read():
        raise OSError("simulated sensor read failure")

    sensors.read_gpu_temp = failing_read
    # Should not raise, and should keep operating off the held CPU value.
    written = run_iteration(config, sensors.io(), state)
    assert written == {}  # dead-band suppresses a re-write of the same target


def test_signal_handler_sets_shutdown_flag():
    flag = {"shutdown": False}
    handler = make_signal_handler(flag)

    handler(15, None)  # SIGTERM's numeric value, frame arg unused

    assert flag["shutdown"] is True


def test_run_loop_reverts_to_auto_on_shutdown(make_config, tmp_path):
    config = dataclasses.replace(
        make_config(fan_headers=(2, 4, 7)), heartbeat_file=tmp_path / "heartbeat"
    )
    sensors = FakeSensors(
        cpu_temps_c=[40.0, 40.0, 40.0],
        gpu_temps_c=[45.0, 45.0, 45.0],
    )
    flag = {"shutdown": False}
    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 2:
            flag["shutdown"] = True

    run_loop(config, sensors.io(), flag, sleep_fn=fake_sleep)

    assert sensors.pwm_enable == {2: 5, 4: 5, 7: 5}


def test_run_loop_exits_immediately_and_still_reverts(make_config, tmp_path):
    config = dataclasses.replace(
        make_config(fan_headers=(2,)), heartbeat_file=tmp_path / "heartbeat"
    )
    sensors = FakeSensors(cpu_temps_c=[40.0], gpu_temps_c=[45.0])
    flag = {"shutdown": True}  # already requested before the loop starts

    run_loop(config, sensors.io(), flag, sleep_fn=lambda _s: None)

    assert sensors.pwm_enable == {2: 5}
    assert sensors.pwm_writes == []  # zero iterations ran
