"""
Colored terminal output.

No dependency on colorama. Windows 10 and later can render ANSI escapes once
virtual terminal processing is switched on, which is done here at import time.
Where that fails, and wherever the output is not a terminal, every helper
degrades to plain text rather than printing escape codes into a log file.

Honours the NO_COLOR convention, see https://no-color.org
"""

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GREY = "\033[90m"


def _enable_windows_ansi():
    """Turn on virtual terminal processing. Returns True when colour is usable."""
    if os.name != "nt":
        return True

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # -11 is STD_OUTPUT_HANDLE, 0x0004 is ENABLE_VIRTUAL_TERMINAL_PROCESSING.
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()

        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return False

        return kernel32.SetConsoleMode(handle, mode.value | 0x0004) != 0
    except Exception:
        return False


def _supported():
    """Whether to emit escape codes at all."""
    if os.environ.get("NO_COLOR") is not None:
        return False

    if os.environ.get("TERM") == "dumb":
        return False

    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False

    return _enable_windows_ansi()


ENABLED = _supported()


def paint(text, *codes):
    """Wrap text in escape codes, or return it untouched when colour is off."""
    if not ENABLED or not codes:
        return text

    return "".join(codes) + str(text) + RESET


def title(text):
    return paint(text, BOLD, CYAN)


def good(text):
    return paint(text, GREEN)


def warn(text):
    return paint(text, YELLOW)


def bad(text):
    return paint(text, RED)


def note(text):
    return paint(text, GREY)


def strong(text):
    return paint(text, BOLD)


def banner(name, version, description=""):
    """The block printed before anything is written."""
    head = paint(name, BOLD, CYAN)

    # A library whose header carries no @version simply shows none.
    if version:
        head += f" {paint(version, DIM)}"

    lines = [head]

    if description:
        lines.append(note(description))

    return "\n".join(lines)


def item(mark, label, path, colour=None):
    """
    One line of the file report.

    The mark is a short word, so the column stays aligned and the output still
    reads correctly when colour is off or the font has no symbols.
    """
    painted = paint(f"{mark:<8}", colour) if colour else f"{mark:<8}"

    return f"  {painted}{path}{('  ' + note(label)) if label else ''}"


def heading(text):
    """A section heading inside the output."""
    return paint(text, BOLD)


def bullet(text, colour=None):
    return f"  {paint('-', GREY)} {paint(text, colour) if colour else text}"
