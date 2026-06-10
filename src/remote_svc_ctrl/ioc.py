"""EPICS soft IOC that monitors a systemd service and exposes PVs."""

import argparse
import threading
import time
from enum import IntEnum

from softioc import builder, softioc

from .systemd import parse_systemctl_status, run_systemctl


class Severity:
    NO_ALARM = "NO_ALARM"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class LoadState(IntEnum):
    LOADED = 0
    NOT_FOUND = 1
    MASKED = 2
    ERROR = 3
    BAD_SETTING = 4

    @property
    def severity(self) -> str:
        if self in (self.NOT_FOUND, self.ERROR, self.BAD_SETTING):
            return Severity.MAJOR
        return Severity.NO_ALARM

    @property
    def label(self) -> str:
        return self.name.lower().replace("_", "-")


class EnabledState(IntEnum):
    ENABLED = 0
    DISABLED = 1
    STATIC = 2
    MASKED = 3
    GENERATED = 4
    INDIRECT = 5
    LINKED = 6

    @property
    def label(self) -> str:
        return self.name.lower()


class ActiveState(IntEnum):
    ACTIVE = 0
    RELOADING = 1
    INACTIVE = 2
    FAILED = 3
    ACTIVATING = 4
    DEACTIVATING = 5

    @property
    def severity(self) -> str:
        if self == self.FAILED:
            return Severity.MAJOR
        return Severity.NO_ALARM

    @property
    def label(self) -> str:
        return self.name.lower()


class SubState(IntEnum):
    RUNNING = 0
    DEAD = 1
    EXITED = 2
    FAILED = 3
    AUTO_RESTART = 4
    START = 5
    STOP = 6
    WAITING = 7
    RELOAD = 8
    CONDITION = 9
    START_PRE = 10
    START_POST = 11
    STOP_SIGTERM = 12
    STOP_SIGKILL = 13
    STOP_POST = 14
    MOUNTED = 15

    @property
    def severity(self) -> str:
        if self == self.FAILED:
            return Severity.MAJOR
        return Severity.NO_ALARM

    @property
    def label(self) -> str:
        return self.name.lower().replace("_", "-")


# Severity field name prefixes for mbbi state indices 0-15
_SV_PREFIXES = (
    "ZR", "ON", "TW", "TH", "FR", "FV", "SX", "SV",
    "EI", "NI", "TE", "EL", "TV", "TT", "FT", "FF",
)


def _mbbi_kwargs(enum_cls: type[IntEnum]) -> dict[str, str]:
    """Build severity keyword args for builder.mbbIn from an enum class."""
    kwargs = {}
    for member in enum_cls:
        sev = getattr(member, "severity", Severity.NO_ALARM)
        if sev != Severity.NO_ALARM:
            kwargs[f"{_SV_PREFIXES[member.value]}SV"] = sev
    return kwargs


def _mbbi_labels(enum_cls: type[IntEnum]) -> tuple[str, ...]:
    """Return the ordered labels for an mbbi enum."""
    return tuple(m.label for m in enum_cls)


def _state_index(enum_cls: type[IntEnum], value: str) -> int:
    """Return the index of value in the enum by label, or 0 if not found."""
    for member in enum_cls:
        if member.label == value:
            return member.value
    return 0


def create_ioc(prefix: str, service: str, host: str | None = None):
    """Create and run the IOC for monitoring a systemd service.

    Parameters
    ----------
    prefix : str
        PV prefix (e.g. "XF:28ID-CT{Svc:MyApp}").
    service : str
        Systemd service name (e.g. "my-app.service").
    host : str or None
        SSH target as user@host, or None for localhost.
    """
    builder.SetDeviceName(prefix)

    # --- Status PVs (read-only) ---
    pv_unit = builder.stringIn("Unit", initial_value="")
    pv_description = builder.stringIn("Desc", initial_value="")
    pv_load_state = builder.mbbIn(
        "LoadState", *_mbbi_labels(LoadState), **_mbbi_kwargs(LoadState)
    )
    pv_unit_file = builder.stringIn("UnitFile", initial_value="")
    pv_enabled = builder.mbbIn(
        "Enabled", *_mbbi_labels(EnabledState), **_mbbi_kwargs(EnabledState)
    )
    pv_active_state = builder.mbbIn(
        "ActiveState", *_mbbi_labels(ActiveState), **_mbbi_kwargs(ActiveState)
    )
    pv_sub_state = builder.mbbIn(
        "SubState", *_mbbi_labels(SubState), **_mbbi_kwargs(SubState)
    )
    pv_since = builder.stringIn("Since", initial_value="")
    pv_main_pid = builder.longIn("MainPID", initial_value=0)
    pv_tasks = builder.longIn("Tasks", initial_value=0)
    pv_memory = builder.stringIn("Memory", initial_value="")
    pv_cpu = builder.stringIn("CPU", initial_value="")
    pv_cgroup = builder.stringIn("CGroup", initial_value="")

    # --- Command PVs (write from CA client triggers action) ---
    def _on_start(value):
        if value:
            run_systemctl("start", service, host)

    def _on_stop(value):
        if value:
            run_systemctl("stop", service, host)

    def _on_restart(value):
        if value:
            run_systemctl("restart", service, host)

    builder.boolOut("Start", on_update=_on_start, initial_value=False)
    builder.boolOut("Stop", on_update=_on_stop, initial_value=False)
    builder.boolOut("Restart", on_update=_on_restart, initial_value=False)

    # --- Build and start IOC ---
    builder.LoadDatabase()
    softioc.iocInit()

    # --- Polling thread ---
    def _poll():
        while True:
            try:
                output = run_systemctl("status", service, host)
                status = parse_systemctl_status(output)
            except Exception:
                time.sleep(1)
                continue

            pv_unit.set(status.unit)
            pv_description.set(status.description)
            pv_load_state.set(_state_index(LoadState, status.load_state))
            pv_unit_file.set(status.unit_file)
            pv_enabled.set(_state_index(EnabledState, status.enabled))
            pv_active_state.set(_state_index(ActiveState, status.active_state))
            pv_sub_state.set(_state_index(SubState, status.sub_state))
            pv_since.set(
                status.since.isoformat() if status.since else ""
            )
            pv_main_pid.set(status.main_pid or 0)
            pv_tasks.set(status.tasks or 0)
            pv_memory.set(status.memory)
            pv_cpu.set(status.cpu)
            pv_cgroup.set(status.cgroup)

            time.sleep(1)

    poll_thread = threading.Thread(target=_poll, daemon=True)
    poll_thread.start()

    softioc.interactive_ioc(globals())


def main():
    parser = argparse.ArgumentParser(
        description="EPICS IOC for monitoring/controlling a systemd service"
    )
    parser.add_argument("prefix", help="PV prefix (e.g. 'XF:28ID-CT{Svc:MyApp}')")
    parser.add_argument("service", help="Systemd service name (e.g. 'my-app.service')")
    parser.add_argument(
        "--host",
        default=None,
        help="SSH target as user@host (default: localhost)",
    )
    args = parser.parse_args()

    create_ioc(args.prefix, args.service, args.host)


if __name__ == "__main__":
    main()
