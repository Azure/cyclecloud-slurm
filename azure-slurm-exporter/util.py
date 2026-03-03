import os

def is_file_binary(binary) -> bool:
    """
    Check if a file exists and is executable.
    """
    return os.path.isfile(binary) and os.access(binary, os.X_OK)