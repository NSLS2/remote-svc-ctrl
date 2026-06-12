"""Tests for remote_svc_ctrl.systemd module."""

from datetime import datetime

from pytest_mock import MockerFixture

from remote_svc_ctrl.systemd import (
    MemoryUsage,
    _parse_cpu_time,
    _parse_log_lines,
    _parse_memory_field,
    parse_systemctl_status,
    run_systemctl,
)

ACTIVE_STATUS_OUTPUT = """\
● sshd.service - OpenSSH server daemon
     Loaded: loaded (/usr/lib/systemd/system/sshd.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-05-08 06:40:50 EDT; 1 month 0 days ago
       Docs: man:sshd(8)
             man:sshd_config(5)
   Main PID: 3470042 (sshd)
      Tasks: 1 (limit: 3355442)
     Memory: 5.1M
        CPU: 23ms
     CGroup: /system.slice/sshd.service
             └─3470042 "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups"
"""

INACTIVE_STATUS_OUTPUT = """\
○ my-app.service - My Application
     Loaded: loaded (/etc/systemd/system/my-app.service; disabled; preset: disabled)
     Active: inactive (dead)
"""

FAILED_STATUS_OUTPUT = """\
× my-app.service - My Application
     Loaded: loaded (/etc/systemd/system/my-app.service; enabled; preset: enabled)
     Active: failed (failed) since Mon 2026-06-09 10:15:30 EDT; 5min ago
   Main PID: 12345 (code=exited, status=1/FAILURE)
      Tasks: 0 (limit: 3355442)
     Memory: 0B
        CPU: 100ms
     CGroup: /system.slice/my-app.service
"""

FAILED_SIGNAL_STATUS_OUTPUT = """\
× xspd.service - Starting X-Spectrum remote service
     Loaded: loaded (/lib/systemd/system/xspd.service; enabled; preset: enabled)
     Active: failed (Result: signal) since Mon 2026-06-08 12:00:40 EDT; 4 days ago
   Duration: 2.187s
    Process: 3185819 ExecStart=/usr/sbin/xspd (code=killed, signal=SEGV)
   Main PID: 3185819 (code=killed, signal=SEGV)
        CPU: 173ms
"""


def test_parse_active_running_service():
    status = parse_systemctl_status(ACTIVE_STATUS_OUTPUT)

    assert status.unit == "sshd.service"
    assert status.description == "OpenSSH server daemon"
    assert status.load_state == "loaded"
    assert status.unit_file == "/usr/lib/systemd/system/sshd.service"
    assert status.enabled == "enabled"
    assert status.active_state == "active"
    assert status.sub_state == "running"
    assert status.since == datetime(2026, 5, 8, 6, 40, 50)
    assert status.duration is None
    assert status.result == ""
    assert status.exit_info == ""
    assert status.main_pid == 3470042
    assert status.tasks == 1
    assert status.memory == MemoryUsage(
        current=5.1 * 1024**2, peak=0.0, swap=0.0, swap_peak=0.0
    )
    assert status.cpu == 0.023
    assert status.cgroup == "/system.slice/sshd.service"


def test_parse_inactive_dead_service():
    status = parse_systemctl_status(INACTIVE_STATUS_OUTPUT)

    assert status.unit == "my-app.service"
    assert status.description == "My Application"
    assert status.load_state == "loaded"
    assert status.unit_file == "/etc/systemd/system/my-app.service"
    assert status.enabled == "disabled"
    assert status.active_state == "inactive"
    assert status.sub_state == "dead"
    assert status.since is None
    assert status.duration is None
    assert status.result == ""
    assert status.exit_info == ""
    assert status.main_pid is None
    assert status.tasks is None


def test_parse_failed_service():
    status = parse_systemctl_status(FAILED_STATUS_OUTPUT)

    assert status.unit == "my-app.service"
    assert status.active_state == "failed"
    assert status.sub_state == "failed"
    assert status.since == datetime(2026, 6, 9, 10, 15, 30)
    assert status.duration is None
    assert status.result == ""
    assert status.exit_info == "code=exited, status=1/FAILURE"
    assert status.main_pid == 12345
    assert status.memory == MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0)
    assert status.cpu == 0.1


def test_parse_failed_signal_service():
    status = parse_systemctl_status(FAILED_SIGNAL_STATUS_OUTPUT)

    assert status.unit == "xspd.service"
    assert status.description == "Starting X-Spectrum remote service"
    assert status.active_state == "failed"
    assert status.sub_state == "failed"
    assert status.result == "signal"
    assert status.since == datetime(2026, 6, 8, 12, 0, 40)
    assert status.duration == 2.187
    assert status.exit_info == "code=killed, signal=SEGV"
    assert status.main_pid == 3185819
    assert status.cpu == 0.173


def test_parse_empty_output():
    status = parse_systemctl_status("")

    assert status.unit == ""
    assert status.description == ""
    assert status.load_state == ""
    assert status.active_state == ""
    assert status.sub_state == ""
    assert status.since is None
    assert status.duration is None
    assert status.result == ""
    assert status.exit_info == ""
    assert status.main_pid is None
    assert status.tasks is None


def test_run_systemctl_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.systemd.subprocess.run")
    mock_run.return_value.stdout = "output"
    mock_run.return_value.returncode = 0

    result = run_systemctl("status", "sshd.service")

    mock_run.assert_called_once_with(
        ["systemctl", "--no-pager", "--no-ask-password", "status", "sshd.service"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == "output"


def test_run_systemctl_remote(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.systemd.subprocess.run")
    mock_run.return_value.stdout = "output"
    mock_run.return_value.returncode = 0

    result = run_systemctl("restart", "my-app.service", host="user@server")

    mock_run.assert_called_once_with(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "user@server",
            "systemctl",
            "--no-pager",
            "--no-ask-password",
            "restart",
            "my-app.service",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == "output"


def test_run_systemctl_raises_on_failure(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.systemd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = "Access denied\n"
    mock_run.return_value.returncode = 1

    import pytest

    with pytest.raises(RuntimeError, match="Access denied"):
        run_systemctl("start", "sshd.service")


def test_run_systemctl_allows_exit_code_3(mocker: MockerFixture):
    """Exit code 3 means unit not active, normal for status on stopped services."""
    mock_run = mocker.patch("remote_svc_ctrl.systemd.subprocess.run")
    mock_run.return_value.stdout = "inactive output"
    mock_run.return_value.returncode = 3

    result = run_systemctl("status", "stopped.service")
    assert result == "inactive output"


# --- _parse_cpu_time ---


def test_parse_cpu_time_seconds():
    assert _parse_cpu_time("5.227s") == 5.227


def test_parse_cpu_time_milliseconds():
    assert _parse_cpu_time("23ms") == 0.023


def test_parse_cpu_time_minutes_and_seconds():
    assert _parse_cpu_time("1min 5.227s") == 65.227


def test_parse_cpu_time_hours_minutes_seconds():
    assert _parse_cpu_time("1h 2min 3.456s") == 3723.456


def test_parse_cpu_time_empty():
    assert _parse_cpu_time("") == 0.0


# --- _parse_memory_field ---


def test_parse_memory_field_simple():
    result = _parse_memory_field("5.1M")
    assert result == MemoryUsage(
        current=5.1 * 1024**2, peak=0.0, swap=0.0, swap_peak=0.0
    )


def test_parse_memory_field_with_all_subfields():
    result = _parse_memory_field("176K (peak: 22.7M, swap: 1.2M, swap peak: 1.2M)")
    assert result.current == 176 * 1024
    assert result.peak == 22.7 * 1024**2
    assert result.swap == 1.2 * 1024**2
    assert result.swap_peak == 1.2 * 1024**2


def test_parse_memory_field_zero():
    result = _parse_memory_field("0B")
    assert result == MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0)


def test_parse_memory_field_empty():
    result = _parse_memory_field("")
    assert result == MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0)


# --- _parse_log_lines ---


def test_parse_log_lines_extracts_messages():
    lines = [
        "Jun 10 09:21:40 alma10 sshd-session[3467350]: Connection from 1.2.3.4",
        "Jun 10 09:21:46 alma10 sshd-session[3467366]: Invalid user foo",
    ]
    result = _parse_log_lines(lines)
    assert len(result) == 2
    assert "Connection from 1.2.3.4" in result[0]
    assert "Invalid user foo" in result[1]


def test_parse_log_lines_skips_non_log_lines():
    lines = [
        "     Loaded: loaded (/usr/lib/systemd/system/sshd.service; enabled)",
        "Jun 10 09:21:40 alma10 sshd[123]: test message",
    ]
    result = _parse_log_lines(lines)
    assert len(result) == 1
    assert "test message" in result[0]
