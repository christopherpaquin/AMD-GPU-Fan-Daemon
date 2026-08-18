"""revert_to_auto is the daemon's ultimate safety fallback - it must be
best-effort across headers so one bad write can't leave others stuck."""

from fan_daemon.daemon import Io, revert_to_auto


def make_io(write_pwm_enable) -> Io:
    return Io(
        read_cpu_temp=lambda: 40000,
        read_gpu_temp=lambda: 45000,
        read_pwm_enable=lambda header: 1,
        write_pwm=lambda header, value: None,
        write_pwm_enable=write_pwm_enable,
    )


def test_revert_writes_failsafe_value_to_every_header(make_config):
    written = {}

    def write_pwm_enable(header, value):
        written[header] = value

    revert_to_auto(make_config(), make_io(write_pwm_enable))

    assert written == {2: 5, 4: 5, 7: 5}


def test_revert_continues_past_a_single_header_failure(make_config):
    written = {}

    def write_pwm_enable(header, value):
        if header == 4:
            raise OSError("simulated write failure on header 4")
        written[header] = value

    revert_to_auto(make_config(), make_io(write_pwm_enable))

    assert written == {2: 5, 7: 5}


def test_revert_continues_past_all_headers_failing(make_config):
    def write_pwm_enable(header, value):
        raise OSError("simulated failure")

    # Must not raise - a fully-failed revert still must not crash the caller
    # (e.g. ExecStopPost, or the in-process shutdown path).
    revert_to_auto(make_config(), make_io(write_pwm_enable))
