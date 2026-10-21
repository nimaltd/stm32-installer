"""
stm32-installer is now lib-installer.

This last release only says so. lib-installer does what stm32-installer did, for
STM32, Zephyr, ESP-IDF, Arduino and PlatformIO alike, with the same commands:
https://github.com/nimaltd/lib-installer
"""

__version__ = "3.0.0"

__all__ = ["main"]


def main(argv=None):
    """Say where stm32-installer went. Returns a process exit code."""
    from .cli import main as _main

    return _main(argv=argv)
