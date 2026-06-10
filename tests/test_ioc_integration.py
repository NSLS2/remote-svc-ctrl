"""Integration tests for create_ioc with mocked systemctl."""

import subprocess
import time

from pytest_mock import MockerFixture

from remote_svc_ctrl.ioc import (
    ActiveState,
    LoadState,
    SubState,
    _state_index,
    create_ioc,
)

RUNNING_OUTPUT = """\
● my-app.service - My Application
     Loaded: loaded (/etc/systemd/system/my-app.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-05-08 06:40:50 EDT; 1 month 0 days ago
   Main PID: 1234 (my-app)
      Tasks: 4 (limit: 3355442)
     Memory: 128.0M
        CPU: 1.5s
     CGroup: /system.slice/my-app.service
"""

STOPPED_OUTPUT = """\
○ my-app.service - My Application
     Loaded: loaded (/etc/systemd/system/my-app.service; enabled; preset: enabled)
     Active: inactive (dead)
"""

FAILED_OUTPUT = """\
× my-app.service - My Application
     Loaded: loaded (/etc/systemd/system/my-app.service; enabled; preset: enabled)
     Active: failed (failed) since Mon 2026-06-09 10:15:30 EDT; 5min ago
   Main PID: 1234 (code=exited, status=1/FAILURE)
      Tasks: 0 (limit: 3355442)
     Memory: 0B
        CPU: 100ms
     CGroup: /system.slice/my-app.service
"""


def _wait_for_value(get_fn, expected, timeout=5.0, interval=0.05):
    """Poll until get_fn() == expected or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_fn() == expected:
            return
        time.sleep(interval)
    assert get_fn() == expected


def test_ioc_integration(mocker: MockerFixture):
    """Start the real IOC with asyncio dispatcher, mock only subprocess.run."""
    from softioc.device import RecordLookup

    state = {"output": RUNNING_OUTPUT}

    def mock_subprocess_run(cmd, **kwargs):
        command = cmd[1] if len(cmd) > 1 else ""
        if command == "start":
            state["output"] = RUNNING_OUTPUT
        elif command == "stop":
            state["output"] = STOPPED_OUTPUT
        elif command == "restart":
            state["output"] = RUNNING_OUTPUT
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout=state["output"], stderr=""
        )

    mocker.patch(
        "remote_svc_ctrl.systemd.subprocess.run",
        side_effect=mock_subprocess_run,
    )

    create_ioc("TEST:Svc", "my-app.service")

    def get_pv(suffix):
        return RecordLookup.LookupRecord(f"TEST:Svc:{suffix}")

    # Wait for PVs to reflect running state
    _wait_for_value(lambda: get_pv("Unit").get(), "my-app.service")

    assert get_pv("Desc").get() == "My Application"
    assert get_pv("ActiveState").get() == _state_index(ActiveState, "active")
    assert get_pv("SubState").get() == _state_index(SubState, "running")
    assert get_pv("LoadState").get() == _state_index(LoadState, "loaded")
    assert get_pv("MainPID").get() == 1234
    assert get_pv("Tasks").get() == 4
    assert get_pv("Memory").get() == "128.0M"
    assert get_pv("CPU").get() == "1.5s"

    # Trigger stop
    get_pv("Stop").set(1)
    _wait_for_value(
        lambda: get_pv("ActiveState").get(),
        _state_index(ActiveState, "inactive"),
    )
    assert get_pv("SubState").get() == _state_index(SubState, "dead")

    # Trigger start
    get_pv("Start").set(1)
    _wait_for_value(
        lambda: get_pv("ActiveState").get(),
        _state_index(ActiveState, "active"),
    )
    assert get_pv("SubState").get() == _state_index(SubState, "running")
    assert get_pv("MainPID").get() == 1234

    # Trigger restart from stopped
    state["output"] = STOPPED_OUTPUT
    _wait_for_value(
        lambda: get_pv("ActiveState").get(),
        _state_index(ActiveState, "inactive"),
    )
    get_pv("Restart").set(1)
    _wait_for_value(
        lambda: get_pv("ActiveState").get(),
        _state_index(ActiveState, "active"),
    )

    # Test failed state
    state["output"] = FAILED_OUTPUT
    _wait_for_value(
        lambda: get_pv("ActiveState").get(),
        _state_index(ActiveState, "failed"),
    )
    assert get_pv("SubState").get() == _state_index(SubState, "failed")
