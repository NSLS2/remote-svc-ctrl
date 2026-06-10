"""Tests for remote_svc_ctrl.systemd module."""

from datetime import datetime

from pytest_mock import MockerFixture

from remote_svc_ctrl.systemd import parse_systemctl_status, run_systemctl

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
    assert status.main_pid == 3470042
    assert status.tasks == 1
    assert status.memory == "5.1M"
    assert status.cpu == "23ms"
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
    assert status.main_pid is None
    assert status.tasks is None


def test_parse_failed_service():
    status = parse_systemctl_status(FAILED_STATUS_OUTPUT)

    assert status.unit == "my-app.service"
    assert status.active_state == "failed"
    assert status.sub_state == "failed"
    assert status.since == datetime(2026, 6, 9, 10, 15, 30)
    assert status.main_pid == 12345
    assert status.memory == "0B"
    assert status.cpu == "100ms"


def test_parse_empty_output():
    status = parse_systemctl_status("")

    assert status.unit == ""
    assert status.description == ""
    assert status.load_state == ""
    assert status.active_state == ""
    assert status.sub_state == ""
    assert status.since is None
    assert status.main_pid is None
    assert status.tasks is None


def test_run_systemctl_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.systemd.subprocess.run")
    mock_run.return_value.stdout = "output"

    result = run_systemctl("status", "sshd.service")

    mock_run.assert_called_once_with(
        ["systemctl", "status", "sshd.service"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == "output"


def test_run_systemctl_remote(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.systemd.subprocess.run")
    mock_run.return_value.stdout = "output"

    result = run_systemctl("restart", "my-app.service", host="user@server")

    mock_run.assert_called_once_with(
        ["systemctl", "--host", "user@server", "restart", "my-app.service"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == "output"
