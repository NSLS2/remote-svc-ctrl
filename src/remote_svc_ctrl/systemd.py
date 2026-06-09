import re
import subprocess
from dataclasses import dataclass
from datetime import datetime


def run_systemctl(command: str, service: str, host: str | None = None) -> str:
    """Run a systemctl subcommand against a service and return stdout.

    Parameters
    ----------
    command : str
        The systemctl subcommand (e.g. "status", "start", "stop", "restart").
    service : str
        The systemd unit name.
    host : str or None
        SSH target as user@host, or None for localhost.
    """
    cmd = ["systemctl"]
    if host:
        cmd += ["--host", host]
    cmd += [command, service]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    return result.stdout


@dataclass
class ServiceStatus:
    unit: str
    description: str
    load_state: str
    unit_file: str
    enabled: str
    active_state: str
    sub_state: str
    since: datetime | None
    main_pid: int | None
    tasks: int | None
    memory: str
    cpu: str
    cgroup: str


def parse_systemctl_status(output: str) -> ServiceStatus:
    """Parse the output of `systemctl status <service>` into a ServiceStatus."""

    lines = output.strip().splitlines()

    # First line: ● sshd.service - OpenSSH server daemon
    unit = ""
    description = ""
    if lines:
        match = re.match(r"[●○×]\s+(\S+?)(?:\s+-\s+(.*))?$", lines[0])
        if match:
            unit = match.group(1)
            description = match.group(2) or ""

    def _get_field(field: str) -> str:
        for line in lines:
            match = re.match(rf"\s*{field}:\s+(.*)", line)
            if match:
                return match.group(1).strip()
        return ""

    # Loaded: loaded (/usr/lib/systemd/system/sshd.service; enabled; preset: enabled)
    load_state = ""
    unit_file = ""
    enabled = ""
    loaded_raw = _get_field("Loaded")
    loaded_match = re.match(r"(\w+)\s+\(([^;]+);\s*(\w+)", loaded_raw)
    if loaded_match:
        load_state = loaded_match.group(1)
        unit_file = loaded_match.group(2)
        enabled = loaded_match.group(3)

    # Active: active (running) since Fri 2026-05-08 06:40:50 EDT; 1 month 0 days ago
    active_state = ""
    sub_state = ""
    since: datetime | None = None
    active_raw = _get_field("Active")
    active_match = re.match(r"(\w+)\s+\((\w+)\)(?:\s+since\s+(.+?)(?:;.*)?)?$", active_raw)
    if active_match:
        active_state = active_match.group(1)
        sub_state = active_match.group(2)
        since_str = active_match.group(3)
        if since_str:
            # Format: "Fri 2026-05-08 06:40:50 EDT"
            # Strip timezone abbreviation and parse
            since_parts = re.match(r"\w+\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", since_str)
            if since_parts:
                since = datetime.strptime(since_parts.group(1), "%Y-%m-%d %H:%M:%S")
    elif active_raw:
        # Handle "inactive (dead)" with no since
        simple_match = re.match(r"(\w+)\s+\((\w+)\)", active_raw)
        if simple_match:
            active_state = simple_match.group(1)
            sub_state = simple_match.group(2)

    # Main PID: 3470042 (sshd)
    main_pid = None
    pid_raw = _get_field("Main PID")
    pid_match = re.match(r"(\d+)", pid_raw)
    if pid_match:
        main_pid = int(pid_match.group(1))

    # Tasks: 1 (limit: 3355442)
    tasks = None
    tasks_raw = _get_field("Tasks")
    tasks_match = re.match(r"(\d+)", tasks_raw)
    if tasks_match:
        tasks = int(tasks_match.group(1))

    memory = _get_field("Memory")
    cpu = _get_field("CPU")
    cgroup = _get_field("CGroup")

    return ServiceStatus(
        unit=unit,
        description=description,
        load_state=load_state,
        unit_file=unit_file,
        enabled=enabled,
        active_state=active_state,
        sub_state=sub_state,
        since=since,
        main_pid=main_pid,
        tasks=tasks,
        memory=memory,
        cpu=cpu,
        cgroup=cgroup,
    )

