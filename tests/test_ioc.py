"""Tests for remote_svc_ctrl.ioc module."""

from datetime import datetime, timedelta

from remote_svc_ctrl.ioc import (
    ActiveState,
    EnabledState,
    LoadState,
    Severity,
    SubState,
    _format_cpu_time,
    _format_duration,
    _format_memory,
    _mbbi_kwargs,
    _mbbi_labels,
    _state_index,
)

# --- Enum labels ---


def test_load_state_labels():
    assert LoadState.LOADED.label == "loaded"
    assert LoadState.NOT_FOUND.label == "not-found"
    assert LoadState.BAD_SETTING.label == "bad-setting"


def test_enabled_state_labels():
    assert EnabledState.ENABLED.label == "enabled"
    assert EnabledState.DISABLED.label == "disabled"
    assert EnabledState.STATIC.label == "static"


def test_active_state_labels():
    assert ActiveState.ACTIVE.label == "active"
    assert ActiveState.FAILED.label == "failed"
    assert ActiveState.DEACTIVATING.label == "deactivating"


def test_sub_state_labels():
    assert SubState.RUNNING.label == "running"
    assert SubState.AUTO_RESTART.label == "auto-restart"
    assert SubState.STOP_SIGTERM.label == "stop-sigterm"


# --- Enum severities ---


def test_load_state_severities():
    assert LoadState.LOADED.severity == Severity.NO_ALARM
    assert LoadState.NOT_FOUND.severity == Severity.MAJOR
    assert LoadState.ERROR.severity == Severity.MAJOR
    assert LoadState.BAD_SETTING.severity == Severity.MAJOR
    assert LoadState.MASKED.severity == Severity.NO_ALARM


def test_active_state_severities():
    assert ActiveState.ACTIVE.severity == Severity.NO_ALARM
    assert ActiveState.FAILED.severity == Severity.MAJOR
    assert ActiveState.INACTIVE.severity == Severity.NO_ALARM


def test_sub_state_severities():
    assert SubState.RUNNING.severity == Severity.NO_ALARM
    assert SubState.FAILED.severity == Severity.MAJOR
    assert SubState.DEAD.severity == Severity.NO_ALARM


# --- _mbbi_kwargs ---


def test_mbbi_kwargs_load_state():
    kwargs = _mbbi_kwargs(LoadState)
    assert kwargs == {
        "ONSV": "MAJOR",  # NOT_FOUND = 1
        "THSV": "MAJOR",  # ERROR = 3
        "FRSV": "MAJOR",  # BAD_SETTING = 4
    }


def test_mbbi_kwargs_active_state():
    kwargs = _mbbi_kwargs(ActiveState)
    assert kwargs == {
        "THSV": "MAJOR",  # FAILED = 3
    }


def test_mbbi_kwargs_enabled_state_empty():
    kwargs = _mbbi_kwargs(EnabledState)
    assert kwargs == {}


# --- _mbbi_labels ---


def test_mbbi_labels_load_state():
    labels = _mbbi_labels(LoadState)
    assert labels == ("loaded", "not-found", "masked", "error", "bad-setting")


def test_mbbi_labels_active_state():
    labels = _mbbi_labels(ActiveState)
    assert labels == (
        "active",
        "reloading",
        "inactive",
        "failed",
        "activating",
        "deactivating",
    )


def test_mbbi_labels_sub_state():
    labels = _mbbi_labels(SubState)
    assert labels[0] == "running"
    assert labels[3] == "failed"
    assert labels[4] == "auto-restart"
    assert len(labels) == 16


# --- _state_index ---


def test_state_index_known_values():
    assert _state_index(LoadState, "loaded") == 0
    assert _state_index(LoadState, "not-found") == 1
    assert _state_index(ActiveState, "failed") == 3
    assert _state_index(SubState, "auto-restart") == 4


def test_state_index_unknown_value_returns_zero():
    assert _state_index(LoadState, "unknown") == 0
    assert _state_index(ActiveState, "bogus") == 0


def test_state_index_empty_string_returns_zero():
    assert _state_index(LoadState, "") == 0


# --- _format_memory ---


def test_format_memory_kilobytes():
    val, egu = _format_memory(512 * 1024)  # 512 KB
    assert val == 512.0
    assert egu == "KB"


def test_format_memory_megabytes():
    val, egu = _format_memory(128 * 1024**2)  # 128 MB
    assert val == 128.0
    assert egu == "MB"


def test_format_memory_gigabytes():
    val, egu = _format_memory(2 * 1024**3)  # 2 GB
    assert val == 2.0
    assert egu == "GB"


def test_format_memory_zero():
    val, egu = _format_memory(0)
    assert val == 0.0
    assert egu == "KB"


# --- _format_cpu_time ---


def test_format_cpu_time_milliseconds():
    val, egu = _format_cpu_time(0.5)
    assert val == 500.0
    assert egu == "ms"


def test_format_cpu_time_seconds():
    val, egu = _format_cpu_time(5.227)
    assert val == 5.227
    assert egu == "s"


def test_format_cpu_time_minutes():
    val, egu = _format_cpu_time(120.0)
    assert val == 2.0
    assert egu == "min"


def test_format_cpu_time_hours():
    val, egu = _format_cpu_time(7200.0)
    assert val == 2.0
    assert egu == "h"


# --- _format_duration ---


def test_format_duration_none():
    assert _format_duration(None) == ""


def test_format_duration_seconds():
    since = datetime.now() - timedelta(seconds=45)
    result = _format_duration(since)
    assert result == "45s" or result == "44s"  # Allow 1s timing tolerance


def test_format_duration_minutes():
    since = datetime.now() - timedelta(minutes=5, seconds=30)
    result = _format_duration(since)
    assert result.startswith("5m")


def test_format_duration_hours():
    since = datetime.now() - timedelta(hours=2, minutes=15, seconds=10)
    result = _format_duration(since)
    assert result.startswith("2h")


def test_format_duration_days():
    since = datetime.now() - timedelta(days=3, hours=1, minutes=5, seconds=20)
    result = _format_duration(since)
    assert result.startswith("3d")
