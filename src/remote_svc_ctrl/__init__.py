"""Remote service control IOC package."""

import subprocess


def get_systemd_property(host: str, service: str, prop: str) -> str:
    """Get a single property from systemctl show."""
    try:
        result = subprocess.run(
            ["systemctl", "--host", host, "show", "-p", prop, "--value", service],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""
