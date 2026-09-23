"""
Install NimaLTD embedded C libraries into an STM32 project.

Installed with pip it is the stm32-installer command. Without pip, the
install.py at the root of its repository fetches it into a temporary folder and
runs it, which can be piped straight into Python from the web. Either way it
takes a library from GitHub, from a downloaded zip, or from a folder.

See https://github.com/nimaltd/stm32-installer
"""

from .installer import InstallError, Result, install_in_place, install_to
from .manifest import Manifest, ManifestError, load

__version__ = "1.1.1"

__all__ = [
    "InstallError",
    "Manifest",
    "ManifestError",
    "Result",
    "install_in_place",
    "install_to",
    "load",
    "main",
]


def main(argv=None, library_root=None):
    """Run the command line interface. Imported lazily to keep start-up cheap."""
    from .cli import main as _main

    return _main(argv=argv, library_root=library_root)
