"""Tests for remote_svc_ctrl.initd module."""

import subprocess
from datetime import datetime

from pytest_mock import MockerFixture

from remote_svc_ctrl.initd import (
    _parse_initd_description,
    _parse_proc_status_memory,
    _parse_process_stats,
    _parse_ps_cputime,
    _parse_ps_lstart,
    _user_is_root,
    get_process_memory,
    get_process_start,
    get_process_stats,
    is_service_enabled,
    parse_initd_status,
    read_initd_description,
    read_process_logs,
    run_service,
)
from remote_svc_ctrl.ssh import wrap_remote
from remote_svc_ctrl.systemd import MemoryUsage


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["service"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- run_service ---


def test_run_service_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = "output"
    mock_run.return_value.returncode = 0

    result = run_service("status", "my-app")

    mock_run.assert_called_once_with(
        ["service", "my-app", "status"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_run_service_remote(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = "output"
    mock_run.return_value.returncode = 0

    run_service("restart", "my-app", host="user@server")

    mock_run.assert_called_once_with(
        wrap_remote(["service", "my-app", "restart"], "user@server"),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_run_service_action_raises_on_failure(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = "Access denied\n"
    mock_run.return_value.returncode = 1

    import pytest

    with pytest.raises(RuntimeError, match="Access denied"):
        run_service("start", "my-app")


def test_run_service_status_allows_nonzero(mocker: MockerFixture):
    """Non-zero exit codes are meaningful for status (LSB), not an error."""
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = "my-app is stopped"
    mock_run.return_value.returncode = 3

    result = run_service("status", "my-app")
    assert result.returncode == 3


def test_run_service_sudo_used_for_nonroot_control(mocker: MockerFixture):
    mocker.patch("remote_svc_ctrl.initd.os.geteuid", return_value=1000)
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    run_service("restart", "my-app", use_sudo=True)

    mock_run.assert_called_once_with(
        ["sudo", "-n", "service", "my-app", "restart"],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_run_service_no_sudo_for_root_local(mocker: MockerFixture):
    mocker.patch("remote_svc_ctrl.initd.os.geteuid", return_value=0)
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    run_service("restart", "my-app", use_sudo=True)

    mock_run.assert_called_once_with(
        ["service", "my-app", "restart"],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_run_service_no_sudo_for_root_remote_user(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    run_service("restart", "my-app", host="root@server", use_sudo=True)

    mock_run.assert_called_once_with(
        wrap_remote(["service", "my-app", "restart"], "root@server"),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_run_service_sudo_for_nonroot_remote_user(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    run_service("start", "my-app", host="user@server", use_sudo=True)

    mock_run.assert_called_once_with(
        wrap_remote(
            ["sudo", "-n", "service", "my-app", "start"],
            "user@server",
            force_tty=True,
        ),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_run_service_no_sudo_without_flag(mocker: MockerFixture):
    # Non-root, but --sudo not requested: never escalate.
    mocker.patch("remote_svc_ctrl.initd.os.geteuid", return_value=1000)
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    run_service("restart", "my-app")

    mock_run.assert_called_once_with(
        ["service", "my-app", "restart"],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_run_service_sudo_not_used_for_status(mocker: MockerFixture):
    mocker.patch("remote_svc_ctrl.initd.os.geteuid", return_value=1000)
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.stdout = "running"
    mock_run.return_value.returncode = 0

    run_service("status", "my-app", use_sudo=True)

    mock_run.assert_called_once_with(
        ["service", "my-app", "status"],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_user_is_root(mocker: MockerFixture):
    assert _user_is_root("root@server") is True
    assert _user_is_root("user@server") is False

    mocker.patch("remote_svc_ctrl.initd.os.geteuid", return_value=0)
    assert _user_is_root(None) is True
    assert _user_is_root("server") is True

    mocker.patch("remote_svc_ctrl.initd.os.geteuid", return_value=1000)
    assert _user_is_root(None) is False
    assert _user_is_root("server") is False


# --- parse_initd_status ---


def test_parse_status_running_by_keyword():
    status = parse_initd_status(_completed(0, " * my-app is running"), "my-app")

    assert status.unit == "my-app"
    assert status.active_state == "active"
    assert status.sub_state == "running"
    assert status.load_state == "loaded"
    assert status.unit_file == "/etc/init.d/my-app"


def test_parse_status_stopped_by_keyword():
    status = parse_initd_status(_completed(0, " * my-app is not running"), "my-app")

    assert status.active_state == "inactive"
    assert status.sub_state == "dead"


def test_parse_status_running_by_exit_code():
    status = parse_initd_status(_completed(0, ""), "my-app")

    assert status.active_state == "active"
    assert status.sub_state == "running"


def test_parse_status_stopped_by_exit_code():
    status = parse_initd_status(_completed(3, ""), "my-app")

    assert status.active_state == "inactive"
    assert status.sub_state == "dead"


def test_parse_status_failed_by_exit_code():
    status = parse_initd_status(_completed(1, "unexpected"), "my-app")

    assert status.active_state == "failed"
    assert status.sub_state == "failed"


def test_parse_status_extracts_pid():
    status = parse_initd_status(_completed(0, "my-app (pid 4321) is running"), "my-app")

    assert status.main_pid == 4321


def test_parse_status_no_pid():
    status = parse_initd_status(_completed(3, "my-app is stopped"), "my-app")

    assert status.main_pid is None


def test_parse_status_logs_capture_stdout_and_stderr():
    status = parse_initd_status(
        _completed(0, "line one\nline two", stderr="warn line"), "my-app"
    )

    assert status.logs == ["line one", "line two", "warn line"]
    # Description is sourced from the init.d script, not the status output.
    assert status.description == ""


def test_parse_status_state_from_stderr_keyword():
    status = parse_initd_status(_completed(1, "", stderr="my-app is stopped"), "my-app")

    assert status.active_state == "inactive"
    assert status.sub_state == "dead"


# --- _parse_ps_cputime ---


def test_parse_ps_cputime_mm_ss():
    assert _parse_ps_cputime("01:23") == 83.0


def test_parse_ps_cputime_hh_mm_ss():
    assert _parse_ps_cputime("01:02:03") == 3723.0


def test_parse_ps_cputime_days():
    assert _parse_ps_cputime("2-00:00:00") == 2 * 86400


def test_parse_ps_cputime_empty():
    assert _parse_ps_cputime("") == 0.0


# --- _parse_process_stats ---


def test_parse_process_stats():
    memory, cpu, tasks = _parse_process_stats("2048 00:01:00 4")

    assert memory == MemoryUsage(current=2048 * 1024, peak=0.0, swap=0.0, swap_peak=0.0)
    assert cpu == 60.0
    assert tasks == 4


def test_parse_process_stats_empty():
    memory, cpu, tasks = _parse_process_stats("")

    assert memory == MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0)
    assert cpu == 0.0
    assert tasks is None


def test_get_process_stats_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "4096 00:00:30 2"

    memory, cpu, tasks = get_process_stats(1234)

    mock_run.assert_called_once_with(
        ["ps", "-p", "1234", "-o", "rss=,cputime=,nlwp="],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert memory.current == 4096 * 1024
    assert cpu == 30.0
    assert tasks == 2


def test_get_process_stats_remote(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "1 00:00:01 1"

    get_process_stats(99, host="user@server")

    mock_run.assert_called_once_with(
        wrap_remote(["ps", "-p", "99", "-o", "rss=,cputime=,nlwp="], "user@server"),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_get_process_stats_missing_process(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""

    memory, cpu, tasks = get_process_stats(1234)

    assert memory == MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0)
    assert cpu == 0.0
    assert tasks is None


# --- _parse_proc_status_memory / get_process_memory ---


PROC_STATUS = """\
Name:\tmy-app
State:\tS (sleeping)
VmPeak:\t  200000 kB
VmSize:\t  190000 kB
VmHWM:\t   65536 kB
VmRSS:\t   40960 kB
VmSwap:\t    1024 kB
Threads:\t4
"""


def test_parse_proc_status_memory():
    memory = _parse_proc_status_memory(PROC_STATUS)

    assert memory == MemoryUsage(
        current=40960 * 1024,
        peak=65536 * 1024,
        swap=1024 * 1024,
        swap_peak=0.0,
    )


def test_parse_proc_status_memory_missing_fields():
    memory = _parse_proc_status_memory("Name:\tmy-app\nState:\tS\n")

    assert memory == MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0)


def test_get_process_memory_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = PROC_STATUS

    memory = get_process_memory(1234)

    mock_run.assert_called_once_with(
        ["cat", "/proc/1234/status"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert memory.current == 40960 * 1024
    assert memory.peak == 65536 * 1024
    assert memory.swap == 1024 * 1024


def test_get_process_memory_remote(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = PROC_STATUS

    get_process_memory(7, host="user@server")

    mock_run.assert_called_once_with(
        wrap_remote(["cat", "/proc/7/status"], "user@server"),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_get_process_memory_missing_process(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""

    assert get_process_memory(1234) == MemoryUsage(
        current=0.0, peak=0.0, swap=0.0, swap_peak=0.0
    )


# --- _parse_ps_lstart / get_process_start ---


def test_parse_ps_lstart():
    assert _parse_ps_lstart("Mon Aug 25 10:15:30 2026") == datetime(
        2026, 8, 25, 10, 15, 30
    )


def test_parse_ps_lstart_extra_whitespace():
    # ps pads the day-of-month, producing a double space.
    assert _parse_ps_lstart(" Tue Aug  5 06:40:50 2026\n") == datetime(
        2026, 8, 5, 6, 40, 50
    )


def test_parse_ps_lstart_empty():
    assert _parse_ps_lstart("") is None


def test_parse_ps_lstart_invalid():
    assert _parse_ps_lstart("not a date") is None


def test_get_process_start_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Mon Aug 25 10:15:30 2026\n"

    result = get_process_start(1234)

    mock_run.assert_called_once_with(
        ["ps", "-p", "1234", "-o", "lstart="],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == datetime(2026, 8, 25, 10, 15, 30)


def test_get_process_start_missing_process(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""

    assert get_process_start(1234) is None


# --- is_service_enabled ---


def test_is_service_enabled_on(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""

    result = is_service_enabled("my-app")

    mock_run.assert_called_once_with(
        ["chkconfig", "my-app"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == "enabled"


def test_is_service_enabled_off(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""

    assert is_service_enabled("my-app") == "disabled"


def test_is_service_enabled_unknown_service(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = "error reading information on service my-app\n"

    assert is_service_enabled("my-app") == ""


def test_is_service_enabled_chkconfig_missing(mocker: MockerFixture):
    mocker.patch(
        "remote_svc_ctrl.initd.subprocess.run",
        side_effect=FileNotFoundError("chkconfig"),
    )

    assert is_service_enabled("my-app") == ""


# --- _parse_initd_description ---


LSB_SCRIPT = """\
#!/bin/sh
### BEGIN INIT INFO
# Provides:          my-app
# Required-Start:    $network
# Short-Description: Short summary of my app
# Description:       My application does a thing
#                    and continues onto a second line.
### END INIT INFO
"""

CHKCONFIG_SCRIPT = """\
#!/bin/sh
# chkconfig: 2345 20 80
# description: A chkconfig-style daemon \\
#              spanning two lines
"""

SHORT_ONLY_SCRIPT = """\
#!/bin/sh
### BEGIN INIT INFO
# Short-Description: Only a short description
### END INIT INFO
"""


def test_parse_initd_description_lsb_multiline():
    result = _parse_initd_description(LSB_SCRIPT)
    assert result == "My application does a thing and continues onto a second line."


def test_parse_initd_description_chkconfig():
    result = _parse_initd_description(CHKCONFIG_SCRIPT)
    assert result == "A chkconfig-style daemon spanning two lines"


def test_parse_initd_description_short_fallback():
    result = _parse_initd_description(SHORT_ONLY_SCRIPT)
    assert result == "Only a short description"


def test_parse_initd_description_none():
    assert _parse_initd_description("#!/bin/sh\necho hi\n") == ""


def test_read_initd_description_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = SHORT_ONLY_SCRIPT

    result = read_initd_description("my-app")

    mock_run.assert_called_once_with(
        ["cat", "/etc/init.d/my-app"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result == "Only a short description"


def test_read_initd_description_missing_file(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.initd.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""

    assert read_initd_description("my-app") == ""


# --- read_process_logs ---


def test_read_process_logs_from_regular_files(mocker: MockerFixture):
    # readlink(fd1), tail(fd1), readlink(fd2), tail(fd2)
    mock_run = mocker.patch(
        "remote_svc_ctrl.initd.subprocess.run",
        side_effect=[
            _completed(0, "/var/log/my-app.out\n"),
            _completed(0, "out line 1\nout line 2\n"),
            _completed(0, "/var/log/my-app.err\n"),
            _completed(0, "err line 1\n"),
        ],
    )

    logs = read_process_logs(1234)

    assert logs == ["out line 1", "out line 2", "err line 1"]
    first_call = mock_run.call_args_list[0].args[0]
    assert first_call == ["readlink", "-f", "/proc/1234/fd/1"]


def test_read_process_logs_skips_devnull_and_pipes(mocker: MockerFixture):
    mocker.patch(
        "remote_svc_ctrl.initd.subprocess.run",
        side_effect=[
            _completed(0, "/dev/null\n"),
            _completed(0, "pipe:[12345]\n"),
        ],
    )

    assert read_process_logs(1234) == []


def test_read_process_logs_dedupes_shared_target(mocker: MockerFixture):
    # Both fd 1 and 2 point at the same file; tail should run only once.
    mock_run = mocker.patch(
        "remote_svc_ctrl.initd.subprocess.run",
        side_effect=[
            _completed(0, "/var/log/my-app.log\n"),
            _completed(0, "shared line\n"),
            _completed(0, "/var/log/my-app.log\n"),
        ],
    )

    logs = read_process_logs(1234)

    assert logs == ["shared line"]
    assert mock_run.call_count == 3


def test_read_process_logs_remote(mocker: MockerFixture):
    mock_run = mocker.patch(
        "remote_svc_ctrl.initd.subprocess.run",
        side_effect=[
            _completed(0, "/var/log/my-app.out\n"),
            _completed(0, "line\n"),
            _completed(0, "/dev/null\n"),
        ],
    )

    read_process_logs(7, host="user@server")

    readlink_call = mock_run.call_args_list[0].args[0]
    tail_call = mock_run.call_args_list[1].args[0]
    assert readlink_call == wrap_remote(
        ["readlink", "-f", "/proc/7/fd/1"], "user@server"
    )
    assert tail_call == wrap_remote(
        ["tail", "-n", "20", "/var/log/my-app.out"], "user@server"
    )
