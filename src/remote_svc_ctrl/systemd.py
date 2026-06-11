"""Systemd service interaction via systemctl."""

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
    cmd = ["systemctl", "--no-pager", "--no-ask-password"]
    if host:
        cmd += ["--host", host]
    cmd += [command, service]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode not in (0, 3):
        # returncode 3 = unit not active (normal for "status" on stopped services)
        msg = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Exit code {result.returncode}"
        )
        raise RuntimeError(msg)
    return result.stdout


@dataclass
class MemoryUsage:
    """Parsed memory values in bytes."""

    current: float
    peak: float
    swap: float
    swap_peak: float


@dataclass
class ServiceStatus:
    """Parsed systemctl status output."""

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
    memory: MemoryUsage
    cpu: float
    cgroup: str
    logs: list[str]


def _parse_memory_value(text: str) -> float:
    """Parse a memory string like '176K' or '22.7M' into bytes."""
    match = re.match(r"([\d.]+)\s*([KMGT]?)", text.strip())
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2)
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    return value * multipliers.get(unit, 1)


def _parse_cpu_time(raw: str) -> float:
    """Parse CPU time like '5.227s', '1min 5.227s', '1h 2min 3.456s' to seconds."""
    total = 0.0
    for match in re.finditer(r"([\d.]+)\s*(h|min|ms|s)", raw):
        value = float(match.group(1))
        unit = match.group(2)
        if unit == "h":
            total += value * 3600
        elif unit == "min":
            total += value * 60
        elif unit == "s":
            total += value
        elif unit == "ms":
            total += value / 1000
    return total


def _parse_memory_field(raw: str) -> MemoryUsage:
    """Parse Memory field like '176K (peak: 22.7M, swap: 1.2M, swap peak: 1.2M)'."""
    current = 0.0
    peak = 0.0
    swap = 0.0
    swap_peak = 0.0

    # Current value is the first token before any parentheses
    current_match = re.match(r"([\d.]+\s*[KMGT]?)", raw)
    if current_match:
        current = _parse_memory_value(current_match.group(1))

    # Parenthesized fields
    peak_match = re.search(r"peak:\s*([\d.]+\s*[KMGT]?)", raw)
    if peak_match:
        peak = _parse_memory_value(peak_match.group(1))

    swap_peak_match = re.search(r"swap peak:\s*([\d.]+\s*[KMGT]?)", raw)
    if swap_peak_match:
        swap_peak = _parse_memory_value(swap_peak_match.group(1))

    # swap: (but not "swap peak:")
    swap_match = re.search(r"(?<!peak)swap:\s*([\d.]+\s*[KMGT]?)", raw)
    if swap_match:
        swap = _parse_memory_value(swap_match.group(1))

    return MemoryUsage(current=current, peak=peak, swap=swap, swap_peak=swap_peak)


def _parse_log_lines(lines: list[str]) -> list[str]:
    """Extract log lines from status output, keeping only timestamp + message."""
    logs = []
    # Log lines start with a date like "Jun 10 09:21:40 hostname process[pid]: message"
    log_pattern = re.compile(
        r"(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+\S+?\[\d+\]:\s+(.*)"
    )
    for line in lines:
        match = log_pattern.match(line.strip())
        if match:
            timestamp = match.group(1)
            message = match.group(2)
            logs.append(f"{timestamp} {message}")
    return logs


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
    active_match = re.match(
        r"(\w+)\s+\((\w+)\)(?:\s+since\s+(.+?)(?:;.*)?)?$", active_raw
    )
    if active_match:
        active_state = active_match.group(1)
        sub_state = active_match.group(2)
        since_str = active_match.group(3)
        if since_str:
            # Format: "Fri 2026-05-08 06:40:50 EDT"
            # Strip timezone abbreviation and parse
            since_parts = re.match(
                r"\w+\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", since_str
            )
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

    memory = _parse_memory_field(_get_field("Memory"))
    cpu_raw = _get_field("CPU")
    cpu = _parse_cpu_time(cpu_raw)
    cgroup = _get_field("CGroup")
    logs = _parse_log_lines(lines)

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
        logs=logs,
    )
