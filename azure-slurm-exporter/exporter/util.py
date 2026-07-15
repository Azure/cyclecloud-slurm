import os
import logging
import subprocess

log = logging.getLogger(__name__)

def is_file_binary(binary) -> bool:
    """
    Check if a file exists and is executable.
    """
    return os.path.isfile(binary) and os.access(binary, os.X_OK)

def validate_port(port_env_var: str, default_port: int) -> int:
    """
    Validate and return a port number from environment variable.
    """
    try:
        raw_port = os.environ.get(port_env_var, default_port)
        port = int(raw_port)
        if not (1 <= port <= 65535):
            log.warning(
                "Invalid %s value '%s': must be between 1 and 65535. Defaulting to %d",
                port_env_var, raw_port, default_port
            )
            port = default_port
    except ValueError:
        log.warning(
            "Invalid %s value '%s': must be an integer between 1 and 65535. Defaulting to %d",
            port_env_var, raw_port, default_port
        )
        port = default_port

    return port

def get_scontrol_config_value(key: str, timeout: int = 10) -> str:
    """Run "scontrol show config" and return the value for a config key."""
    try:
        proc = subprocess.run(
            ["scontrol", "show", "config"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except Exception as e:
        log.warning("Failed to read scontrol config for %s: %s", key, e)
        return ""

    if proc.returncode != 0:
        log.warning(
            "scontrol show config failed (rc=%s) while reading %s: %s",
            proc.returncode,
            key,
            (proc.stderr or "").strip(),
        )
        return ""

    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if "=" not in stripped:
            continue
        lhs, rhs = stripped.split("=", 1)
        if lhs.strip() == key:
            return rhs.strip()

    return ""