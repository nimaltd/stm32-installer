"""
stm32-installer is now libNIMA.

This last release only says so. libNIMA does what stm32-installer did, for STM32,
Zephyr, ESP-IDF, Arduino and PlatformIO alike, with a window and the libnima
command: https://github.com/nimaltd/libNIMA
"""

__version__ = "3.0.1"

__all__ = ["main"]


def main(argv=None):
    """Say where stm32-installer went. Returns a process exit code."""
    from .cli import main as _main

    return _main(argv=argv)
