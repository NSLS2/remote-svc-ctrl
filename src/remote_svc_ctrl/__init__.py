
import subprocess

def get_systemd_property(host: str, service: str, prop: str) -> str:
    """Get a single property from systemctl show."""
    try:
        result = subprocess.run(
            ["systemctl", "--host", host, "show", "-p", prop, "--value", service],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""