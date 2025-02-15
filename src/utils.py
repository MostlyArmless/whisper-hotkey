import os
import subprocess


def setup_display() -> None:
    """Set up the DISPLAY environment variable for X11 GUI operations.
    This is particularly important when running as a service."""
    try:
        # Try to get the current display from the 'w' command output
        display = subprocess.check_output(["w", "-hs"]).decode().split()[2]
        os.environ["DISPLAY"] = display
    except (subprocess.SubprocessError, IndexError):
        # Fall back to :0 if we can't determine the display
        os.environ["DISPLAY"] = ":0"
