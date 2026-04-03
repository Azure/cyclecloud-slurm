import os
import logging

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