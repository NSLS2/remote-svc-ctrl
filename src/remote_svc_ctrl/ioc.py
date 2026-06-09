"""EPICS soft IOC that monitors a systemd service and exposes PVs."""

import argparse
import threading
import time

from softioc import builder, softioc

from .systemd import parse_systemctl_status, run_systemctl


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
    pv_load_state = builder.stringIn("LoadState", initial_value="")
    pv_unit_file = builder.stringIn("UnitFile", initial_value="")
    pv_enabled = builder.stringIn("Enabled", initial_value="")
    pv_active_state = builder.stringIn("ActiveState", initial_value="")
    pv_sub_state = builder.stringIn("SubState", initial_value="")
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
            pv_load_state.set(status.load_state)
            pv_unit_file.set(status.unit_file)
            pv_enabled.set(status.enabled)
            pv_active_state.set(status.active_state)
            pv_sub_state.set(status.sub_state)
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
