"""EPICS soft IOC that monitors a systemd service and exposes PVs."""

import argparse
import asyncio
import logging
from datetime import datetime
from enum import IntEnum

from epicsdbbuilder import SetSimpleRecordNames
from softioc import builder, softioc
from softioc.asyncio_dispatcher import AsyncioDispatcher

from .systemd import parse_systemctl_status, run_systemctl

log = logging.getLogger(__name__)


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


class SubState(_StateEnum):
    """Systemd unit sub-states."""

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
    SetSimpleRecordNames(prefix=prefix, separator="")

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
        return last_states.get("ActiveState") == ActiveState.ACTIVE

    def _on_start(value):
        if value:
            if _is_active():
                _status_msg("Service is already running")
                return
            try:
                run_systemctl("start", service, host)
            except Exception as e:
                _status_msg(f"Start failed: {e}")

    def _on_stop(value):
        if value:
            if not _is_active():
                _status_msg("Service is already stopped")
                return
            try:
                run_systemctl("stop", service, host)
            except Exception as e:
                _status_msg(f"Stop failed: {e}")

    def _on_restart(value):
        if value:
            try:
                run_systemctl("restart", service, host)
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
    last_states: dict[str, int] = {}

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
                output = run_systemctl("status", service, host)
                status = parse_systemctl_status(output)
            except Exception:
                await asyncio.sleep(1)
                continue

            pv_unit.set(status.unit)
            pv_description.set(status.description)
            pv_load_state.set(_state_index(LoadState, status.load_state))
            pv_unit_file.set(status.unit_file)
            pv_enabled.set(_state_index(EnabledState, status.enabled))
            pv_active_state.set(_state_index(ActiveState, status.active_state))
            pv_sub_state.set(_state_index(SubState, status.sub_state))
            pv_since.set(_format_duration(status.since))
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
            current_states = {
                "ActiveState": _state_index(ActiveState, status.active_state),
                "SubState": _state_index(SubState, status.sub_state),
                "LoadState": _state_index(LoadState, status.load_state),
                "Enabled": _state_index(EnabledState, status.enabled),
            }
            if first_poll:
                _status_msg(
                    f"{status.active_state}({status.sub_state}) "
                    f"load={status.load_state} enabled={status.enabled}"
                )
                last_states.update(current_states)
                first_poll = False
            elif current_states != last_states:
                changed = [
                    k for k in current_states if current_states[k] != last_states.get(k)
                ]
                parts = []
                if "ActiveState" in changed or "SubState" in changed:
                    parts.append(f"{status.active_state}({status.sub_state})")
                if "LoadState" in changed:
                    parts.append(f"load={status.load_state}")
                if "Enabled" in changed:
                    parts.append(f"enabled={status.enabled}")
                _status_msg(" ".join(parts))
                last_states.update(current_states)

            await asyncio.sleep(1)

    dispatcher.loop.call_soon_threadsafe(dispatcher.loop.create_task, _poll())


def main():
    """CLI entrypoint for the remote service control IOC."""
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
    softioc.interactive_ioc(globals())


if __name__ == "__main__":
    main()
