#!/usr/bin/env python3
"""
Run stm32-installer without installing anything.

Straight from the web, from the root of your STM32 project:

    PowerShell
        irm https://raw.githubusercontent.com/nimaltd/stm32-installer/main/install.py | python - nimaltd/example

    Command Prompt, Linux, macOS (python3 on the last two)
        curl -fsSL https://raw.githubusercontent.com/nimaltd/stm32-installer/main/install.py | python - nimaltd/example

Everything after the "-" goes to the installer, so this takes whatever the
stm32-installer command takes: a library name, "owner/name", a GitHub URL, a
downloaded .zip or a folder, and the same options, --ref included.

The installer is fetched into a temporary folder, run, and deleted. Nothing is
installed on your machine, and nothing but the library lands in your project.

Kept beside the installer's own src folder, as it is in a download of this
repository, it runs that copy instead of fetching one, so it works with no
network at all:

    python stm32-installer-main/install.py D:/Downloads/example-master.zip
"""

import io
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# Where the installer comes from. Anyone maintaining their own libraries with
# this tool points this at their own fork and changes nothing else.
SOURCE = "https://github.com/nimaltd/stm32-installer/archive/refs/heads/main.zip"

MODULE = "stm32_installer"
TIMEOUT_SECONDS = 30

USAGE = """\
Say what to install, for example:

    python install.py nimaltd/example
    python install.py D:/Downloads/example-master.zip

or pipe this file into Python from the web, as the stm32-installer README shows.
"""


def here():
    """
    The folder this file sits in, or None when it has none.

    Piped into Python there is no file: __file__ reads "<stdin>", and on Windows
    that name is not even a legal path.
    """
    try:
        path = Path(__file__)
        return path.resolve().parent if path.is_file() else None
    except (NameError, OSError):
        return None


def load(extra_path=None):
    """Import the installer, optionally from a folder put first on the path."""
    if extra_path is not None and str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))

    try:
        return __import__(MODULE)
    except ImportError:
        return None


def load_beside():
    """The installer from a src folder next to this file, when there is one."""
    folder = here()

    if folder is None or not (folder / "src" / MODULE).is_dir():
        return None

    return load(folder / "src")


def fetch_to(folder):
    """
    Download the installer and unpack it. Returns the folder to import from.

    None when it could not be fetched, which is not fatal on its own: an already
    installed copy is tried next.
    """
    try:
        with urllib.request.urlopen(SOURCE, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except (urllib.error.URLError, OSError) as error:
        print(f"Could not reach GitHub: {error}", file=sys.stderr)
        return None

    try:
        zipfile.ZipFile(io.BytesIO(raw)).extractall(folder)
    except (zipfile.BadZipFile, OSError) as error:
        print(f"The download was not a usable archive: {error}", file=sys.stderr)
        return None

    # The archive holds one top level folder named after the repository and branch.
    found = sorted(folder.glob("*/src"))

    if not found:
        print("The download did not contain the installer.", file=sys.stderr)
        return None

    return found[0]


def install_with_pip():
    """
    Last resort: let pip fetch it.

    Worth having for one reason. pip carries its own certificates and honours
    proxy settings, so on a network where Python's own download fails, pip often
    still gets through.
    """
    print("Falling back to pip ...", flush=True)

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", SOURCE]
        )
    except (subprocess.CalledProcessError, OSError):
        return None

    return load()


def get_installer(staging):
    """The installer module, however it can be got hold of."""
    installer = load_beside()

    if installer is not None:
        return installer

    print("Fetching the installer ...", flush=True)

    installer = load(fetch_to(staging))

    if installer is None:
        # A copy installed with pip, for a machine that cannot reach GitHub.
        installer = load()

    if installer is None:
        installer = install_with_pip()

    return installer


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        print(USAGE, file=sys.stderr)
        return 2

    staging = Path(tempfile.mkdtemp(prefix="stm32-install-"))

    try:
        installer = get_installer(staging)

        if installer is None:
            print(
                "\nCould not get the installer.\n"
                "Check that this machine can reach github.com and try again.",
                file=sys.stderr,
            )
            return 2

        return installer.main(argv=argv)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
