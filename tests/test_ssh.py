"""Tests for remote_svc_ctrl.ssh module."""

from pytest_mock import MockerFixture

from remote_svc_ctrl.ssh import (
    close_connection,
    control_path,
    read_log_file,
    wrap_remote,
)

# --- wrap_remote / connection multiplexing ---


def test_wrap_remote_local_is_unchanged():
    assert wrap_remote(["service", "my-app", "status"], None) == [
        "service",
        "my-app",
        "status",
    ]


def test_wrap_remote_enables_control_master():
    wrapped = wrap_remote(["service", "my-app", "status"], "user@server")

    assert wrapped[0] == "ssh"
    assert "ControlMaster=auto" in wrapped
    assert f"ControlPath={control_path('user@server')}" in wrapped
    assert "ControlPersist=60" in wrapped
    # PATH is prepended for remote commands so /sbin tools are found.
    assert "PATH=$PATH:/sbin:/usr/sbin" in wrapped
    assert wrapped[-3:] == ["service", "my-app", "status"]
    assert "user@server" in wrapped


def test_control_path_is_stable_and_host_specific():
    assert control_path("user@server") == control_path("user@server")
    assert control_path("user@server") != control_path("other@host")


# --- close_connection ---


def test_close_connection_local_is_noop(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.ssh.subprocess.run")

    close_connection(None)

    mock_run.assert_not_called()


def test_close_connection_sends_exit(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.ssh.subprocess.run")

    close_connection("user@server")

    mock_run.assert_called_once_with(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ControlPath={control_path('user@server')}",
            "-O",
            "exit",
            "user@server",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_close_connection_ignores_errors(mocker: MockerFixture):
    mocker.patch(
        "remote_svc_ctrl.ssh.subprocess.run",
        side_effect=OSError("boom"),
    )

    # Should not raise.
    close_connection("user@server")


# --- read_log_file ---


def test_read_log_file_local(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.ssh.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "line 1\nline 2\n\n"

    logs = read_log_file("/var/log/my-app.log", lines=5)

    mock_run.assert_called_once_with(
        ["tail", "-n", "5", "/var/log/my-app.log"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert logs == ["line 1", "line 2"]


def test_read_log_file_remote(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.ssh.subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "line\n"

    read_log_file("/var/log/my-app.log", host="user@server", lines=20)

    mock_run.assert_called_once_with(
        wrap_remote(["tail", "-n", "20", "/var/log/my-app.log"], "user@server"),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_read_log_file_missing_returns_empty(mocker: MockerFixture):
    mock_run = mocker.patch("remote_svc_ctrl.ssh.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""

    assert read_log_file("/nope.log") == []


def test_read_log_file_ignores_errors(mocker: MockerFixture):
    mocker.patch(
        "remote_svc_ctrl.ssh.subprocess.run",
        side_effect=OSError("boom"),
    )

    assert read_log_file("/var/log/my-app.log") == []
