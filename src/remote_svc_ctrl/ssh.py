"""Shared SSH helpers with connection multiplexing.

Both the systemd and init.d backends run remote commands over ssh. These
helpers wrap commands so that repeated calls reuse a single persistent master
connection (ControlMaster) instead of re-authenticating every time.
"""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from .log import logger

# Seconds to keep the shared ssh master connection alive after its last use.
CONTROL_PERSIST = 60


def control_path(host: str) -> str:
    """Return the ssh ControlPath socket used to multiplex a host's session.

    Includes the uid so sockets do not collide between users on a shared host,
    and uses SHA-256 (usedforsecurity=False) to avoid FIPS-mode restrictions.
    """
    digest = hashlib.sha256(host.encode(), usedforsecurity=False).hexdigest()[:16]
    name = f"remote-svc-ctrl-{os.getuid()}-{digest}.sock"
    return str(Path(tempfile.gettempdir()) / name)


def wrap_remote(args: list[str], host: str | None) -> list[str]:
    """Wrap a command in a non-interactive ssh call when a host is given.

    Uses ssh connection multiplexing (ControlMaster) so repeated remote
    commands reuse a single persistent connection instead of re-authenticating
    on every call.
    """
    if host:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={control_path(host)}",
            "-o",
            f"ControlPersist={CONTROL_PERSIST}",
        ]
        # Ensure /sbin and /usr/sbin are on PATH for remote commands.
        cmd.extend([host, "PATH=$PATH:/sbin:/usr/sbin", *args])
        logger.debug(f"Remote command on {host}: {args}")
        return cmd
    return args


def close_connection(host: str | None) -> None:
    """Close the shared ssh master connection for a host, if one is open.

    Safe to call when no host is set or no master exists; errors are ignored.
    """
    if not host:
        return
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ControlPath={control_path(host)}",
        "-O",
        "exit",
        host,
    ]
    try:
        logger.info(f"Closing SSH master connection to {host}")
        subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        logger.warning(f"Failed to close SSH connection to {host}", exc_info=True)


def read_log_file(
    path: str,
    host: str | None = None,
    lines: int = 20,
) -> list[str]:
    """Return the last ``lines`` lines of a log file, locally or over ssh.

    Any error (missing file, permission denied, ssh failure) yields an empty
    list rather than raising.

    Parameters
    ----------
    path : str
        Path to the log file to tail.
    host : str or None
        SSH target as user@host, or None for localhost.
    lines : int
        Maximum number of trailing lines to return.
    """
    cmd = wrap_remote(["tail", "-n", str(lines), path], host)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        logger.error(f"Failed to read log file {path}", exc_info=True)
        return []
    if result.returncode != 0:
        logger.warning(
            f"Log file {path} returned exit code {result.returncode}: "
            f"{result.stderr.strip()}"
        )
        return []
    log_lines = [line for line in result.stdout.splitlines() if line.strip()]
    logger.debug(f"Read {len(log_lines)} lines from {path}")
    return log_lines
