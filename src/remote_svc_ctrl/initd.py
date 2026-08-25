"""Init.d (SysV) service interaction via the `service` command."""

import re
import subprocess
from datetime import datetime

from .ssh import wrap_remote
from .systemd import MemoryUsage, ServiceStatus


def run_service(
    command: str, service: str, host: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run an init.d service action and return the completed process.

    Parameters
    ----------
    command : str
        The service action (e.g. "status", "start", "stop", "restart").
    service : str
        The init.d service name.
    host : str or None
        SSH target as user@host, or None for localhost.

    Returns
    -------
    subprocess.CompletedProcess
        The completed process, including returncode and captured output. The
        returncode is meaningful for "status" (LSB exit codes), so it is
        returned rather than discarded.
    """
    cmd = wrap_remote(["service", service, command], host)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if command != "status" and result.returncode != 0:
        msg = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Exit code {result.returncode}"
        )
        raise RuntimeError(msg)
    return result


def parse_initd_status(
    result: subprocess.CompletedProcess[str], service: str
) -> ServiceStatus:
    """Parse the output of `service <service> status` into a ServiceStatus.

    Init.d scripts do not emit a standard status format, so state is derived
    from output keywords where possible, falling back to the LSB exit code.
    Both stdout and stderr are captured into the logs. Memory, CPU and task
    counts are left at their defaults here; they are populated separately from
    the process PID, and the description is read from the init.d script.

    Parameters
    ----------
    result : subprocess.CompletedProcess
        The completed `service <service> status` process.
    service : str
        The init.d service name.
    """
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    lowered = combined.lower()

    # Prefer explicit keywords, then fall back to LSB status exit codes:
    # 0 = running, 3 = not running, 1/2 = dead (pid/lock file present).
    if re.search(r"\b(not running|stopped|dead|inactive)\b", lowered):
        active_state, sub_state = "inactive", "dead"
    elif re.search(r"\brunning\b", lowered):
        active_state, sub_state = "active", "running"
    elif result.returncode == 0:
        active_state, sub_state = "active", "running"
    elif result.returncode == 3:
        active_state, sub_state = "inactive", "dead"
    else:
        active_state, sub_state = "failed", "failed"

    main_pid = None
    pid_match = re.search(r"pid[:\s]+(\d+)", combined, re.IGNORECASE)
    if pid_match:
        main_pid = int(pid_match.group(1))

    return ServiceStatus(
        unit=service,
        description="",
        load_state="loaded",
        unit_file=f"/etc/init.d/{service}",
        enabled="",
        active_state=active_state,
        sub_state=sub_state,
        since=None,
        main_pid=main_pid,
        tasks=None,
        memory=MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0),
        cpu=0.0,
        cgroup="",
        logs=lines,
    )


def _parse_ps_cputime(raw: str) -> float:
    """Parse a ps CPU time like 'MM:SS', 'HH:MM:SS' or 'DD-HH:MM:SS' to seconds."""
    raw = raw.strip()
    if not raw:
        return 0.0
    days = 0
    if "-" in raw:
        day_part, raw = raw.split("-", 1)
        days = int(day_part)
    seconds = 0.0
    for part in raw.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds + days * 86400


def _parse_process_stats(output: str) -> tuple[MemoryUsage, float, int | None]:
    """Parse `ps -o rss=,cputime=,nlwp=` output into memory, CPU and task count."""
    parts = output.split()
    if len(parts) < 3:
        return MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0), 0.0, None
    rss_kb = float(parts[0])
    cpu = _parse_ps_cputime(parts[1])
    tasks = int(parts[2])
    memory = MemoryUsage(current=rss_kb * 1024, peak=0.0, swap=0.0, swap_peak=0.0)
    return memory, cpu, tasks


def get_process_stats(
    pid: int, host: str | None = None
) -> tuple[MemoryUsage, float, int | None]:
    """Return (memory, cpu_seconds, tasks) for a running PID via `ps`.

    Parameters
    ----------
    pid : int
        The process ID to inspect.
    host : str or None
        SSH target as user@host, or None for localhost.
    """
    cmd = wrap_remote(["ps", "-p", str(pid), "-o", "rss=,cputime=,nlwp="], host)
    empty = MemoryUsage(current=0.0, peak=0.0, swap=0.0, swap_peak=0.0), 0.0, None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return empty
    if result.returncode != 0:
        return empty
    return _parse_process_stats(result.stdout)


def _parse_ps_lstart(raw: str) -> datetime | None:
    """Parse a ps ``lstart`` value like 'Mon Aug 25 10:15:30 2026' to a datetime."""
    text = " ".join(raw.split())
    if not text:
        return None
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


def get_process_start(pid: int, host: str | None = None) -> datetime | None:
    """Return the start time of a running PID via `ps`, or None if unavailable.

    Parameters
    ----------
    pid : int
        The process ID to inspect.
    host : str or None
        SSH target as user@host, or None for localhost.
    """
    cmd = wrap_remote(["ps", "-p", str(pid), "-o", "lstart="], host)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    return _parse_ps_lstart(result.stdout)


def is_service_enabled(service: str, host: str | None = None) -> str:
    """Return the enabled state of a service from `chkconfig`.

    Returns "enabled" when chkconfig reports the service on for the current
    runlevel, "disabled" when it is off, and "" when the state is unknown
    (chkconfig missing or the service is not registered).

    Parameters
    ----------
    service : str
        The init.d service name.
    host : str or None
        SSH target as user@host, or None for localhost.
    """
    cmd = wrap_remote(["chkconfig", service], host)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return ""
    # `chkconfig <name>` exits 0 when on in the current runlevel, non-zero when
    # off; an error on stderr (e.g. unknown service) means the state is unknown.
    if result.returncode == 0:
        return "enabled"
    if result.stderr.strip():
        return ""
    return "disabled"


def read_process_logs(pid: int, host: str | None = None, lines: int = 20) -> list[str]:
    """Best-effort read of a process's stdout/stderr via /proc/<pid>/fd.

    Init.d daemons have no journal, so this follows the fd 1/2 symlinks and
    tails them when they point at a regular file. Pipes, sockets and
    /dev/null are skipped, and any error yields an empty list.

    Parameters
    ----------
    pid : int
        The process ID whose stdout/stderr to read.
    host : str or None
        SSH target as user@host, or None for localhost.
    lines : int
        Maximum number of trailing lines to read from each stream.
    """
    collected: list[str] = []
    seen: set[str] = set()
    for fd in ("1", "2"):
        resolve = wrap_remote(["readlink", "-f", f"/proc/{pid}/fd/{fd}"], host)
        try:
            target = subprocess.run(resolve, capture_output=True, text=True, timeout=10)
        except (subprocess.SubprocessError, OSError):
            continue
        path = target.stdout.strip()
        if (
            not path
            or path in seen
            or path.endswith("/dev/null")
            or "pipe:" in path
            or "socket:" in path
        ):
            continue
        seen.add(path)
        tail = wrap_remote(["tail", "-n", str(lines), path], host)
        try:
            result = subprocess.run(tail, capture_output=True, text=True, timeout=10)
        except (subprocess.SubprocessError, OSError):
            continue
        if result.returncode == 0:
            collected += [ln for ln in result.stdout.splitlines() if ln.strip()]
    return collected


def _parse_initd_description(content: str) -> str:
    """Extract a service description from init.d script LSB/chkconfig headers.

    Prefers the (possibly multi-line) LSB "Description" field, falling back to
    "Short-Description". A lowercase chkconfig "description" is also matched.
    """
    lines = content.splitlines()
    short_desc = ""
    description = ""
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        short_match = re.match(r"#\s*Short-Description:\s*(.*)", line, re.IGNORECASE)
        if short_match:
            short_desc = short_match.group(1).strip()
            i += 1
            continue
        desc_match = re.match(r"#\s*Description:\s*(.*)", line, re.IGNORECASE)
        if desc_match:
            parts = [desc_match.group(1).strip().rstrip("\\").strip()]
            j = i + 1
            while j < n:
                if "END INIT INFO" in lines[j] or re.match(
                    r"#\s*[A-Za-z][\w-]*:", lines[j]
                ):
                    break
                cont = re.match(r"#\s+(\S.*)", lines[j])
                if not cont:
                    break
                parts.append(cont.group(1).strip().rstrip("\\").strip())
                j += 1
            description = " ".join(part for part in parts if part)
            i = j
            continue
        i += 1
    return description or short_desc


def read_initd_description(service: str, host: str | None = None) -> str:
    """Read and parse the description from the init.d script for a service.

    Parameters
    ----------
    service : str
        The init.d service name (script under /etc/init.d).
    host : str or None
        SSH target as user@host, or None for localhost.
    """
    cmd = wrap_remote(["cat", f"/etc/init.d/{service}"], host)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return _parse_initd_description(result.stdout)
