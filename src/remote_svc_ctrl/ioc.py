"""EPICS soft IOC that monitors a systemd service and exposes PVs."""

import argparse
import asyncio
import atexit
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Protocol

from epicsdbbuilder import SetSimpleRecordNames
from softioc import alarm, builder, softioc
from softioc.asyncio_dispatcher import AsyncioDispatcher

from ._version import __version__  # noqa: F401
from .initd import (
    get_process_memory,
    get_process_start,
    get_process_stats,
    is_service_enabled,
    parse_initd_status,
    read_initd_description,
    read_process_logs,
    run_service,
)
from .ssh import close_connection, read_log_file
from .systemd import ServiceStatus, parse_systemctl_status, run_systemctl

log = logging.getLogger(__name__)


class ServiceBackend(Protocol):
    """Interface for querying and controlling a service backend."""

    def get_status(self) -> ServiceStatus:
        """Return the current status of the service."""
        ...

    def run_command(self, command: str) -> None:
        """Run a control action ("start", "stop", "restart") on the service."""
        ...


class SystemdBackend:
    """Service backend that uses systemctl to manage a systemd unit."""

    def __init__(
        self,
        service: str,
        host: str | None = None,
        log_file: str | None = None,
        log_lines: int = 20,
    ):
        self.service = service
        self.host = host
        self.log_file = log_file
        self.log_lines = log_lines
        # Close the multiplexed ssh connection when the process exits.
        if host:
            atexit.register(close_connection, host)

    def get_status(self) -> ServiceStatus:
        status = parse_systemctl_status(
            run_systemctl("status", self.service, self.host, lines=self.log_lines)
        )
        # An explicit log file overrides the journal lines from `systemctl`.
        if self.log_file:
            logs = read_log_file(self.log_file, self.host, self.log_lines)
            if logs:
                status.logs = logs
        return status

    def run_command(self, command: str) -> None:
        run_systemctl(command, self.service, self.host)


class InitdBackend:
    """Service backend that uses the `service` command to manage init.d."""

    def __init__(
        self,
        service: str,
        host: str | None = None,
        log_file: str | None = None,
        log_lines: int = 20,
        use_sudo: bool = False,
    ):
        self.service = service
        self.host = host
        self.log_file = log_file
        self.log_lines = log_lines
        self.use_sudo = use_sudo
        self._description: str | None = None
        # Close the multiplexed ssh connection when the process exits.
        if host:
            atexit.register(close_connection, host)

    def get_status(self) -> ServiceStatus:
        status = parse_initd_status(
            run_service("status", self.service, self.host), self.service
        )
        # The description comes from the init.d script and is static, so cache
        # it once a non-empty value has been read.
        if not self._description:
            self._description = read_initd_description(self.service, self.host)
        status.description = self._description
        status.enabled = is_service_enabled(self.service, self.host)
        # A running service reports a PID; use it to gather live process stats.
        if status.main_pid is not None:
            memory, cpu, tasks = get_process_stats(status.main_pid, self.host)
            # /proc gives current, peak and swap; fall back to ps RSS if absent.
            proc_memory = get_process_memory(status.main_pid, self.host)
            status.memory = proc_memory if proc_memory.current else memory
            status.cpu = cpu
            status.tasks = tasks
            status.since = get_process_start(status.main_pid, self.host)
            # Init.d has no journal, so derive uptime from the start time.
            if status.since is not None:
                elapsed = (datetime.now() - status.since).total_seconds()
                status.duration = elapsed if elapsed >= 0 else None
        # Logs: prefer an explicit log file, else the process's stdout/stderr.
        if self.log_file:
            logs = read_log_file(self.log_file, self.host, self.log_lines)
            if logs:
                status.logs = logs
        elif status.main_pid is not None:
            process_logs = read_process_logs(status.main_pid, self.host, self.log_lines)
            if process_logs:
                status.logs = process_logs
        return status

    def run_command(self, command: str) -> None:
        run_service(command, self.service, self.host, use_sudo=self.use_sudo)


class Severity:
    """EPICS alarm severity constants."""

    NO_ALARM = "NO_ALARM"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class _StateEnum(IntEnum):
    """Base for systemd state enums with an mbbi label."""

    @property
    def label(self) -> str:
        return self.name.lower().replace("_", "-")


class LoadState(_StateEnum):
    """Systemd unit load states."""

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


class EnabledState(_StateEnum):
    """Systemd unit enabled states."""

    ENABLED = 0
    DISABLED = 1
    STATIC = 2
    MASKED = 3
    GENERATED = 4
    INDIRECT = 5
    LINKED = 6


class ActiveState(_StateEnum):
    """Systemd unit active states."""

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


class SubState(StrEnum):
    """Systemd unit sub-states."""

    RUNNING = "running"
    DEAD = "dead"
    EXITED = "exited"
    FAILED = "failed"
    AUTO_RESTART = "auto-restart"
    START = "start"
    STOP = "stop"
    WAITING = "waiting"
    RELOAD = "reload"
    CONDITION = "condition"
    START_PRE = "start-pre"
    START_POST = "start-post"
    STOP_PRE = "stop-pre"
    STOP_SIGTERM = "stop-sigterm"
    STOP_SIGKILL = "stop-sigkill"
    STOP_POST = "stop-post"
    FINAL_SIGTERM = "final-sigterm"
    FINAL_SIGKILL = "final-sigkill"
    FINAL_WATCHDOG = "final-watchdog"
    CLEANING = "cleaning"
    MOUNTED = "mounted"
    MOUNTING = "mounting"
    UNMOUNTING = "unmounting"
    PLUGGED = "plugged"
    LISTENING = "listening"
    TENTATIVE = "tentative"
    ACTIVATING = "activating"
    ACTIVATING_DONE = "activating-done"
    DEACTIVATING = "deactivating"
    DEACTIVATING_SIGTERM = "deactivating-sigterm"
    DEACTIVATING_SIGKILL = "deactivating-sigkill"

    @property
    def severity(self) -> int:
        """Return the alarm severity for this sub-state."""
        if self == self.FAILED:
            return alarm.MAJOR_ALARM
        return alarm.NO_ALARM


@dataclass
class _TrackedStates:
    """Snapshot of states used to detect changes."""

    active: ActiveState = ActiveState.ACTIVE
    sub: SubState = SubState.RUNNING
    load: LoadState = LoadState.LOADED
    enabled: EnabledState = EnabledState.ENABLED


# Severity field name prefixes for mbbi state indices 0-15
_SV_PREFIXES = (
    "ZR",
    "ON",
    "TW",
    "TH",
    "FR",
    "FV",
    "SX",
    "SV",
    "EI",
    "NI",
    "TE",
    "EL",
    "TV",
    "TT",
    "FT",
    "FF",
)


def _mbbi_kwargs(enum_cls: type[_StateEnum]) -> dict[str, str]:
    """Build severity keyword args for builder.mbbIn from an enum class."""
    kwargs = {}
    for member in enum_cls:
        sev = getattr(member, "severity", Severity.NO_ALARM)
        if sev != Severity.NO_ALARM:
            kwargs[f"{_SV_PREFIXES[member.value]}SV"] = sev
    return kwargs


def _mbbi_labels(enum_cls: type[_StateEnum]) -> tuple[str, ...]:
    """Return the ordered labels for an mbbi enum."""
    return tuple(m.label for m in enum_cls)


def _state_index(enum_cls: type[_StateEnum], value: str) -> int:
    """Return the index of value in the enum by label, or 0 if not found."""
    for member in enum_cls:
        if member.label == value:
            return member.value
    return 0


def _format_memory(value_bytes: float) -> tuple[float, str]:
    """Convert bytes to a display value and EGU (KB, MB, or GB)."""
    if value_bytes >= 1024**3:
        return value_bytes / 1024**3, "GB"
    if value_bytes < 1024**2:
        return value_bytes / 1024, "KB"
    return value_bytes / 1024**2, "MB"


def _format_cpu_time(seconds: float) -> tuple[float, str]:
    """Convert CPU seconds to a display value and EGU (ms, s, min, or h)."""
    if seconds >= 3600:
        return seconds / 3600, "h"
    if seconds >= 60:
        return seconds / 60, "min"
    if seconds < 1:
        return seconds * 1000, "ms"
    return seconds, "s"


def _format_duration(since: datetime | None) -> str:
    """Format elapsed time since a datetime as 'Xd Xh Xm Xs'."""
    if since is None:
        return ""
    delta = datetime.now() - since
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return ""
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def create_ioc(
    prefix: str,
    service: str,
    host: str | None = None,
    use_initd: bool = False,
    log_file: str | None = None,
    log_lines: int = 20,
    use_sudo: bool = False,
):
    """Create and run the IOC for monitoring a service.

    Parameters
    ----------
    prefix : str
        PV prefix (e.g. "XF:28ID-CT{Svc:MyApp}").
    service : str
        Service name (e.g. "my-app.service" for systemd, "my-app" for init.d).
    host : str or None
        SSH target as user@host, or None for localhost.
    use_initd : bool
        Manage the service via init.d (SysV) instead of systemd.
    log_file : str or None
        Path to a log file to tail for the Logs PV instead of the default
        journal/process output.
    log_lines : int
        Number of log lines to track.
    use_sudo : bool
        For init.d, run control actions via ``sudo -n`` (requires sudoers).
    """
    backend: ServiceBackend = (
        InitdBackend(service, host, log_file, log_lines, use_sudo)
        if use_initd
        else SystemdBackend(service, host, log_file, log_lines)
    )

    SetSimpleRecordNames(prefix=prefix, separator="")

    # --- Status PVs (read-only) ---
    pv_unit = builder.longStringIn("Unit", length=256, initial_value="")
    pv_description = builder.longStringIn("Desc", length=256, initial_value="")
    pv_load_state = builder.mbbIn(
        "LoadState", *_mbbi_labels(LoadState), **_mbbi_kwargs(LoadState)
    )
    pv_unit_file = builder.longStringIn("UnitFile", length=256, initial_value="")
    pv_enabled = builder.mbbIn(
        "Enabled", *_mbbi_labels(EnabledState), **_mbbi_kwargs(EnabledState)
    )
    pv_active_state = builder.mbbIn(
        "ActiveState", *_mbbi_labels(ActiveState), **_mbbi_kwargs(ActiveState)
    )
    pv_sub_state = builder.stringIn("SubState", initial_value="")
    pv_since = builder.stringIn("Since", initial_value="")
    pv_duration = builder.aIn("Duration", initial_value=0, EGU="s", PREC=3)
    pv_result = builder.stringIn("Result", initial_value="")
    pv_exit_info = builder.stringIn("ExitInfo", initial_value="")
    pv_main_pid = builder.longIn("MainPID", initial_value=0)
    pv_tasks = builder.aIn("Tasks", initial_value=0, PREC=0)
    pv_mem_current = builder.aIn("Mem", initial_value=0, EGU="MB", PREC=1)
    pv_mem_peak = builder.aIn("MemPeak", initial_value=0, EGU="MB", PREC=1)
    pv_mem_swap = builder.aIn("MemSwap", initial_value=0, EGU="MB", PREC=1)
    pv_mem_swap_peak = builder.aIn("MemSwapPeak", initial_value=0, EGU="MB", PREC=1)
    pv_cpu = builder.aIn("CPU", initial_value=0, EGU="s", PREC=3)
    pv_cgroup = builder.longStringIn("CGroup", length=256, initial_value="")
    pv_logs = builder.longStringIn("Logs", length=4096, initial_value="")
    pv_status = builder.longStringIn("StatusMessage", length=256, initial_value="")

    def _status_msg(msg: str):
        """Set status PV with timestamp prefix."""
        ts = datetime.now().strftime("%H:%M:%S")
        pv_status.set(f"[{ts}] {msg}")

    # --- Command PVs (write from CA client triggers action) ---
    def _is_active() -> bool:
        return last_states is not None and last_states.active == ActiveState.ACTIVE

    def _on_start(value):
        if value:
            if _is_active():
                _status_msg("Service is already running")
                return
            try:
                backend.run_command("start")
            except Exception as e:
                _status_msg(f"Start failed: {e}")

    def _on_stop(value):
        if value:
            if not _is_active():
                _status_msg("Service is already stopped")
                return
            try:
                backend.run_command("stop")
            except Exception as e:
                _status_msg(f"Stop failed: {e}")

    def _on_restart(value):
        if value:
            try:
                backend.run_command("restart")
            except Exception as e:
                _status_msg(f"Restart failed: {e}")

    builder.boolOut(
        "Start", on_update=_on_start, initial_value=False, always_update=True
    )
    builder.boolOut("Stop", on_update=_on_stop, initial_value=False, always_update=True)
    builder.boolOut(
        "Restart", on_update=_on_restart, initial_value=False, always_update=True
    )

    # --- Build and start IOC ---
    dispatcher = AsyncioDispatcher()
    builder.LoadDatabase()
    softioc.iocInit(dispatcher)

    # --- Polling task ---
    egu_cache: dict[str, str] = {}
    last_states: _TrackedStates | None = None

    def _set_egu(pv, egu: str):
        """Update EGU field only when it changes, via direct memory write."""
        if egu_cache.get(pv._name) != egu:
            log.info(
                "Updating EGU for %s: %s -> %s",
                pv._name,
                egu_cache.get(pv._name, ""),
                egu,
            )
            pv._record.EGU = egu
            egu_cache[pv._name] = egu

    async def _poll():
        first_poll = True
        while True:
            try:
                status = backend.get_status()
            except Exception:
                await asyncio.sleep(1)
                continue

            pv_unit.set(status.unit)
            pv_description.set(status.description)
            pv_load_state.set(_state_index(LoadState, status.load_state))
            pv_unit_file.set(status.unit_file)
            pv_enabled.set(_state_index(EnabledState, status.enabled))
            pv_active_state.set(_state_index(ActiveState, status.active_state))
            try:
                sub = SubState(status.sub_state)
            except ValueError:
                sub = None
            sub_severity = sub.severity if sub else alarm.NO_ALARM
            pv_sub_state.set(
                status.sub_state,
                severity=sub_severity,
                alarm=sub_severity,
            )
            pv_since.set(_format_duration(status.since))
            pv_duration.set(status.duration or 0)
            pv_result.set(status.result)
            pv_exit_info.set(status.exit_info)
            pv_main_pid.set(status.main_pid or 0)
            pv_tasks.set(status.tasks or 0)

            for pv, value_bytes in (
                (pv_mem_current, status.memory.current),
                (pv_mem_peak, status.memory.peak),
                (pv_mem_swap, status.memory.swap),
                (pv_mem_swap_peak, status.memory.swap_peak),
            ):
                display_val, egu = _format_memory(value_bytes)
                pv.set(display_val)
                _set_egu(pv, egu)

            cpu_val, cpu_egu = _format_cpu_time(status.cpu)
            pv_cpu.set(cpu_val)
            _set_egu(pv_cpu, cpu_egu)
            pv_cgroup.set(status.cgroup)
            pv_logs.set("\n".join(status.logs))

            # Track state changes and update status message
            active_enum = ActiveState(_state_index(ActiveState, status.active_state))
            try:
                sub_enum = SubState(status.sub_state)
            except ValueError:
                sub_enum = SubState.RUNNING
            load_enum = LoadState(_state_index(LoadState, status.load_state))
            enabled_enum = EnabledState(_state_index(EnabledState, status.enabled))
            current_states = _TrackedStates(
                active=active_enum,
                sub=sub_enum,
                load=load_enum,
                enabled=enabled_enum,
            )
            if first_poll:
                state_str = (
                    f"{status.active_state}({status.sub_state})"
                    if status.active_state
                    else "unknown state"
                )
                _status_msg(
                    f"{state_str} load={status.load_state} enabled={status.enabled}"
                )
                nonlocal last_states
                last_states = current_states
                first_poll = False
            elif current_states != last_states and last_states is not None:
                parts = []
                if (
                    current_states.active != last_states.active
                    or current_states.sub != last_states.sub
                ):
                    parts.append(f"{status.active_state}({status.sub_state})")
                if current_states.load != last_states.load:
                    parts.append(f"load={status.load_state}")
                if current_states.enabled != last_states.enabled:
                    parts.append(f"enabled={status.enabled}")
                _status_msg(" ".join(parts))
                last_states = current_states

            await asyncio.sleep(1)

    dispatcher.loop.call_soon_threadsafe(dispatcher.loop.create_task, _poll())


def main():
    """CLI entrypoint for the remote service control IOC."""
    parser = argparse.ArgumentParser(
        description="EPICS IOC for monitoring/controlling a system service"
    )
    parser.add_argument("prefix", help="PV prefix (e.g. 'XF:28ID-CT{Svc:MyApp}')")
    parser.add_argument(
        "service",
        help="Service name (e.g. 'my-app.service' for systemd, 'my-app' for init.d)",
    )
    parser.add_argument(
        "--host",
        default=None,
    )
    parser.add_argument(
        "--initd",
        action="store_true",
        help="Manage the service via init.d (SysV) instead of systemd",
    )
    parser.add_argument(
        "--sudo",
        action="store_true",
        help="For --initd, run control actions via 'sudo -n' (requires sudoers)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to a log file to tail for the Logs PV instead of the "
        "default journal/process output",
    )
    parser.add_argument(
        "--log-lines",
        type=int,
        default=20,
        help="Number of log lines to track (default: 20)",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"remote-svc-ctrl {__version__}"
    )
    args = parser.parse_args()

    if args.log_lines <= 0:
        parser.error("--log-lines must be a positive integer")

    create_ioc(
        args.prefix,
        args.service,
        args.host,
        use_initd=args.initd,
        log_file=args.log_file,
        log_lines=args.log_lines,
        use_sudo=args.sudo,
    )
    softioc.interactive_ioc(globals())


if __name__ == "__main__":
    main()
