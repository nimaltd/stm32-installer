"""
The stm32-installer command, now only a pointer to libNIMA.

--version still answers, so a script that checks it keeps working. Anything
else says where the installer went and what to type there, and installs
nothing, with exit code 1, so a script notices.
"""

import shlex
import sys

from . import __version__

NAME = "stm32-installer"

__all__ = ["main"]


def main(argv=None):
    """Say where stm32-installer went. Returns a process exit code."""
    argv = sys.argv[1:] if argv is None else list(argv)

    if argv[:1] in (["--version"], ["-V"]):
        print(f"{NAME} {__version__}")
        return 0

    same = "libnima " + (shlex.join(argv) if argv else "owner/example")
    print(
        f"{NAME} is now libNIMA: one installer for STM32, Zephyr, ESP-IDF, Arduino\n"
        "and PlatformIO, with a window and the libnima command, and no Python.\n"
        "Nothing was installed.\n"
        "\n"
        "Download libNIMA from https://github.com/nimaltd/libNIMA/releases/latest,\n"
        "then:\n"
        "\n"
        f"    pip uninstall {NAME}\n"
        f"    {same}\n"
        "\n"
        f"An STM32 project {NAME} installed into moves over by itself on the first run.\n"
        "https://github.com/nimaltd/libNIMA",
        file=sys.stderr,
    )

    return 1


if __name__ == "__main__":
    sys.exit(main())
