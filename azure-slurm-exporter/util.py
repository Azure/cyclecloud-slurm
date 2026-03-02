import os

def is_file_binary(binary) -> bool:
    """
    Check if a file exists and is executable.

    Args:
        binary (str): The file path to check.

    Returns:
        bool: True if the file exists and is executable, False otherwise.
    """
    return os.path.isfile(binary) and os.access(binary, os.X_OK)